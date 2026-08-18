"""Conductor — generic, schema-flexible bulk import.

A single data-type registry maps a target id -> {label, description, field
hints, write(rows)}. The importer accepts CSV / JSON array / NDJSON (or
already-parsed rows) and routes them to the right writer.

Design philosophy: field hints are for the UI preview ONLY — never strict
validation. Unknown/extra columns are preserved (merged into an `attributes`
JSON column for products/people, kept as the raw object for reports/automations)
so a user can drop arbitrary data and it imports. Per-row errors never fail the
whole import.

Router prefix: /api/import
"""
from __future__ import annotations

import csv
import io
import json
import sys
from pathlib import Path

# Make sibling backend modules importable whether this file is loaded as
# `backend.bulkimport` (repo root) or `bulkimport` (backend dir on sys.path).
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import APIRouter, HTTPException

import storage

router = APIRouter(prefix="/api/import", tags=["import"])


# ---------------------------------------------------------------------------
# parsing (CSV / JSON array / NDJSON)
# ---------------------------------------------------------------------------
def _coerce_rows(value) -> list[dict]:
    if isinstance(value, list):
        return [r for r in value if isinstance(r, dict)]
    if isinstance(value, str):
        return _parse_rows(value)
    return []


def _parse_rows(data: str) -> list[dict]:
    """Auto-detect and parse a raw string into a list of dict rows."""
    text = (data or "").strip()
    if not text:
        return []

    # 1) JSON array (or a single JSON object)
    try:
        obj = json.loads(text)
        if isinstance(obj, list):
            return [r for r in obj if isinstance(r, dict)]
        if isinstance(obj, dict):
            return [obj]
    except Exception:
        pass

    # 2) NDJSON / JSONL — one JSON object per line
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if lines:
        first = lines[0].strip()
        if first.startswith("{") or first.startswith("["):
            nd, ok = [], True
            for ln in lines:
                try:
                    o = json.loads(ln)
                except Exception:
                    ok = False
                    break
                if not isinstance(o, dict):
                    ok = False
                    break
                nd.append(o)
            if ok and nd:
                return nd

    # 3) CSV / TSV — first row is the header
    try:
        sample = text[:4096]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
        except Exception:
            dialect = csv.excel
        reader = csv.DictReader(io.StringIO(text), dialect=dialect)
        rows = []
        for r in reader:
            if r is None:
                continue
            rows.append(dict(r))
        return rows
    except Exception:
        return []


# ---------------------------------------------------------------------------
# target writers (each returns {created, skipped, errors})
# ---------------------------------------------------------------------------
def _write_products(rows: list[dict]) -> dict:
    from ingestion import run_compliance

    created = skipped = 0
    errors: list[str] = []
    for i, row in enumerate(rows):
        try:
            if not isinstance(row, dict):
                errors.append(f"row {i}: expected an object")
                skipped += 1
                continue
            sku = str(row.get("sku") or "").strip()
            name = str(row.get("name") or "").strip()
            if not sku or not name:
                errors.append(f"row {i}: sku and name are required")
                skipped += 1
                continue
            known = {"sku", "name", "category", "market", "attributes", "source", "file_id"}
            attrs = {}
            for k, v in row.items():
                if k not in known:
                    attrs[k] = v
            extra = row.get("attributes") or {}
            if isinstance(extra, dict):
                attrs = {**extra, **attrs}
            pid = storage.create_product(
                sku=sku,
                name=name,
                category=str(row.get("category") or "general"),
                market=str(row.get("market") or "US"),
                attributes=attrs,
                source=str(row.get("source") or "import"),
                file_id=row.get("file_id"),
            )
            try:
                run_compliance(pid)  # best-effort — never fail the row over it
            except Exception:
                pass
            created += 1
        except Exception as exc:
            errors.append(f"row {i}: {exc}")
    return {"created": created, "skipped": skipped, "errors": errors}


def _write_sops(rows: list[dict]) -> dict:
    created = skipped = 0
    errors: list[str] = []
    for i, row in enumerate(rows):
        try:
            if not isinstance(row, dict):
                errors.append(f"row {i}: expected an object")
                skipped += 1
                continue
            title = str(row.get("title") or "").strip()
            if not title:
                errors.append(f"row {i}: title is required")
                skipped += 1
                continue
            category = str(row.get("category") or "sop")
            if category not in ("sop", "runbook", "training", "governance"):
                category = "sop"
            body = str(row.get("body") or "")
            known = {"title", "category", "body", "version"}
            extras = {
                k: v for k, v in row.items()
                if k not in known and k not in ("id", "created_at", "updated_at")
            }
            if extras:
                body = (
                    body + "\n\n<!-- imported fields -->\n"
                    + json.dumps(extras, indent=2, default=str)
                ).strip()
            ts = storage.now_iso()
            conn = storage._conn()
            conn.execute(
                "INSERT INTO sops (title, category, body, version, created_at, updated_at) "
                "VALUES (?,?,?,1,?,?)",
                (title, category, body, ts, ts),
            )
            conn.commit()
            created += 1
        except Exception as exc:
            errors.append(f"row {i}: {exc}")
    return {"created": created, "skipped": skipped, "errors": errors}


def _write_people(rows: list[dict]) -> dict:
    from people import create_person, init_people_db

    init_people_db()  # idempotent — ensure the table exists before writing
    created = skipped = 0
    errors: list[str] = []
    for i, row in enumerate(rows):
        try:
            if not isinstance(row, dict):
                errors.append(f"row {i}: expected an object")
                skipped += 1
                continue
            create_person(row)
            created += 1
        except Exception as exc:
            errors.append(f"row {i}: {exc}")
            skipped += 1
    return {"created": created, "skipped": skipped, "errors": errors}


def _coerce_json_list(value) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        s = value.strip()
        if s:
            try:
                parsed = json.loads(s)
                if isinstance(parsed, list):
                    return parsed
                if isinstance(parsed, dict):
                    return [parsed]
            except Exception:
                pass
    return []


def _write_workflows(rows: list[dict]) -> dict:
    created = skipped = 0
    errors: list[str] = []
    for i, row in enumerate(rows):
        try:
            if not isinstance(row, dict):
                errors.append(f"row {i}: expected an object")
                skipped += 1
                continue
            name = str(row.get("name") or "").strip()
            if not name:
                errors.append(f"row {i}: name is required")
                skipped += 1
                continue
            known = {"name", "description", "trigger_source", "trigger_event",
                     "conditions", "actions", "enabled"}
            extras = {
                k: v for k, v in row.items()
                if k not in known and k not in ("id", "run_count", "last_run_at",
                                               "last_status", "last_log", "created_at")
            }
            description = str(row.get("description") or "")
            if extras:  # preserve unknown keys on the raw object
                description = (
                    description + ("\n" if description else "")
                    + json.dumps(extras, indent=2, default=str)
                ).strip()
            conn = storage._conn()
            conn.execute(
                "INSERT INTO automations (name, description, trigger_source, trigger_event, "
                "conditions, actions, enabled, created_at) VALUES (?,?,?,?,?,?,?,?)",
                (
                    name,
                    description,
                    str(row.get("trigger_source") or "manual"),
                    str(row.get("trigger_event") or ""),
                    json.dumps(_coerce_json_list(row.get("conditions"))),
                    json.dumps(_coerce_json_list(row.get("actions"))),
                    1 if row.get("enabled", True) else 0,
                    storage.now_iso(),
                ),
            )
            conn.commit()
            created += 1
        except Exception as exc:
            errors.append(f"row {i}: {exc}")
    return {"created": created, "skipped": skipped, "errors": errors}


def _write_reports(rows: list[dict]) -> dict:
    created = skipped = 0
    errors: list[str] = []
    for i, row in enumerate(rows):
        try:
            if not isinstance(row, dict):
                errors.append(f"row {i}: expected an object")
                skipped += 1
                continue
            kind = str(row.get("kind") or "import")
            title = str(row.get("title") or "").strip() or kind
            meta = row.get("meta") or {}
            if not isinstance(meta, dict):
                meta = {"raw": meta}
            data = row.get("data") or {}
            if not isinstance(data, dict):
                data = {"raw": data}
            known = {"kind", "title", "meta", "data"}
            extras = {
                k: v for k, v in row.items()
                if k not in known and k not in ("id", "created_at")
            }
            if extras:  # keep the raw object — unknown keys fold into meta
                meta = {**meta, **extras}
            conn = storage._conn()
            conn.execute(
                "INSERT INTO reports (kind, title, meta, data, created_at) VALUES (?,?,?,?,?)",
                (kind, title, json.dumps(meta), json.dumps(data), storage.now_iso()),
            )
            conn.commit()
            created += 1
        except Exception as exc:
            errors.append(f"row {i}: {exc}")
    return {"created": created, "skipped": skipped, "errors": errors}


def _write_tasks(rows: list[dict]) -> dict:
    items: list[dict] = []
    skipped = 0
    errors: list[str] = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            errors.append(f"row {i}: expected an object")
            skipped += 1
            continue
        text = str(row.get("text") or row.get("task") or "").strip()
        if not text:
            errors.append(f"row {i}: text is required")
            skipped += 1
            continue
        items.append({
            "source": str(row.get("source") or "import"),
            "text": text,
            "priority": str(row.get("priority") or "P2"),
        })
    inserted = storage.import_tasks(items)  # upserts by (source, text)
    skipped += len(items) - inserted  # duplicates count as skipped
    return {"created": inserted, "skipped": skipped, "errors": errors}


def _write_guidelines(rows: list[dict]) -> dict:
    from guidelines import GROUPINGS, RULE_TYPES, SEVERITIES

    created = skipped = 0
    errors: list[str] = []
    for i, row in enumerate(rows):
        try:
            if not isinstance(row, dict):
                errors.append(f"row {i}: expected an object")
                skipped += 1
                continue
            attribute = str(row.get("attribute") or "").strip()
            if not attribute:
                errors.append(f"row {i}: attribute is required")
                skipped += 1
                continue
            grouping = str(row.get("grouping") or "attribute")
            if grouping not in GROUPINGS:
                grouping = "attribute"
            rule_type = str(row.get("rule_type") or "required")
            if rule_type not in RULE_TYPES:
                rule_type = "required"
            severity = str(row.get("severity") or "warning")
            if severity not in SEVERITIES:
                severity = "warning"
            conn = storage._conn()
            conn.execute(
                "INSERT INTO attribute_guidelines (attribute, grouping, group_value, rule_type, "
                "rule_value, severity, enabled, note, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    attribute,
                    grouping,
                    str(row.get("group_value") or ""),
                    rule_type,
                    str(row.get("rule_value") or ""),
                    severity,
                    1 if row.get("enabled", True) else 0,
                    str(row.get("note") or ""),
                    storage.now_iso(),
                ),
            )
            conn.commit()
            created += 1
        except Exception as exc:
            errors.append(f"row {i}: {exc}")
    return {"created": created, "skipped": skipped, "errors": errors}


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------
TARGETS: dict[str, dict] = {
    "products": {
        "label": "Products",
        "description": "Catalog products. Unknown columns merge into the product's attributes; each row is run through the compliance engine.",
        "fields": ["sku", "name", "category", "market", "brand", "description", "price",
                   "currency", "condition", "image", "upc", "ean", "asin", "material",
                   "color", "size", "weight"],
        "write": _write_products,
    },
    "sops": {
        "label": "SOPs & Runbooks",
        "description": "Standard operating procedures. Unknown columns are appended into the body so nothing is lost.",
        "fields": ["title", "category", "body", "version"],
        "write": _write_sops,
    },
    "people": {
        "label": "People",
        "description": "Team directory. Unknown columns merge into the person's attributes.",
        "fields": ["name", "role", "email", "team", "notes"],
        "write": _write_people,
    },
    "workflows": {
        "label": "Workflows (Automations)",
        "description": "Trigger → condition → action automations. conditions/actions may be JSON arrays.",
        "fields": ["name", "description", "trigger_source", "trigger_event",
                   "conditions", "actions", "enabled"],
        "write": _write_workflows,
    },
    "reports": {
        "label": "Reports",
        "description": "Report records (kind/title/meta/data). Unknown columns fold into meta.",
        "fields": ["kind", "title", "meta", "data"],
        "write": _write_reports,
    },
    "tasks": {
        "label": "Tasks (Action Queue)",
        "description": "Action queue items — upserted by (source, text), so re-imports don't duplicate.",
        "fields": ["source", "text", "priority"],
        "write": _write_tasks,
    },
    "guidelines": {
        "label": "Attribute Guidelines",
        "description": "Per-attribute quality rules (required, allowed_values, pattern, min/max length, range).",
        "fields": ["attribute", "grouping", "group_value", "rule_type", "rule_value",
                   "severity", "note"],
        "write": _write_guidelines,
    },
}

for _tid, _t in TARGETS.items():
    _t["id"] = _tid


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------
@router.get("/types")
def list_types():
    return [
        {"id": t["id"], "label": t["label"], "description": t["description"],
         "fields": t["fields"]}
        for t in TARGETS.values()
    ]


@router.post("")
def do_import(body: dict):
    target_id = str(body.get("target") or "")
    target = TARGETS.get(target_id)
    if not target:
        raise HTTPException(400, f"Unknown target '{target_id}' — available: {', '.join(TARGETS)}")
    rows = _coerce_rows(body.get("rows") if "rows" in body else body.get("data"))
    result = target["write"](rows)
    return {
        "target": target_id,
        "received": len(rows),
        "created": result["created"],
        "skipped": result["skipped"],
        "errors": result["errors"],
    }
