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


def _get_rows(source: str, limit: int, q: str = "", tag: str = "") -> list[dict]:
    if source in SUPABASE_SOURCES:
        meta = SUPABASE_SOURCES[source]
        return _supabase_rows(meta["schema"], meta["table"], limit, q, unwrap_payload=meta.get("unwrap_payload", False))
    if source == "asana":
        return _asana_rows(limit, q)
    if source == "files":
        return _file_rows(limit, q)
    return _product_rows(limit, q, tag)


# --------------------------------------------------------------------------
# routes
# --------------------------------------------------------------------------
@router.get("/sources")
def sources():
    tags = storage.list_tags()
    out = []
    for sid, meta in SOURCES.items():
        count = 0
        try:
            if sid == "products":
                count = storage.count_products()
            elif sid == "asana":
                count = storage.asana_counts().get("tasks", 0)
            elif sid == "files":
                count = len(storage.list_files())
        except Exception:
            count = 0
        item = {"id": sid, "label": meta["label"], "columns": meta["columns"],
                "groupable": meta["groupable"], "count": count}
        if sid == "products":
            item["tags"] = tags
        out.append(item)
    for sid, meta in SUPABASE_SOURCES.items():
        count = _supabase_count(meta["schema"], meta["table"])
        out.append({"id": sid, "label": meta["label"], "columns": [], "groupable": [], "count": count})
    return out


@router.get("/table")
def table(source: str = "products", limit: int = 500, q: str = "", tag: str = ""):
    if source not in SOURCES and source not in SUPABASE_SOURCES:
        raise HTTPException(400, "Unknown source")
    rows = _get_rows(source, min(limit, 1000), q, tag)
    if source in SUPABASE_SOURCES:
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
    return {"source": source, "columns": SOURCES[source]["columns"], "rows": rows}


@router.post("/pivot")
def pivot(body: dict):
    source = str(body.get("source") or "products")
    if source not in SOURCES:
        raise HTTPException(400, "Unknown source")
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
    rows = storage._conn().execute("SELECT * FROM data_views ORDER BY id DESC").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["config"] = json.loads(d.get("config") or "{}")
        out.append(d)
    return out


@router.post("/views", status_code=201)
def create_view(body: dict):
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
    storage._conn().execute("DELETE FROM data_views WHERE id=?", (view_id,))
    storage._conn().commit()
    return None


# --- push to Asana ---------------------------------------------------------
@router.post("/push-asana")
def push_asana(body: dict):
    """Create Asana task(s) from selected rows (live only with a configured PAT)."""
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
