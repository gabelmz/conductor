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

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

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
