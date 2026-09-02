"""Conductor — Product Management Pipelines (Amazon SP-API).

A *product pipeline* turns Amazon's canonical product-type definition into an
actionable listing workflow. The source of truth is the Selling Partner API
endpoint `getDefinitionsProductType`:

    GET /definitions/2020-09-01/productTypes/{productType}/definitions
        ?marketplaceIds=<id1,id2>&locale=en_US&requirements=LISTING

That returns a JSON-schema describing every attribute the product type accepts
— which are `required`, each attribute's type / allowed values (`enum`) /
length bounds / patterns / description / example, grouped into display groups.

This module fetches that definition (LWA auth: refresh_token + client_id +
client_secret → access_token), caches it, and derives a pipeline from it:

  1. Required attributes      — the `schema.required` list
  2. Attribute table          — every property w/ type, enum, bounds, group
  3. Flat-file columns        — columns generated from the schema
  4. Attribute guidelines     — required / allowed_values / pattern / min-max rules
  5. Catalog readiness        — which catalog products satisfy required attrs

Execution honesty contract: live SP-API calls happen ONLY when real LWA
credentials are configured (`refresh_token`, or a direct `access_token`).
Otherwise fetch falls back to bundled sample definitions and is explicitly
labelled `source: "bundled"`. Generated flat files / guidelines write into the
existing `flatfile_templates` / `attribute_guidelines` tables.

Router prefix: /api/productpipeline
"""
from __future__ import annotations

import csv
import json
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

import asin_sources
import storage

router = APIRouter(prefix="/api/productpipeline", tags=["productpipeline"])

CONFIG_PATH = storage.DATA_DIR / "spapi.json"
TOKEN_URL = "https://api.amazon.com/auth/o2/token"

# LWA region → SP-API host (getDefinitionsProductType is a selling-partner call).
REGIONS = {
    "na": "https://sellingpartnerapi-na.amazon.com",
    "eu": "https://sellingpartnerapi-eu.amazon.com",
    "fe": "https://sellingpartnerapi-fe.amazon.com",
}

# Common marketplace IDs → friendly code (for the picker + display).
MARKETPLACES = {
    "ATVPDKIKX0DER": "US",
    "A2EUQ1WTGCTBG2": "CA",
    "A1AM78C64UM0Y8": "MX",
    "A1F83G8C2ARO7P": "UK",
    "A1PA6795UKMFR9": "DE",
    "A13V1IB3VIYZZH": "FR",
    "APJ6JRA9NG5V4": "IT",
    "A1RKKUPIHCS9HS": "ES",
    "A1VC38T7YXB528": "JP",
    "A39IBJ37TRP1C6": "AU",
}

REQUIREMENTS = ["LISTING", "LISTING_PRODUCT_ONLY", "LISTING_OFFER_ONLY"]


# ---------------------------------------------------------------------------
# Product Registry — seven-stage lifecycle
#
# ONE canonical record per product/upload (product_registry_items). Stage
# lives as a field on that record (`stage`) plus full history in
# product_registry_transitions — rows are never duplicated per stage.
#
# `file_type` (what KIND of data this is) and `stage` (WHERE the record is
# in the seven-stage workflow) are kept as SEPARATE fields. Before adding
# them this way, the existing schema was checked for an already-approved
# combined model: `product_pipelines` (above, in this same file) already
# keeps `product_type` and `status` as two separate columns rather than
# one combined field, and no table anywhere in this codebase (grepped
# across backend/*.py and supabase/*.sql) combines a content-type and a
# lifecycle-status into a single column. So there is no existing combined
# model to preserve — separate fields both match the one precedent that
# does exist (product_pipelines) and are what was asked for.
#
# Shape mirrors backend/spine.py's LIFECYCLES convention (key, label,
# description, sort_order, terminal, transitions) rather than inventing a
# second lifecycle-modeling idiom, and mirrors the seven stages seeded
# into Postgres by supabase/migrations/20260901_0002_product_registry_lifecycle.sql.
# ---------------------------------------------------------------------------
REGISTRY_STAGES: list[tuple[str, str, str, int, bool, list[str]]] = [
    ("suggested", "Suggested", "Recommended candidate — not yet staged for work.", 10, False, ["staging", "archive"]),
    ("staging", "Staging", "Selected and being assembled/prepared.", 20, False, ["review", "archive"]),
    ("review", "Review", "Awaiting human review of the prepared data.", 30, False, ["analysis", "staging", "archive"]),
    ("analysis", "Analysis", "Under compliance/attribute analysis.", 40, False, ["submitted", "staging", "archive"]),
    ("submitted", "Submitted", "Submitted to the marketplace (SP-API) for publish.", 50, False, ["live", "analysis", "archive"]),
    ("live", "Live", "Published and active on the marketplace.", 60, False, ["archive"]),
    ("archive", "Archive", "Retired; historical record only.", 70, True, []),
]
REGISTRY_STAGE_KEYS = [s[0] for s in REGISTRY_STAGES]
REGISTRY_TRANSITIONS = {s[0]: s[5] for s in REGISTRY_STAGES}
REGISTRY_DEFAULT_STAGE = REGISTRY_STAGE_KEYS[0]  # "suggested"

# Registry types a user chooses at upload time — echoes the dataset keys
# already seeded by backend/spine.py / spine_sync_supabase.sql
# (keepa_products, catalog_products, suggested_content) so terminology
# stays consistent across the app, singularised for a per-record type tag.
REGISTRY_TYPES = [
    "asin_list",
    "catalog_product",
    "keepa_export",
    "suggested_content",
    "compliance_document",
    "other",
]

# Registry types whose rows are expected to carry ASIN-shaped values in
# at least one column — used to decide whether to run ASIN validation
# during upload, and which registry rows asin_sources.py's "recommended"
# resolver treats as a product-data upload vs. an ASIN list.
_ASIN_BEARING_TYPES = {"asin_list", "catalog_product", "keepa_export"}
_ASIN_COLUMN_CANDIDATES = ("asin", "asins", "sku", "product_id", "value")


# ---------------------------------------------------------------------------
# schema
# ---------------------------------------------------------------------------
def init_product_pipeline_db() -> None:
    conn = storage._conn()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS product_pipelines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            product_type TEXT NOT NULL,
            marketplace_id TEXT NOT NULL,
            locale TEXT DEFAULT 'en_US',
            requirements TEXT DEFAULT 'LISTING',
            definition TEXT NOT NULL,      -- full getDefinitionsProductType JSON
            source TEXT NOT NULL,          -- live | bundled
            status TEXT DEFAULT 'draft',   -- draft | ready
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS product_registry_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_key TEXT NOT NULL,           -- sku/asin, or upload_id when the record is file-only
            name TEXT DEFAULT '',
            file_type TEXT NOT NULL,          -- registry type chosen at upload — see REGISTRY_TYPES (kept SEPARATE from `stage`)
            stage TEXT NOT NULL DEFAULT 'suggested',   -- lifecycle stage — see REGISTRY_STAGES (kept SEPARATE from `file_type`)
            asin_source TEXT DEFAULT '',      -- connected | uploaded | recommended | manual (see asin_sources.py)
            upload_id TEXT,
            upload_status TEXT DEFAULT '',    -- uploading | ready | parsing | done | error (matches storage.py's files.status vocabulary)
            product_id INTEGER,               -- linked catalog product (storage.products.id), if any
            raw TEXT DEFAULT '{}',            -- json: raw ingested payload (filename/size/original text, capped)
            parsed TEXT DEFAULT '{}',         -- json: normalized rows / extracted ASIN rows
            validation TEXT DEFAULT '{}',     -- json: {"ok": bool, "errors": [...], ...} from the last validation pass
            provenance TEXT DEFAULT '{}',     -- json: per-ASIN/per-field provenance
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS product_registry_transitions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER NOT NULL,
            from_stage TEXT,
            to_stage TEXT NOT NULL,
            note TEXT DEFAULT '',
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_registry_items_stage ON product_registry_items(stage)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_registry_items_file_type ON product_registry_items(file_type)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_registry_items_key ON product_registry_items(item_key)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_registry_transitions_item ON product_registry_transitions(item_id)")
    conn.commit()


# ---------------------------------------------------------------------------
# config (data/spapi.json + SPAPI_* env overrides)
# ---------------------------------------------------------------------------
def _load_config() -> dict:
    cfg = {}
    if CONFIG_PATH.exists():
        try:
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            cfg = {}
    cfg["refresh_token"] = cfg.get("refresh_token") or os.environ.get("SPAPI_REFRESH_TOKEN", "")
    cfg["client_id"] = cfg.get("client_id") or os.environ.get("SPAPI_CLIENT_ID", "")
    cfg["client_secret"] = cfg.get("client_secret") or os.environ.get("SPAPI_CLIENT_SECRET", "")
    cfg["access_token"] = cfg.get("access_token") or os.environ.get("SPAPI_ACCESS_TOKEN", "")
    region = str(cfg.get("region") or "na").lower()
    cfg["region"] = region if region in REGIONS else "na"
    return cfg


def _save_config(cfg: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def _mask(s: str) -> str:
    return (f"****{s[-4:]}" if len(s) >= 4 else "****") if s else ""


def get_config() -> dict:
    cfg = _load_config()
    has_key = bool(cfg["access_token"]) or bool(cfg["refresh_token"] and cfg["client_id"] and cfg["client_secret"])
    return {
        "has_key": has_key,
        "auth_mode": "access_token" if cfg["access_token"] else ("lwa" if has_key else "none"),
        "refresh_token_masked": _mask(cfg["refresh_token"]),
        "client_id_masked": _mask(cfg["client_id"]),
        "access_token_masked": _mask(cfg["access_token"]),
        "region": cfg["region"],
        "regions": [{"id": k, "host": v} for k, v in REGIONS.items()],
        "marketplaces": [{"id": k, "code": v} for k, v in sorted(MARKETPLACES.items(), key=lambda x: x[1])],
        "requirements": REQUIREMENTS,
    }


# ---------------------------------------------------------------------------
# SP-API client (LWA auth → getDefinitionsProductType)
# ---------------------------------------------------------------------------
def _access_token(cfg: dict) -> str:
    """Return a live access token: direct override, else LWA refresh exchange."""
    if cfg.get("access_token"):
        return cfg["access_token"]
    if not (cfg.get("refresh_token") and cfg.get("client_id") and cfg.get("client_secret")):
        raise HTTPException(400, "SP-API credentials not configured — add a refresh_token (or access_token) in the Product Pipelines view.")
    data = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": cfg["refresh_token"],
        "client_id": cfg["client_id"],
        "client_secret": cfg["client_secret"],
    }).encode("utf-8")
    req = urllib.request.Request(
        TOKEN_URL, data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
                 "User-Agent": "Conductor/1.3"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise HTTPException(502, f"LWA token exchange failed ({exc.code}): {detail}")
    except urllib.error.URLError as exc:
        raise HTTPException(502, f"LWA token exchange unreachable: {exc.reason}")
    token = payload.get("access_token")
    if not token:
        raise HTTPException(502, f"LWA token exchange returned no access_token: {json.dumps(payload)[:200]}")
    return token


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _fetch_definition(product_type: str, marketplace_ids: list[str], locale: str,
                      requirements: str) -> dict:
    cfg = _load_config()
    token = _access_token(cfg)
    host = REGIONS[cfg["region"]]
    params = urllib.parse.urlencode({
        "marketplaceIds": ",".join(marketplace_ids),
        "locale": locale,
        "requirements": requirements,
    })
    url = f"{host}/definitions/2020-09-01/productTypes/{urllib.parse.quote(product_type)}/definitions?{params}"
    req = urllib.request.Request(url, headers={
        "x-amz-access-token": token,
        "x-amz-date": _iso_now(),
        "User-Agent": "Conductor/1.3",
    })
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise HTTPException(502, f"SP-API getDefinitionsProductType error {exc.code}: {detail}")
    except urllib.error.URLError as exc:
        raise HTTPException(502, f"SP-API unreachable: {exc.reason}")


def _fetch_search(keywords: str, marketplace_ids: list[str]) -> list[dict]:
    cfg = _load_config()
    token = _access_token(cfg)
    host = REGIONS[cfg["region"]]
    params = urllib.parse.urlencode({
        "keywords": keywords,
        "marketplaceIds": ",".join(marketplace_ids),
    })
    url = f"{host}/definitions/2020-09-01/productTypes?{params}"
    req = urllib.request.Request(url, headers={
        "x-amz-access-token": token,
        "x-amz-date": _iso_now(),
        "User-Agent": "Conductor/1.3",
    })
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            return payload.get("productTypes") or []
    except (urllib.error.HTTPError, urllib.error.URLError) as exc:
        detail = getattr(exc, "reason", str(exc))
        raise HTTPException(502, f"SP-API searchDefinitionsProductTypes failed: {detail}")


# ---------------------------------------------------------------------------
# Bundled sample definitions (offline / no-key fallback, clearly labelled)
# ---------------------------------------------------------------------------
def _bundled_definition(product_type: str, marketplace_ids: list[str], locale: str,
                        requirements: str) -> dict:
    return {
        "productType": product_type,
        "marketplaceIds": marketplace_ids,
        "locale": locale,
        "requirements": requirements,
        "requirementsEnforced": "ENFORCED",
        "source": "bundled",
        "schema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "properties": {
                "item_name": {
                    "type": "string", "minLength": 1, "maxLength": 500,
                    "description": "The title of the product shown to buyers.",
                    "example": "Premium hardshell carry-on spinner, 20 inch",
                },
                "brand_name": {
                    "type": "string", "minLength": 1, "maxLength": 50,
                    "description": "The brand under which the product is sold.",
                    "example": "Acme Travel",
                },
                "item_type": {
                    "type": "string",
                    "description": "Keywords describing the product category.",
                    "example": "luggage",
                },
                "color": {
                    "type": "string",
                    "enum": ["Black", "Navy", "Gray", "Red", "Blue"],
                    "description": "The color of the product.",
                    "example": "Black",
                },
                "size": {
                    "type": "string",
                    "description": "The size variation of the product.",
                    "example": "20 inch",
                },
                "material": {
                    "type": "string",
                    "description": "Primary material composition.",
                    "example": "Polycarbonate",
                },
                "item_weight": {
                    "type": "number", "format": "decimal",
                    "description": "Shipping weight in pounds.",
                    "example": 7.5,
                },
                "country_of_origin": {
                    "type": "string", "maxLength": 2,
                    "description": "ISO-3166-1 alpha-2 country code of origin.",
                    "example": "CN",
                },
                "bullet_point1": {
                    "type": "string", "maxLength": 500,
                    "description": "First marketing bullet point.",
                },
                "bullet_point2": {
                    "type": "string", "maxLength": 500,
                    "description": "Second marketing bullet point.",
                },
                "product_description": {
                    "type": "string", "maxLength": 2000,
                    "description": "Long-form description of the product.",
                },
                "recommended_browse_nodes": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Amazon browse node IDs to classify the listing.",
                    "example": ["9479196011"],
                },
                "sku": {
                    "type": "string", "minLength": 1, "maxLength": 40,
                    "description": "Seller SKU for the offer.",
                    "example": "ACME-CARRY-20-BLK",
                },
                "standard_price": {
                    "type": "number", "format": "decimal",
                    "description": "List price in the marketplace currency.",
                    "example": 129.99,
                },
                "quantity": {
                    "type": "integer",
                    "description": "Available inventory.",
                    "example": 250,
                },
                "condition_type": {
                    "type": "string",
                    "enum": ["New", "Refurbished", "UsedLikeNew", "UsedVeryGood",
                             "UsedGood", "UsedAcceptable"],
                    "description": "The condition of the item.",
                    "example": "New",
                },
            },
            "required": ["item_name", "brand_name", "sku", "standard_price",
                         "quantity", "condition_type"],
        },
        "propertyGroups": {
            "Product Identity": {"title": "Product Identity", "propertyNames": ["item_name", "brand_name", "item_type", "sku"]},
            "Discovery": {"title": "Discovery", "propertyNames": ["color", "size", "material", "recommended_browse_nodes"]},
            "Compliance & Logistics": {"title": "Compliance & Logistics", "propertyNames": ["item_weight", "country_of_origin"]},
            "Offer": {"title": "Offer", "propertyNames": ["standard_price", "quantity", "condition_type"]},
            "Content": {"title": "Content", "propertyNames": ["bullet_point1", "bullet_point2", "product_description"]},
        },
    }


# ---------------------------------------------------------------------------
# schema flattening → pipeline stages
# ---------------------------------------------------------------------------
def _resolve(node: dict, schema: dict, _depth: int = 0) -> dict:
    """Follow a JSON-schema `$ref` into `schema.definitions` (bounded depth)."""
    if not isinstance(node, dict) or _depth > 6:
        return node or {}
    ref = node.get("$ref")
    if ref:
        name = ref.split("/")[-1]
        target = ((schema.get("definitions") or {}).get(name) or {})
        return _resolve(target, schema, _depth + 1)
    return node


def _flatten_schema(definition: dict) -> list[dict]:
    schema = definition.get("schema") or {}
    properties = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    # SP-API returns `propertyGroups` at the definition's top level (sibling to
    # `schema`), with a fallback to schema-level in bundled/dev definitions.
    groups = definition.get("propertyGroups") or schema.get("propertyGroups") or {}
    # build property → group title lookup
    prop_group = {}
    for g in groups.values():
        title = g.get("title") or ""
        for p in g.get("propertyNames") or []:
            prop_group[p] = title

    out = []
    for name, raw in properties.items():
        node = _resolve(raw, schema)
        t = node.get("type") or ""
        if isinstance(t, list):
            t = "|".join(str(x) for x in t)
        enum = node.get("enum") or []
        out.append({
            "name": name,
            "type": str(t),
            "required": name in required,
            "enum": [str(v) for v in enum],
            "min_length": node.get("minLength"),
            "max_length": node.get("maxLength"),
            "pattern": node.get("pattern"),
            "format": node.get("format") or "",
            "description": node.get("description") or "",
            "example": node.get("example"),
            "group": prop_group.get(name) or "Uncategorized",
        })
    # required-first, then by group then name
    out.sort(key=lambda a: (not a["required"], a["group"], a["name"]))
    return out


def _pipeline_stages(definition: dict) -> dict:
    schema = definition.get("schema") or {}
    attrs = _flatten_schema(definition)
    required_attrs = [a for a in attrs if a["required"]]
    columns = [{
        "key": a["name"], "label": a["name"].replace("_", " ").title(),
        "required": a["required"], "values": a["enum"], "example": a["example"],
    } for a in attrs]
    guidelines = []
    for a in attrs:
        if a["required"]:
            guidelines.append({"attribute": a["name"], "rule_type": "required",
                               "rule_value": "", "severity": "blocker",
                               "note": f"{a['group']} — {a['description'][:120]}"})
        if a["enum"]:
            guidelines.append({"attribute": a["name"], "rule_type": "allowed_values",
                               "rule_value": "|".join(a["enum"]), "severity": "warning",
                               "note": f"{a['group']} — one of {len(a['enum'])} allowed values"})
        if a["pattern"]:
            guidelines.append({"attribute": a["name"], "rule_type": "pattern",
                               "rule_value": a["pattern"], "severity": "warning", "note": a["group"]})
        if a["min_length"] is not None:
            guidelines.append({"attribute": a["name"], "rule_type": "min_length",
                               "rule_value": str(a["min_length"]), "severity": "warning", "note": a["group"]})
        if a["max_length"] is not None:
            guidelines.append({"attribute": a["name"], "rule_type": "max_length",
                               "rule_value": str(a["max_length"]), "severity": "warning", "note": a["group"]})
    return {
        "required_attributes": [a["name"] for a in required_attrs],
        "attributes": attrs,
        "flatfile_columns": columns,
        "guidelines": guidelines,
    }


def _row(r) -> dict:
    d = dict(r)
    d["definition"] = json.loads(d.get("definition") or "{}")
    d["stages"] = _pipeline_stages(d["definition"])
    return d


# ---------------------------------------------------------------------------
# storage helpers
# ---------------------------------------------------------------------------
def _get_pipeline(pid: int):
    row = storage._conn().execute(
        "SELECT * FROM product_pipelines WHERE id=?", (pid,)).fetchone()
    if not row:
        raise HTTPException(404, "Pipeline not found")
    return row


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------
@router.get("/status")
def status():
    return get_config()


@router.post("/config")
def config(body: dict):
    """Persist LWA credentials to data/spapi.json. Accepts a direct access_token
    (dev convenience) OR refresh_token + client_id + client_secret (LWA flow)."""
    return apply_config(body)


def apply_config(body: dict) -> dict:
    """Shared credential writer — used by the /config route AND the Integrations
    page (automation.py `spapi` connector) so both surfaces share one source."""
    cfg = _load_config()
    for field in ("refresh_token", "client_id", "client_secret", "access_token"):
        if body.get(field) is not None:
            cfg[field] = str(body[field]).strip()
    if body.get("region") is not None:
        region = str(body["region"]).lower()
        if region not in REGIONS:
            raise HTTPException(400, f"region must be one of {', '.join(REGIONS)}")
        cfg["region"] = region
    _save_config({k: cfg[k] for k in ("refresh_token", "client_id", "client_secret", "access_token", "region")})
    return get_config()


def test_connection() -> dict:
    """Live credential check for the Integrations `Test` button. No creds → honest
    'unconfigured' (fetches fall back to bundled). With creds → LWA token exchange
    + a light searchDefinitionsProductTypes ping."""
    cfg = _load_config()
    has_key = bool(cfg["access_token"]) or bool(cfg["refresh_token"] and cfg["client_id"] and cfg["client_secret"])
    if not has_key:
        return {"ok": False, "mode": "unconfigured",
                "detail": "No SP-API credentials — fetches fall back to bundled sample definitions."}
    try:
        _access_token(cfg)
        results = _fetch_search("", ["ATVPDKIKX0DER"])
        return {"ok": True, "mode": "live",
                "detail": f"LWA token exchange OK — {len(results)} product type(s) reachable."}
    except HTTPException as exc:
        return {"ok": False, "mode": "live", "detail": exc.detail}
    except Exception as exc:
        return {"ok": False, "mode": "live", "detail": str(exc)}


@router.get("/product-types")
def product_types(keywords: str = "", marketplace_id: str = "ATVPDKIKX0DER"):
    """Search product types. Live searchDefinitionsProductTypes when creds exist,
    else bundled sample types (labelled)."""
    cfg = _load_config()
    bundled = ["LUGGAGE", "SHAMPOO", "BACKPACK", "HOME_BED_AND_BATH", "GENERIC"]
    has_key = bool(cfg["access_token"]) or bool(cfg["refresh_token"] and cfg["client_id"] and cfg["client_secret"])
    if has_key and keywords.strip():
        results = _fetch_search(keywords.strip(), [marketplace_id])
        return {"source": "live", "product_types": [
            {"name": r.get("name"), "marketplace_ids": r.get("marketplaceIds") or []}
            for r in results
        ]}
    kw = keywords.strip().upper()
    names = [t for t in bundled if kw in t] if kw else bundled
    return {"source": "bundled", "product_types": [
        {"name": n, "marketplace_ids": [marketplace_id]} for n in names
    ]}


@router.post("/fetch")
def fetch(body: dict):
    """Fetch getDefinitionsProductType for a product type + marketplace and build
    a pipeline from it. Falls back to a bundled definition when no credentials."""
    product_type = str(body.get("product_type") or "").strip().upper()
    if not product_type:
        raise HTTPException(400, "product_type is required (e.g. LUGGAGE)")
    marketplace_ids = [str(m).strip().upper() for m in (body.get("marketplace_ids") or body.get("marketplace_id") or ["ATVPDKIKX0DER"]) if str(m).strip()]
    marketplace_ids = marketplace_ids or ["ATVPDKIKX0DER"]
    for m in marketplace_ids:
        if m not in MARKETPLACES:
            raise HTTPException(400, f"unknown marketplaceId {m} — use one of {', '.join(sorted(MARKETPLACES))}")
    locale = str(body.get("locale") or "en_US")
    requirements = str(body.get("requirements") or "LISTING").upper()
    if requirements not in REQUIREMENTS:
        raise HTTPException(400, f"requirements must be one of {', '.join(REQUIREMENTS)}")
    name = str(body.get("name") or "").strip() or f"{product_type} · {MARKETPLACES.get(marketplace_ids[0], marketplace_ids[0])}"

    cfg = _load_config()
    has_key = bool(cfg["access_token"]) or bool(cfg["refresh_token"] and cfg["client_id"] and cfg["client_secret"])
    if has_key:
        definition = _fetch_definition(product_type, marketplace_ids, locale, requirements)
        source = "live"
    else:
        definition = _bundled_definition(product_type, marketplace_ids, locale, requirements)
        source = "bundled"

    now = storage.now_iso()
    conn = storage._conn()
    cur = conn.execute(
        "INSERT INTO product_pipelines "
        "(name, product_type, marketplace_id, locale, requirements, definition, source, status, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (name, product_type, marketplace_ids[0], locale, requirements,
         json.dumps(definition), source, "draft", now, now),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM product_pipelines WHERE id=?", (cur.lastrowid,)).fetchone()
    d = _row(row)
    d["_fetched_from"] = "live" if source == "live" else "bundled-sample (no SP-API credentials)"
    return d


@router.get("/pipelines")
def list_pipelines():
    rows = storage._conn().execute(
        "SELECT * FROM product_pipelines ORDER BY updated_at DESC").fetchall()
    return {"pipelines": [{
        "id": r["id"], "name": r["name"], "product_type": r["product_type"],
        "marketplace_id": r["marketplace_id"], "locale": r["locale"],
        "requirements": r["requirements"], "source": r["source"],
        "status": r["status"], "created_at": r["created_at"], "updated_at": r["updated_at"],
    } for r in rows]}


@router.get("/pipelines/{pid}")
def get_pipeline(pid: int):
    return _row(_get_pipeline(pid))


@router.delete("/pipelines/{pid}", status_code=204)
def delete_pipeline(pid: int):
    _get_pipeline(pid)
    storage._conn().execute("DELETE FROM product_pipelines WHERE id=?", (pid,))
    storage._conn().commit()
    return None


@router.post("/pipelines/{pid}/generate")
def generate(pid: int, body: dict):
    """Materialize the pipeline: write derived columns into `flatfile_templates`
    and derived rules into `attribute_guidelines`. Returns what was written."""
    d = _row(_get_pipeline(pid))
    stages = d["stages"]
    target = str(body.get("target") or "both")  # flatfile | guidelines | both
    flatfile_id = guideline_count = 0

    if target in ("flatfile", "both"):
        now = storage.now_iso()
        conn = storage._conn()
        cur = conn.execute(
            "INSERT INTO flatfile_templates (name, product_type, columns, header_note, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?)",
            (f"{d['product_type']} (SP-API)", d["product_type"],
             json.dumps(stages["flatfile_columns"]),
             f"Generated from SP-API getDefinitionsProductType ({d['source']}) for marketplace {d['marketplace_id']}.",
             now, now),
        )
        flatfile_id = cur.lastrowid
        conn.commit()

    if target in ("guidelines", "both"):
        conn = storage._conn()
        for g in stages["guidelines"]:
            conn.execute(
                "INSERT INTO attribute_guidelines "
                "(attribute, grouping, group_value, rule_type, rule_value, severity, enabled, note, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (g["attribute"], "product_type", d["product_type"], g["rule_type"],
                 g["rule_value"], g["severity"], 1, g["note"], storage.now_iso()),
            )
            guideline_count += 1
        conn.commit()

    return {
        "pipeline_id": pid,
        "flatfile_template_id": flatfile_id or None,
        "guidelines_written": guideline_count,
        "flatfile_columns": stages["flatfile_columns"] if target in ("flatfile", "both") else [],
        "guidelines": stages["guidelines"] if target in ("guidelines", "both") else [],
    }


@router.post("/pipelines/{pid}/readiness")
def readiness(pid: int):
    """Score the catalog against the pipeline's required attributes."""
    d = _row(_get_pipeline(pid))
    required = d["stages"]["required_attributes"]
    products = storage.list_products(limit=1000)
    results = []
    for p in products:
        attrs = p.get("attributes") or {}
        missing = [a for a in required if not str(attrs.get(a) or "").strip()]
        results.append({
            "id": p.get("id"), "sku": p.get("sku"), "name": p.get("name"),
            "missing": missing,
            "complete": not missing,
            "pct": round(100 * (len(required) - len(missing)) / len(required)) if required else 100,
        })
    ready = [r for r in results if r["complete"]]
    return {
        "pipeline_id": pid,
        "product_type": d["product_type"],
        "required_attributes": required,
        "catalog_count": len(results),
        "ready_count": len(ready),
        "products": results,
    }


# ---------------------------------------------------------------------------
# Product Registry — upload parsing helpers
#
# Minimal CSV/TSV/JSON/NDJSON row parser for registry uploads. Mirrors the
# header/key handling already used in flatfiles.py's `upload_template`
# (auto-detect delimiter, normalize header keys) and reuses parsers.py's
# `normalise_row` idea of trying a short list of candidate column names
# for the identifying value (there: "sku","asin","asins","product_id",... ;
# here: the same list, since a registry row's identifying value IS an
# ASIN/SKU in the vast majority of cases).
# ---------------------------------------------------------------------------
def _norm_header_key(s: str) -> str:
    return str(s or "").strip().lower().replace(" ", "_")


def _parse_tabular(raw: bytes, filename: str) -> list[dict]:
    ext = Path(filename or "").suffix.lower()
    text = raw.decode("utf-8-sig", errors="replace")

    if ext == ".json":
        try:
            obj = json.loads(text)
        except Exception:
            return []
        if isinstance(obj, list):
            return [r for r in obj if isinstance(r, dict)]
        if isinstance(obj, dict):
            return [obj]
        return []

    if ext in (".ndjson", ".jsonl"):
        rows = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if isinstance(obj, dict):
                rows.append(obj)
        return rows

    lines = [l for l in text.splitlines() if l.strip()]
    if not lines:
        return []
    if ext in (".tsv", ".tab") or "\t" in lines[0]:
        delim = "\t"
    elif "," in lines[0]:
        delim = ","
    else:
        delim = None
    if delim is None:
        # A single column with no delimiter is ambiguous: it could be a bare
        # ASIN list with NO header (every line is a value), or a one-column
        # file WITH a header (e.g. just "asin\n"). Disambiguate: if the
        # first line reads like one of the recognized column names AND is
        # not itself ASIN-shaped, treat it as a header and drop it.
        first = lines[0].strip().lower()
        if first in _ASIN_COLUMN_CANDIDATES and not asin_sources.is_valid_asin(lines[0]):
            return [{"asin": l.strip()} for l in lines[1:]]
        return [{"value": l.strip()} for l in lines]

    rows_raw = [r for r in csv.reader(lines, delimiter=delim) if any(str(c).strip() for c in r)]
    if not rows_raw:
        return []
    header = [_norm_header_key(c) for c in rows_raw[0]]
    out = []
    for r in rows_raw[1:]:
        out.append({header[i]: (r[i].strip() if i < len(r) else "") for i in range(len(header))})
    return out


def _row_identifier(row: dict) -> str:
    """Best-effort ASIN/SKU value for one parsed row — tries the same
    short candidate-column list parsers.py's `normalise_row` already uses
    for a row's identifying value, plus falls back to a single-column
    file's only value (e.g. a bare one-ASIN-per-line upload)."""
    for key in _ASIN_COLUMN_CANDIDATES:
        v = row.get(key)
        if v not in (None, ""):
            return str(v).strip()
    if len(row) == 1:
        return str(next(iter(row.values())) or "").strip()
    return ""


def _validate_registry_rows(file_type: str, rows: list[dict], asin_rows: list[dict]) -> dict:
    """Validation pass run once at upload time. Recorded verbatim in the
    stored `validation` json and read back by the asin_sources
    AsinDataAccess implementation below to decide whether an upload
    qualifies for the 'recommended' ASIN source (must be `status == 'done'`
    AND `validation.ok`)."""
    errors: list[str] = []
    invalid_asins = 0
    if not rows:
        errors.append("File is empty or unparseable.")
    elif file_type in _ASIN_BEARING_TYPES:
        if not asin_rows:
            errors.append(
                f"No identifying column found — expected one of {', '.join(_ASIN_COLUMN_CANDIDATES)}."
            )
        else:
            invalid_asins = sum(1 for r in asin_rows if not asin_sources.is_valid_asin(r["asin"]))
            if invalid_asins == len(asin_rows):
                errors.append("No row contained a value matching the ASIN shape.")
    return {
        "ok": not errors,
        "errors": errors,
        "row_count": len(rows),
        "asin_row_count": len(asin_rows),
        "invalid_asin_count": invalid_asins,
    }


# ---------------------------------------------------------------------------
# Product Registry — ASIN data access (wires asin_sources.AsinDataAccess to
# local storage). No network/Keepa/Supabase call happens here — "connected"
# reads Keepa's already-cached product set (keepa.list_keepa_products,
# a SQLite read), "uploaded"/"recommended" read this file's own
# product_registry_items rows.
# ---------------------------------------------------------------------------
class RegistryAsinAccess:
    """Concrete asin_sources.AsinDataAccess for the Product Registry.
    A5 can substitute a fake implementing the same four methods in tests —
    see asin_sources.AsinDataAccess for the exact contract."""

    def get_connected_asins(self) -> list[dict]:
        import keepa

        out = []
        for row in keepa.list_keepa_products(1000):
            data = row.get("data") or {}
            asin = data.get("asin") or row.get("asin")
            if not asin:
                continue
            out.append({"asin": asin, "list_name": "connected", "ingested_at": row.get("fetched_at")})
        return out

    def _asin_list_rows(self) -> list:
        return storage._conn().execute(
            "SELECT * FROM product_registry_items WHERE file_type='asin_list' ORDER BY created_at DESC"
        ).fetchall()

    def get_uploaded_asins(self) -> list[dict]:
        items = self._asin_list_rows()
        if not items:
            return []
        newest = dict(items[0])
        parsed = json.loads(newest.get("parsed") or "{}")
        out = []
        for r in parsed.get("asin_rows") or []:
            out.append({
                "asin": r.get("asin"),
                "upload_id": newest.get("upload_id"),
                "list_name": newest.get("name"),
                "row_number": r.get("row_number"),
                "ingested_at": r.get("ingested_at"),
            })
        return out

    def get_uploads(self) -> list[dict]:
        rows = storage._conn().execute(
            "SELECT * FROM product_registry_items WHERE file_type != 'asin_list' ORDER BY created_at DESC"
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            validation = json.loads(d.get("validation") or "{}")
            out.append({
                "upload_id": d.get("upload_id"),
                "filename": d.get("name"),
                "status": d.get("upload_status"),
                "validated": bool(validation.get("ok")),
                "created_at": d.get("created_at"),
            })
        return out

    def get_upload_asin_rows(self, upload_id: str) -> list[dict]:
        row = storage._conn().execute(
            "SELECT * FROM product_registry_items WHERE upload_id=?", (upload_id,)
        ).fetchone()
        if not row:
            return []
        parsed = json.loads(dict(row).get("parsed") or "{}")
        out = []
        for r in parsed.get("asin_rows") or []:
            out.append({
                "asin": r.get("asin"),
                "upload_id": upload_id,
                "row_number": r.get("row_number"),
                "ingested_at": r.get("ingested_at"),
            })
        return out


# ---------------------------------------------------------------------------
# Product Registry — storage helpers
# ---------------------------------------------------------------------------
def _record_transition(item_id: int, from_stage: str | None, to_stage: str, note: str = "") -> None:
    conn = storage._conn()
    conn.execute(
        "INSERT INTO product_registry_transitions (item_id, from_stage, to_stage, note, created_at) "
        "VALUES (?,?,?,?,?)",
        (item_id, from_stage, to_stage, note, storage.now_iso()),
    )
    conn.commit()


def _get_registry_item_row(item_id: int):
    row = storage._conn().execute(
        "SELECT * FROM product_registry_items WHERE id=?", (item_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404, "Registry item not found")
    return row


def _registry_row(row) -> dict:
    d = dict(row)
    d["raw"] = json.loads(d.get("raw") or "{}")
    d["parsed"] = json.loads(d.get("parsed") or "{}")
    d["validation"] = json.loads(d.get("validation") or "{}")
    d["provenance"] = json.loads(d.get("provenance") or "{}")

    linked_product = None
    if d.get("product_id"):
        prow = storage._conn().execute(
            "SELECT * FROM products WHERE id=?", (d["product_id"],)
        ).fetchone()
        if prow:
            p = dict(prow)
            p["attributes"] = json.loads(p.get("attributes") or "{}")
            p["tags"] = json.loads(p.get("tags") or "[]")
            linked_product = p
    d["linked_product"] = linked_product

    history = storage._conn().execute(
        "SELECT * FROM product_registry_transitions WHERE item_id=? ORDER BY created_at, id",
        (d["id"],),
    ).fetchall()
    d["transition_history"] = [dict(t) for t in history]
    return d


# ---------------------------------------------------------------------------
# Product Registry — routes
# ---------------------------------------------------------------------------
@router.get("/registry/stages")
def registry_stages():
    """The seven lifecycle stages + their legal next-stage transitions."""
    return {
        "stages": [
            {"key": key, "label": label, "description": desc, "sort_order": order,
             "terminal": terminal, "transitions": transitions}
            for key, label, desc, order, terminal, transitions in REGISTRY_STAGES
        ]
    }


@router.get("/registry/types")
def registry_types():
    """The registry types a user may choose at upload time."""
    return {"types": REGISTRY_TYPES}


@router.post("/registry/upload", status_code=201)
async def registry_upload(
    file: UploadFile = File(...),
    file_type: str = Form(...),
    name: str = Form(""),
):
    """Upload a file, choosing its registry type. Parses it synchronously
    (mirrors flatfiles.py's upload_template / insights.py's upload — both
    small-file, single-request patterns, appropriate here since ASIN lists
    and registry uploads are small relative to bulk catalog imports), runs
    one validation pass, and creates ONE canonical registry record at the
    'suggested' stage. `file_type` (registry type) and `stage` (lifecycle)
    are independent from the start."""
    file_type = str(file_type or "").strip().lower()
    if file_type not in REGISTRY_TYPES:
        raise HTTPException(400, f"file_type must be one of {', '.join(REGISTRY_TYPES)}")

    raw = await file.read()
    if len(raw) > 20 * 1024 * 1024:
        raise HTTPException(413, "Registry upload too large (max 20MB)")

    filename = file.filename or "upload"
    rows = _parse_tabular(raw, filename)
    now = storage.now_iso()

    asin_rows = []
    for i, row in enumerate(rows, start=1):
        token = _row_identifier(row)
        if token:
            asin_rows.append({"asin": token.upper(), "row_number": i, "ingested_at": now})

    validation = _validate_registry_rows(file_type, rows, asin_rows)
    upload_status = "done" if rows else "error"
    upload_id = uuid.uuid4().hex[:12]

    raw_preview = raw.decode("utf-8-sig", errors="replace")
    truncated = len(raw_preview) > 200_000
    raw_payload = {
        "filename": filename,
        "size_bytes": len(raw),
        "text": raw_preview[:200_000],
        "truncated": truncated,
    }
    parsed_payload = {"rows": rows, "asin_rows": asin_rows, "row_count": len(rows)}

    conn = storage._conn()
    cur = conn.execute(
        "INSERT INTO product_registry_items "
        "(item_key, name, file_type, stage, asin_source, upload_id, upload_status, product_id, "
        " raw, parsed, validation, provenance, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            upload_id,
            (name or Path(filename).stem).strip() or upload_id,
            file_type,
            REGISTRY_DEFAULT_STAGE,
            "manual",
            upload_id,
            upload_status,
            None,
            json.dumps(raw_payload),
            json.dumps(parsed_payload),
            json.dumps(validation),
            json.dumps({}),
            now,
            now,
        ),
    )
    conn.commit()
    item_id = cur.lastrowid
    _record_transition(item_id, None, REGISTRY_DEFAULT_STAGE, "created via upload")
    return _registry_row(_get_registry_item_row(item_id))


@router.get("/registry/items")
def registry_list(stage: str = "", file_type: str = ""):
    """List registry records, optionally filtered by stage and/or file
    type. `counts_by_stage` always reflects the WHOLE registry (unfiltered)
    so the UI can render stage-filter tabs with live counts."""
    conn = storage._conn()
    query = "SELECT * FROM product_registry_items WHERE 1=1"
    params: list = []
    if stage:
        if stage not in REGISTRY_STAGE_KEYS:
            raise HTTPException(400, f"stage must be one of {', '.join(REGISTRY_STAGE_KEYS)}")
        query += " AND stage=?"
        params.append(stage)
    if file_type:
        if file_type not in REGISTRY_TYPES:
            raise HTTPException(400, f"file_type must be one of {', '.join(REGISTRY_TYPES)}")
        query += " AND file_type=?"
        params.append(file_type)
    query += " ORDER BY updated_at DESC"
    rows = conn.execute(query, params).fetchall()
    items = [_registry_row(r) for r in rows]

    counts_by_stage = {key: 0 for key in REGISTRY_STAGE_KEYS}
    for r in conn.execute("SELECT stage FROM product_registry_items").fetchall():
        counts_by_stage[r["stage"]] = counts_by_stage.get(r["stage"], 0) + 1

    return {"count": len(items), "items": items, "counts_by_stage": counts_by_stage}


@router.get("/registry/items/{item_id}")
def registry_detail(item_id: int):
    """Full authorized view of one registry record: raw / parsed /
    validation / source / linked-product data, plus its transition
    history."""
    return _registry_row(_get_registry_item_row(item_id))


@router.post("/registry/items/{item_id}/transition")
def registry_transition(item_id: int, body: dict):
    """Move a registry record to a new stage. Enforces the legal-transition
    graph in REGISTRY_TRANSITIONS (mirrors the seven stage_definitions
    seeded by the Postgres migration) — illegal transitions are rejected
    with a clear error naming the stages that ARE legal from here."""
    row = _get_registry_item_row(item_id)
    current = row["stage"]
    to_stage = str(body.get("to_stage") or "").strip().lower()
    note = str(body.get("note") or "").strip()

    if to_stage not in REGISTRY_TRANSITIONS:
        raise HTTPException(400, f"Unknown stage {to_stage!r} — must be one of {', '.join(REGISTRY_STAGE_KEYS)}")
    if to_stage == current:
        raise HTTPException(409, f"Item {item_id} is already in stage {current!r}.")
    allowed = REGISTRY_TRANSITIONS.get(current, [])
    if to_stage not in allowed:
        raise HTTPException(
            409,
            f"Illegal transition {current!r} -> {to_stage!r}. "
            f"Allowed next stage(s) from {current!r}: {', '.join(allowed) or '(none — terminal stage)'}.",
        )

    now = storage.now_iso()
    conn = storage._conn()
    conn.execute("UPDATE product_registry_items SET stage=?, updated_at=? WHERE id=?", (to_stage, now, item_id))
    conn.commit()
    _record_transition(item_id, current, to_stage, note)
    return _registry_row(_get_registry_item_row(item_id))


@router.post("/registry/items/{item_id}/link-product")
def registry_link_product(item_id: int, body: dict):
    """Link an existing catalog product (storage.products) to a registry
    record so its detail view can surface linked-product data."""
    _get_registry_item_row(item_id)
    product_id = body.get("product_id")
    if not product_id:
        raise HTTPException(400, "product_id is required")
    prow = storage._conn().execute("SELECT id FROM products WHERE id=?", (product_id,)).fetchone()
    if not prow:
        raise HTTPException(404, f"Product {product_id} not found")
    now = storage.now_iso()
    conn = storage._conn()
    conn.execute("UPDATE product_registry_items SET product_id=?, updated_at=? WHERE id=?", (product_id, now, item_id))
    conn.commit()
    return _registry_row(_get_registry_item_row(item_id))


@router.post("/registry/asins/resolve")
def registry_resolve_asins(body: dict):
    """Resolve one of the three explicit ASIN sources (connected / uploaded
    / recommended) — see asin_sources.py. Never mixes sources and never
    silently falls back; an unavailable/empty/unqualified source raises a
    clear error instead."""
    source = str(body.get("source") or "").strip().lower()
    try:
        result = asin_sources.resolve(source, RegistryAsinAccess())
    except asin_sources.AsinSourceError as exc:
        status_code = 400 if source not in asin_sources.SOURCES else 409
        raise HTTPException(status_code, str(exc))
    return result.to_dict()
