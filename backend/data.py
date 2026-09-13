"""Full Data Management: tables, pivot aggregation, saved views, Asana push,
and ingest-source status. Serves the `data` view (Data Management).

Plain-language tour (this module is read by non-engineers too):

* A **source** is one named pile of data you can look at — "Catalog products",
  "Asana tasks", "Supabase — Products (live)", and so on.
* Every source has a **resolver**: the small function that actually goes and
  fetches the rows for that pile (out of the local SQLite database, or over
  the network from Supabase).
* The **routing table** (:func:`routing_table`) is the single map that says
  which source uses which resolver, what it is called, and what type of data
  it really is. It is data, not an if/elif chain, so a Settings screen can
  read it, show it, and change the labels — and so an unknown source name
  fails loudly instead of quietly handing back the wrong pile of data.

Router prefix: /api/data
"""
from __future__ import annotations

import json
from typing import Any, Callable

from fastapi import APIRouter, HTTPException

import storage
import automation

router = APIRouter(prefix="/api/data", tags=["data"])


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _brand(attrs: dict) -> str:
    """Pull the brand name out of a product's free-form attribute bag.

    Different catalogs spell the same field differently ("brand", "Brand",
    "BRAND", "manufacturer"), so this tries each spelling in turn and returns
    the first non-empty one. Returns "" when the product has no brand at all.
    """
    for k in ("brand", "Brand", "BRAND", "manufacturer"):
        v = attrs.get(k)
        if v:
            return str(v).strip()
    return ""


def _latest_check(product_id: int) -> dict | None:
    """Fetch the most recent compliance check recorded for one product.

    Reads from the local SQLite database. Returns the check as a dict (score,
    severity, status), or None if this product has never been checked — or if
    the lookup fails, because a missing score must never break the table view.
    """
    try:
        return storage.latest_check_by_product(product_id)
    except Exception:
        return None


def _product_rows(limit: int = 500, q: str = "", tag: str = "") -> list[dict]:
    """Pull rows for the **Catalog products** source.

    Where from: the local SQLite `products` table (plus each product's latest
    compliance check, for the score/severity/status columns).
    What you get back: one flat dict per product — sku, name, category,
    market, brand, source, tags, created_at, score, severity, status.
    `q` keeps only products whose name/sku/category contains that text,
    `tag` keeps only products carrying that tag, and `limit` caps how many
    rows come back.
    """
    rows = []
    for p in storage.list_products(limit=1000, tag=tag or None):
        chk = _latest_check(p["id"]) or {}
        attrs = p.get("attributes") or {}
        name = p.get("name") or ""
        sku = p.get("sku") or ""
        category = p.get("category") or ""
        if q and q.lower() not in (name + " " + sku + " " + category).lower():
            continue
        rows.append({
            "id": p["id"], "sku": sku, "name": name, "category": category,
            "market": p.get("market") or "", "brand": _brand(attrs),
            "source": p.get("source") or "", "tags": p.get("tags") or [],
            "created_at": p.get("created_at") or "",
            "score": chk.get("score"), "severity": chk.get("severity") or "",
            "status": chk.get("status") or "",
        })
        if len(rows) >= limit:
            break
    return rows


def _asana_rows(limit: int = 500, q: str = "") -> list[dict]:
    """Pull rows for the **Asana tasks** source.

    Where from: the local SQLite `asana_tasks` mirror — the copy Conductor
    keeps of your Asana workspace (filled in by the Asana sync), never a live
    call to Asana from this function.
    What you get back: one flat dict per task — id (Asana's gid), name,
    project, assignee, completed, due_on, created_at. `q` keeps only tasks
    whose name contains that text; `limit` caps the row count.
    """
    rows = []
    for t in storage.list_asana_tasks(limit=min(limit, 1000)):
        name = t.get("name") or ""
        if q and q.lower() not in name.lower():
            continue
        rows.append({
            "id": t.get("gid") or "", "name": name,
            "project": t.get("project_name") or "", "assignee": t.get("assignee_name") or "",
            "completed": bool(t.get("completed")), "due_on": t.get("due_on") or "",
            "created_at": t.get("created_at") or "",
        })
        if len(rows) >= limit:
            break
    return rows


def _file_rows(limit: int = 500, q: str = "") -> list[dict]:
    """Pull rows for the **Uploaded files** source.

    Where from: the local SQLite `files` table — the record of every
    spreadsheet/CSV someone dropped into Catalog Ingest, not the file
    contents themselves.
    What you get back: one dict per upload — id, name (the filename),
    status, records (how many rows were parsed out of it), size in bytes,
    created_at. `q` matches on filename; `limit` caps the row count.
    """
    rows = []
    for f in storage.list_files(limit=100):
        fn = f.get("filename") or ""
        if q and q.lower() not in fn.lower():
            continue
        rows.append({
            "id": f["id"], "name": fn, "status": f.get("status") or "",
            "records": f.get("record_count") or 0, "size": f.get("total_size") or 0,
            "created_at": f.get("created_at") or "",
        })
        if len(rows) >= limit:
            break
    return rows


SOURCES = {
    "products": {
        "label": "Catalog products",
        "columns": ["sku", "name", "category", "market", "brand", "source", "tags", "score", "severity", "status", "created_at"],
        "groupable": ["category", "market", "brand", "source", "severity", "status"],
    },
    "asana": {
        "label": "Asana tasks",
        "columns": ["name", "project", "assignee", "completed", "due_on", "created_at"],
        "groupable": ["project", "assignee", "completed"],
    },
    "files": {
        "label": "Uploaded files",
        "columns": ["name", "status", "records", "size", "created_at"],
        "groupable": ["status"],
    },
}

# --------------------------------------------------------------------------
# Supabase-backed sources — a read-only allowlist of (schema, table) pairs
# from the shared Supabase project's `product` schema. Deliberately an
# explicit allowlist, never a client-supplied schema/table: several other
# exposed schemas on this project (`registry`, `lumi`) hold tables literally
# named `keys` and are unrelated to Conductor's own domain, so nothing here
# ever accepts a caller-chosen schema/table name.
# --------------------------------------------------------------------------
SUPABASE_SOURCES = {
    "supabase_products": {"schema": "product", "table": "products", "label": "Supabase — Products (live)"},
    "supabase_suggested": {"schema": "product", "table": "suggested", "label": "Supabase — Suggested Listings (live)"},
    # asana_views.* stores each object as a JSONB envelope (object_gid, payload,
    # source_modified_at, fetched_at, synced_at) rather than typed columns —
    # unwrap_payload flattens `payload` into the row so the generic table view
    # shows real task/project/user/team fields instead of one opaque blob
    # column. Currently blocked live on a missing schema-level GRANT (same
    # class of issue conductor.* had) — wired up now so it works the moment
    # that's applied, not built later as a second pass.
    "supabase_asana_tasks": {"schema": "asana_views", "table": "tasks", "label": "Supabase — Asana Tasks (live)", "unwrap_payload": True},
    "supabase_asana_projects": {"schema": "asana_views", "table": "projects", "label": "Supabase — Asana Projects (live)", "unwrap_payload": True},
    "supabase_asana_users": {"schema": "asana_views", "table": "users", "label": "Supabase — Asana Users (live)", "unwrap_payload": True},
    "supabase_asana_teams": {"schema": "asana_views", "table": "teams", "label": "Supabase — Asana Teams (live)", "unwrap_payload": True},
}


def _unwrap_payload_rows(rows: list[dict]) -> list[dict]:
    """Flatten a JSONB envelope row ({object_gid, payload: {...}, ...meta})
    into one flat dict per row: meta columns plus every key inside `payload`,
    so the generic table/pivot view can show real fields instead of a single
    opaque `payload` column."""
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        payload = row.get("payload")
        flat = {k: v for k, v in row.items() if k != "payload"}
        if isinstance(payload, dict):
            flat.update(payload)
        out.append(flat)
    return out


def _supabase_rows(schema: str, table: str, limit: int, q: str = "", *, unwrap_payload: bool = False) -> list[dict]:
    """Read-only fetch from an allowlisted Supabase table. Returns [] (never
    raises) if Supabase isn't configured or the request fails — this is a
    browsing convenience, not a critical path, and must never break the
    Data Management view just because the live project is unreachable."""
    import supabase_sync
    import requests

    cfg = supabase_sync._load_config()
    if not (cfg["url"] and cfg["service_key"]):
        return []
    base = cfg["url"].rstrip("/") + "/rest/v1"
    headers = {
        "apikey": cfg["service_key"],
        "Authorization": f"Bearer {cfg['service_key']}",
        "Accept-Profile": schema,
    }
    try:
        resp = requests.get(
            f"{base}/{table}", headers=headers,
            params={"select": "*", "limit": min(max(limit, 1), 1000)}, timeout=15,
        )
        resp.raise_for_status()
        rows = resp.json()
    except Exception:
        return []
    if not isinstance(rows, list):
        return []
    if unwrap_payload:
        rows = _unwrap_payload_rows(rows)
    if q:
        ql = q.lower()
        rows = [r for r in rows if ql in json.dumps(r, default=str).lower()]
    return rows


def _supabase_count(schema: str, table: str) -> int:
    """Ask Supabase how many rows one allowlisted table holds, without
    downloading any of them.

    Where from: the live Supabase REST API, using PostgREST's exact-count
    header (so it reads `limit=0` plus a count, not the data).
    What you get back: a plain integer. Returns 0 — never raises — when
    Supabase isn't configured or the call fails, because a row count is
    decoration on the sources list, not something worth breaking the page for.
    """
    import supabase_sync
    import requests

    cfg = supabase_sync._load_config()
    if not (cfg["url"] and cfg["service_key"]):
        return 0
    base = cfg["url"].rstrip("/") + "/rest/v1"
    headers = {
        "apikey": cfg["service_key"],
        "Authorization": f"Bearer {cfg['service_key']}",
        "Accept-Profile": schema,
        "Prefer": "count=exact",
    }
    try:
        resp = requests.get(f"{base}/{table}", headers=headers, params={"select": "*", "limit": 0}, timeout=15)
        total = resp.headers.get("content-range", "*/0").split("/")[-1]
        return int(total) if total.isdigit() else 0
    except Exception:
        return 0


# ==========================================================================
# ROUTING REGISTRY
# --------------------------------------------------------------------------
# One explicit, data-driven map of source -> {label, kind, resolver}. This
# replaced an if/elif chain whose final bare `return _product_rows(...)` meant
# ANY unrecognized source silently handed back catalog products — so a typo,
# a renamed source, or a stale bookmark produced plausible-looking but
# completely wrong data, labelled "catalog". Routing is now absolute: a source
# either has an entry here or the request is rejected with HTTP 400.
# ==========================================================================

# `kind` = what the data REALLY is. Labels and job/activity text are derived
# from this, so nothing is ever described as "catalog" just because it fell
# off the end of a lookup.
KIND_CATALOG_PRODUCTS = "catalog_products"
KIND_ASANA_TASKS = "asana_tasks"
KIND_UPLOADED_FILES = "uploaded_files"
KIND_SUPABASE_TABLE = "supabase_table"


def _resolve_catalog_products(entry: dict, limit: int, q: str, tag: str) -> list[dict]:
    """Resolver for locally stored catalog products. See :func:`_product_rows`."""
    return _product_rows(limit, q, tag)


def _resolve_asana_tasks(entry: dict, limit: int, q: str, tag: str) -> list[dict]:
    """Resolver for the local Asana task mirror. See :func:`_asana_rows`."""
    return _asana_rows(limit, q)


def _resolve_uploaded_files(entry: dict, limit: int, q: str, tag: str) -> list[dict]:
    """Resolver for the local uploaded-file records. See :func:`_file_rows`."""
    return _file_rows(limit, q)


def _resolve_supabase_table(entry: dict, limit: int, q: str, tag: str) -> list[dict]:
    """Resolver for a live, allowlisted Supabase table. See :func:`_supabase_rows`.

    The schema/table pair comes from this source's own registry entry — never
    from the caller — which is why `params` is not user-overridable (see
    :data:`OVERRIDABLE_FIELDS`).
    """
    params = entry.get("params") or {}
    return _supabase_rows(
        str(params.get("schema") or ""),
        str(params.get("table") or ""),
        limit,
        q,
        unwrap_payload=bool(params.get("unwrap_payload")),
    )


# resolver name -> the function that actually fetches rows. A routing entry
# (including a user override) may only name a resolver that exists here, so
# configuration can never point a source at arbitrary code.
RESOLVERS: dict[str, Callable[[dict, int, str, str], list[dict]]] = {
    KIND_CATALOG_PRODUCTS: _resolve_catalog_products,
    KIND_ASANA_TASKS: _resolve_asana_tasks,
    KIND_UPLOADED_FILES: _resolve_uploaded_files,
    KIND_SUPABASE_TABLE: _resolve_supabase_table,
}

# resolver name -> how to count rows for the /sources tile, again as data
# rather than an if/elif chain.
COUNTERS: dict[str, Callable[[dict], int]] = {
    KIND_CATALOG_PRODUCTS: lambda entry: storage.count_products(),
    KIND_ASANA_TASKS: lambda entry: storage.asana_counts().get("tasks", 0),
    KIND_UPLOADED_FILES: lambda entry: len(storage.list_files()),
    KIND_SUPABASE_TABLE: lambda entry: _supabase_count(
        str((entry.get("params") or {}).get("schema") or ""),
        str((entry.get("params") or {}).get("table") or ""),
    ),
}

# Which source id each built-in local source maps onto. Kept beside SOURCES so
# adding a source is one edit in two obvious places, not a hunt through code.
_LOCAL_KINDS = {
    "products": KIND_CATALOG_PRODUCTS,
    "asana": KIND_ASANA_TASKS,
    "files": KIND_UPLOADED_FILES,
}

# Spine `configurations` coordinates for user routing overrides.
ROUTING_CONFIG_SCOPE = "routing"
ROUTING_CONFIG_KEY = "sources"

# A Settings screen may rename a source, re-declare what kind of data it is,
# repoint it at another registered resolver, or switch it off. It may NOT
# supply `params`: the Supabase schema/table pair is a deliberate server-side
# allowlist (see the SUPABASE_SOURCES comment above), and letting a config
# payload choose them would hand a caller arbitrary read access to the
# project's other schemas.
OVERRIDABLE_FIELDS = ("label", "kind", "resolver", "enabled")


def _builtin_routing() -> dict[str, dict]:
    """The ships-with-the-app routing map, before any user overrides.

    Built straight from SOURCES and SUPABASE_SOURCES so those two tables stay
    the single place a source is declared.
    """
    table: dict[str, dict] = {}
    for sid, meta in SOURCES.items():
        kind = _LOCAL_KINDS[sid]
        table[sid] = {
            "id": sid,
            "label": meta["label"],
            "kind": kind,
            "resolver": kind,
            "params": {},
            "columns": list(meta["columns"]),
            "groupable": list(meta["groupable"]),
            "enabled": True,
            "builtin": True,
            "overridden": False,
        }
    for sid, meta in SUPABASE_SOURCES.items():
        table[sid] = {
            "id": sid,
            "label": meta["label"],
            "kind": KIND_SUPABASE_TABLE,
            "resolver": KIND_SUPABASE_TABLE,
            # Columns are not fixed ahead of time for a live external table —
            # /table derives them from whatever rows actually came back.
            "params": {
                "schema": meta["schema"],
                "table": meta["table"],
                "unwrap_payload": bool(meta.get("unwrap_payload")),
            },
            "columns": [],
            "groupable": [],
            "enabled": True,
            "builtin": True,
            "overridden": False,
        }
    return table


def read_routing_overrides() -> dict[str, dict]:
    """Read the user's saved routing tweaks out of the spine config table.

    Where from: `spine_configurations`, scope "routing", key "sources".
    What you get back: `{source_id: {field: value}}` — only the fields someone
    actually changed. Returns {} when nothing has ever been overridden (or
    when the spine tables don't exist yet), so routing always works.
    """
    from spine import user_config

    value = user_config.read_configuration_value(ROUTING_CONFIG_SCOPE, ROUTING_CONFIG_KEY, {})
    if not isinstance(value, dict):
        return {}
    return {str(k): dict(v) for k, v in value.items() if isinstance(v, dict)}


def _write_routing_overrides(overrides: dict[str, dict]) -> None:
    """Persist routing tweaks to the spine `configurations` table.

    Uses spine.user_config.put_configuration(scope="routing", key="sources").
    If the spine tables have not been created yet in this database, they are
    created on the fly and the write is retried once.
    """
    import sqlite3

    from spine import user_config

    body = {"value": overrides}
    try:
        user_config.put_configuration(ROUTING_CONFIG_SCOPE, ROUTING_CONFIG_KEY, body)
    except sqlite3.OperationalError:
        from spine.schema import init_tables

        init_tables()
        user_config.put_configuration(ROUTING_CONFIG_SCOPE, ROUTING_CONFIG_KEY, body)


def routing_table() -> dict[str, dict]:
    """The full, introspectable routing map: source id -> routing entry.

    Each entry is `{id, label, kind, resolver, params, columns, groupable,
    enabled, builtin, overridden}`:

    * **label** — what a person sees ("Supabase — Products (live)").
    * **kind** — what the data truly is, used to derive activity/job labels.
    * **resolver** — the name of the function that fetches the rows.

    User overrides saved in Settings are merged on top of the built-in map,
    so this is what the app actually routes by. Safe to call on every request.
    """
    table = _builtin_routing()
    for sid, override in read_routing_overrides().items():
        entry = table.get(sid)
        if not entry:
            continue  # an override for a source that no longer exists is ignored
        changed = False
        for field in OVERRIDABLE_FIELDS:
            if field not in override:
                continue
            value = override[field]
            if field == "resolver" and value not in RESOLVERS:
                continue  # never route at a resolver that doesn't exist
            if field == "enabled":
                value = bool(value)
            elif not str(value).strip():
                continue
            else:
                value = str(value).strip()
            if entry[field] != value:
                entry[field] = value
                changed = True
        entry["overridden"] = changed
    return table


def valid_sources() -> list[str]:
    """Every source id the app will accept right now (disabled ones excluded)."""
    return [sid for sid, entry in routing_table().items() if entry["enabled"]]


def resolve_source(source: str) -> dict:
    """Look one source name up in the routing table, or fail loudly.

    This is the whole point of the registry: an unknown or switched-off source
    raises HTTP 400 listing the valid sources, instead of silently falling
    through to catalog products the way the old if/elif chain did.
    """
    table = routing_table()
    entry = table.get(source)
    if entry is None:
        raise HTTPException(
            400,
            f"Unknown data source '{source}'. Valid sources: "
            + ", ".join(sorted(sid for sid, e in table.items() if e["enabled"])),
        )
    if not entry["enabled"]:
        raise HTTPException(400, f"Data source '{source}' is turned off in routing settings.")
    if entry["resolver"] not in RESOLVERS:
        raise HTTPException(
            500,
            f"Data source '{source}' is routed to unknown resolver '{entry['resolver']}'.",
        )
    return entry


def set_routing_override(source: str, changes: dict) -> dict:
    """Change how one source is routed, and remember it.

    `changes` may contain any of label / kind / resolver / enabled. Anything
    else is rejected, and `resolver` must name a resolver that really exists.
    The merged result is written to the spine configurations table so it
    survives restarts. Returns the source's new routing entry.
    """
    table = _builtin_routing()
    if source not in table:
        raise HTTPException(
            400,
            f"Unknown data source '{source}'. Valid sources: " + ", ".join(sorted(table)),
        )
    unknown = [k for k in changes if k not in OVERRIDABLE_FIELDS]
    if unknown:
        raise HTTPException(
            400,
            f"Cannot override {', '.join(sorted(unknown))}; "
            f"only {', '.join(OVERRIDABLE_FIELDS)} may be changed.",
        )
    clean: dict[str, Any] = {}
    for field in OVERRIDABLE_FIELDS:
        if field not in changes:
            continue
        if field == "enabled":
            clean[field] = bool(changes[field])
            continue
        value = str(changes[field] or "").strip()
        if not value:
            raise HTTPException(400, f"{field} cannot be blank")
        if field == "resolver" and value not in RESOLVERS:
            raise HTTPException(
                400,
                f"Unknown resolver '{value}'. Available resolvers: " + ", ".join(sorted(RESOLVERS)),
            )
        clean[field] = value
    if not clean:
        raise HTTPException(400, f"No routing changes supplied; expected one of {', '.join(OVERRIDABLE_FIELDS)}")

    overrides = read_routing_overrides()
    merged = {**overrides.get(source, {}), **clean}
    overrides[source] = merged
    _write_routing_overrides(overrides)
    return routing_table()[source]


def clear_routing_override(source: str) -> dict:
    """Forget any saved tweaks for one source and go back to the built-in routing."""
    if source not in _builtin_routing():
        raise HTTPException(400, f"Unknown data source '{source}'")
    overrides = read_routing_overrides()
    overrides.pop(source, None)
    _write_routing_overrides(overrides)
    return routing_table()[source]


# ==========================================================================
# ACTIVITY / JOB LABELS
# --------------------------------------------------------------------------
# Job rows carry a short machine `kind`. The Activity feed needs a human
# label, an icon, and the TRUE data type — derived from the real source and
# payload, never hardcoded to "catalog".
# ==========================================================================
JOB_KINDS: dict[str, dict] = {
    "parse_catalog": {"label": "Catalog import", "icon": "cloud-upload", "type": KIND_CATALOG_PRODUCTS},
    "asana_sync": {"label": "Asana sync", "icon": "sync", "type": KIND_ASANA_TASKS},
    "supabase_sync": {"label": "Supabase sync", "icon": "database", "type": KIND_SUPABASE_TABLE},
    "ai_process": {"label": "AI processing", "icon": "chat-sparkle", "type": "ai"},
    "model_install": {"label": "Local model download", "icon": "cloud-download", "type": "model"},
    "model_start": {"label": "Local model server", "icon": "server-process", "type": "model"},
    "report": {"label": "Report", "icon": "graph", "type": "report"},
}

# data kind -> the job kind its work shows up under in Activity.
KIND_JOB_KINDS = {
    KIND_CATALOG_PRODUCTS: "parse_catalog",
    KIND_UPLOADED_FILES: "parse_catalog",
    KIND_ASANA_TASKS: "asana_sync",
    KIND_SUPABASE_TABLE: "supabase_sync",
}


def activity_label(source: str = "", payload: dict | None = None) -> dict:
    """Work out what to CALL a piece of work, from what it actually is.

    Give it the source it ran against (e.g. "supabase_products") and/or the
    job payload, and it returns
    `{source, type, label, job_kind, icon}` where:

    * **type** is the true data type ("supabase_table", "report", "model", …)
    * **label** is the human sentence for the Activity feed
    * **job_kind** is the machine kind to store on the job row
    * **icon** is the codicon name the feed should draw

    Crucially it never falls back to "catalog": an unrecognized source comes
    back as its own tidied-up name with type "unknown", so a mislabeled feed
    entry is visibly odd instead of convincingly wrong.
    """
    payload = payload if isinstance(payload, dict) else {}
    source = str(source or payload.get("source") or "").strip()

    # A report's true type is its report kind (cdq, …), whatever source fed it.
    report_kind = str(payload.get("report_kind") or payload.get("report_type") or "").strip()
    if report_kind or str(payload.get("entity") or "").strip() == "report":
        return {
            "source": source,
            "type": "report",
            "label": f"{report_kind.upper()} report" if report_kind else "Report",
            "job_kind": "report",
            "icon": JOB_KINDS["report"]["icon"],
        }

    entry = routing_table().get(source)
    if entry is not None:
        job_kind = KIND_JOB_KINDS.get(entry["kind"], "job")
        return {
            "source": source,
            "type": entry["kind"],
            "label": entry["label"],
            "job_kind": job_kind,
            "icon": JOB_KINDS.get(job_kind, {}).get("icon", "gear"),
        }

    if source in JOB_KINDS:
        meta = JOB_KINDS[source]
        return {
            "source": source,
            "type": meta["type"],
            "label": meta["label"],
            "job_kind": source,
            "icon": meta["icon"],
        }

    return {
        "source": source,
        "type": "unknown",
        "label": source.replace("_", " ").strip().capitalize() or "Activity",
        "job_kind": source or "job",
        "icon": "gear",
    }


def _get_rows(source: str, limit: int, q: str = "", tag: str = "") -> list[dict]:
    """Fetch the rows for one source by looking it up in the routing table.

    There is deliberately no fallback branch here. Unknown source in ->
    HTTP 400 out (see :func:`resolve_source`).
    """
    entry = resolve_source(source)
    return RESOLVERS[entry["resolver"]](entry, limit, q, tag)


# --------------------------------------------------------------------------
# routes
# --------------------------------------------------------------------------
@router.get("/sources")
def sources():
    """List every data source the user can browse, with a row count each.

    Where from: the routing table — local SQLite counts for the built-in
    sources, a live count call for each allowlisted Supabase table.
    What you get back: one entry per source with id, label, columns,
    groupable columns and count (plus the tag list on catalog products).
    Sources switched off in routing settings are left out.
    """
    tags = storage.list_tags()
    out = []
    for sid, entry in routing_table().items():
        if not entry["enabled"]:
            continue
        try:
            count = COUNTERS[entry["resolver"]](entry)
        except Exception:
            count = 0
        item = {"id": sid, "label": entry["label"], "columns": entry["columns"],
                "groupable": entry["groupable"], "count": count}
        if entry["kind"] == KIND_CATALOG_PRODUCTS:
            item["tags"] = tags
        out.append(item)
    return out


@router.get("/routing")
def get_routing():
    """Show the whole routing map so a Settings screen can render it.

    What you get back: `sources` (the full list of routing entries — label,
    true kind, resolver, whether it has been customized), `resolvers` (the
    resolver names an entry may be pointed at), `kinds` (the data types),
    `overridable` (which fields Settings may change) and `overrides` (what
    has actually been changed so far).
    """
    table = routing_table()
    return {
        "sources": list(table.values()),
        "resolvers": sorted(RESOLVERS),
        "kinds": sorted({entry["kind"] for entry in table.values()}),
        "overridable": list(OVERRIDABLE_FIELDS),
        "overrides": read_routing_overrides(),
        "config": {"scope": ROUTING_CONFIG_SCOPE, "key": ROUTING_CONFIG_KEY},
    }


@router.post("/routing/{source}")
def put_routing(source: str, body: dict):
    """Change one source's routing (label / kind / resolver / enabled) and save it."""
    return set_routing_override(source, body or {})


@router.delete("/routing/{source}")
def reset_routing(source: str):
    """Throw away saved tweaks for one source and restore the built-in routing."""
    return clear_routing_override(source)


@router.get("/labels")
def labels():
    """Every label the Activity feed needs, so the UI stops hardcoding them.

    What you get back: `job_kinds` (machine kind -> label/icon/type) and
    `sources` (source id -> the derived label/type/icon for that source).
    """
    return {
        "job_kinds": JOB_KINDS,
        "sources": {sid: activity_label(sid) for sid in routing_table()},
    }


@router.post("/activity-label")
def post_activity_label(body: dict | None = None):
    """Derive one activity/job label from a real source and payload.

    Body: `{"source": "...", "payload": {...}}`. See :func:`activity_label`.
    """
    body = body or {}
    payload = body.get("payload")
    return activity_label(str(body.get("source") or ""), payload if isinstance(payload, dict) else {})


@router.get("/table")
def table(source: str = "products", limit: int = 500, q: str = "", tag: str = ""):
    """Fetch one source's rows as a plain table.

    Where from: whichever resolver the routing table names for `source`.
    What you get back: `{source, columns, rows}`. For the live Supabase
    sources the column list is derived from the rows that actually came back,
    because an external table's shape isn't known ahead of time.
    An unknown `source` is a 400, never a silent switch to another dataset.
    """
    entry = resolve_source(source)
    rows = _get_rows(source, min(limit, 1000), q, tag)
    if entry["kind"] == KIND_SUPABASE_TABLE:
        # Column list isn't fixed ahead of time for a live external table —
        # derive it from whatever rows actually came back this call.
        columns: list[str] = []
        seen: set[str] = set()
        for row in rows:
            for col in row.keys():
                if col not in seen:
                    seen.add(col)
                    columns.append(col)
        return {"source": source, "columns": columns, "rows": rows}
    return {"source": source, "columns": entry["columns"], "rows": rows}


@router.post("/pivot")
def pivot(body: dict):
    """Group one source's rows and add up a number for each group.

    Where from: the same resolver /table uses, so a pivot is always over the
    same data you can see in the table.
    What you get back: `{group_by, agg, measure, rows}` where each row is
    `{key, value, count}` — e.g. group_by "brand", agg "avg", measure
    "score" gives the average score per brand, biggest group first.
    Only the fixed-shape local sources can be pivoted; the live Supabase
    tables have no declared groupable columns, so they are rejected with a
    400 rather than silently pivoted on a column that may not exist.
    """
    source = str(body.get("source") or "products")
    entry = resolve_source(source)
    if not entry["groupable"]:
        raise HTTPException(
            400,
            f"Source '{source}' ({entry['label']}) has no groupable columns, so it cannot be pivoted.",
        )
    group_by = str(body.get("group_by") or "")
    agg = str(body.get("agg") or "count")           # count | sum | avg | min | max
    measure = str(body.get("measure") or "score")
    q = str(body.get("q") or "")
    rows = _get_rows(source, 2000, q)

    buckets: dict[str, list[float]] = {}
    for r in rows:
        key = str(r.get(group_by) or "(blank)")
        val = r.get(measure)
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            buckets.setdefault(key, []).append(float(val))
        else:
            buckets.setdefault(key, []).append(0.0)

    result = []
    for key, vals in buckets.items():
        if agg == "sum":
            value = sum(vals)
        elif agg == "avg":
            value = round(sum(vals) / len(vals), 2) if vals else 0
        elif agg == "min":
            value = min(vals) if vals else 0
        elif agg == "max":
            value = max(vals) if vals else 0
        else:
            value = len(vals)
        result.append({"key": key, "value": value, "count": len(vals)})
    result.sort(key=lambda x: -x["count"])
    return {"group_by": group_by, "agg": agg, "measure": measure, "rows": result}


# --- saved views -----------------------------------------------------------
@router.get("/views")
def list_views():
    """List every saved view (a remembered source + filter + pivot setup).

    Where from: the local SQLite `data_views` table, newest first.
    What you get back: one dict per view with its name, source and the
    decoded `config` object describing how it was set up.
    """
    rows = storage._conn().execute("SELECT * FROM data_views ORDER BY id DESC").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["config"] = json.loads(d.get("config") or "{}")
        out.append(d)
    return out


@router.post("/views", status_code=201)
def create_view(body: dict):
    """Save the current table/pivot setup under a name so it can be reopened.

    Body: `{name, source, config}`. Stored in the local SQLite `data_views`
    table; returns the saved view exactly as :func:`list_views` would show it.
    """
    name = str(body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "name is required")
    source = str(body.get("source") or "products")
    config = json.dumps(body.get("config") or {})
    cur = storage._conn().execute(
        "INSERT INTO data_views (name, source, config, created_at) VALUES (?,?,?,?)",
        (name, source, config, storage.now_iso()),
    )
    storage._conn().commit()
    d = storage._conn().execute("SELECT * FROM data_views WHERE id=?", (cur.lastrowid,)).fetchone()
    d = dict(d)
    d["config"] = json.loads(d.get("config") or "{}")
    return d


@router.delete("/views/{view_id}", status_code=204)
def delete_view(view_id: int):
    """Delete one saved view from the local SQLite `data_views` table."""
    storage._conn().execute("DELETE FROM data_views WHERE id=?", (view_id,))
    storage._conn().commit()
    return None


# --- push to Asana ---------------------------------------------------------
@router.post("/push-asana")
def push_asana(body: dict):
    """Create Asana task(s) from selected rows (live only with a configured PAT).

    Body: `{name, notes, project, rows}`. Each selected row is appended to the
    task notes as a readable bullet line, then the task is created through the
    normal automation action so it goes out with the server-held Asana token —
    the browser never sees that credential.
    """
    name = str(body.get("name") or "").strip()
    notes = str(body.get("notes") or "").strip()
    project = str(body.get("project") or "").strip()
    rows = body.get("rows") or []
    if not name:
        raise HTTPException(400, "name is required")
    # Append selected rows to notes
    if rows:
        lines = ["", "Selected rows:"]
        for r in rows:
            lines.append("  · " + " | ".join(str(v) for v in r.values() if v not in (None, "")))
        notes = (notes + "\n" + "\n".join(lines)).strip()
    result = automation.execute_action(
        {"type": "asana_create_task", "target": project, "payload": {"name": name, "notes": notes}},
        ctx={},
    )
    return result


# --- ingest sources --------------------------------------------------------
@router.get("/ingest/sources")
def ingest_sources():
    """List the places data can come INTO Conductor from, and whether each is set up.

    Where from: each integration's own local config (e.g. whether an Asana
    personal access token has been saved) — no network calls, no credentials
    in the response.
    What you get back: `{"sources": [{id, label, status, note}]}` where status
    is "ready" (usable now) or "configure" (needs credentials first).
    """
    asana_cfg = {}
    try:
        import asana_sync
        asana_cfg = asana_sync.get_config()
    except Exception:
        asana_cfg = {}
    return {
        "sources": [
            {"id": "asana", "label": "Asana", "status": "ready" if asana_cfg.get("has_pat") else "configure",
             "note": "Tasks, projects, users — synced via Settings → Asana."},
            {"id": "google_sheets", "label": "Google Sheets", "status": "configure",
             "note": "Needs a Google service account / OAuth — not yet wired."},
            {"id": "google_drive", "label": "Google Drive", "status": "configure",
             "note": "Needs Drive credentials — not yet wired."},
            {"id": "local_reports", "label": "Reports on this computer", "status": "ready",
             "note": "Drop CSV/TSV/JSON/NDJSON/XLSX into Catalog Ingest."},
            {"id": "user_reports", "label": "Reports submitted by users", "status": "ready",
             "note": "POST to /webhooks/ingest or upload in Catalog Ingest."},
        ],
    }
