"""Attribute guidelines — per-attribute (or per-grouping) quality rules.

Guidelines constrain/enforce how catalog attributes should look. Each rule is
scoped by `grouping` + `group_value`:
  - grouping 'attribute' + group_value ''        → applies to that attribute everywhere
  - grouping 'attribute' + group_value '<attr>'  → (same, group_value carries the attribute)
  - grouping 'category'|'product_type'|'market'|'brand' + group_value '<X>' → applies to
    that attribute only within the given group
  - grouping 'all' → global default for the attribute

rule_type: required | allowed_values | pattern | min_length | max_length | range

Router prefix: /api/guidelines
"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

import storage

router = APIRouter(prefix="/api/guidelines", tags=["guidelines"])

GROUPINGS = ["attribute", "category", "product_type", "market", "brand", "all"]
RULE_TYPES = ["required", "allowed_values", "pattern", "min_length", "max_length", "range"]
SEVERITIES = ["blocker", "warning", "info"]


def _row_to_guideline(row) -> dict:
    return dict(row)


@router.get("")
def list_guidelines(attribute: str | None = None, grouping: str | None = None):
    sql = "SELECT * FROM attribute_guidelines"
    conds, params = [], []
    if attribute:
        conds.append("attribute=?")
        params.append(attribute)
    if grouping:
        conds.append("grouping=?")
        params.append(grouping)
    if conds:
        sql += " WHERE " + " AND ".join(conds)
    sql += " ORDER BY grouping, attribute, id"
    rows = storage._conn().execute(sql, params).fetchall()
    return {"guidelines": [_row_to_guideline(r) for r in rows]}


@router.post("")
def create_guideline(body: dict):
    attribute = str(body.get("attribute") or "").strip()
    if not attribute:
        raise HTTPException(400, "attribute is required")
    grouping = str(body.get("grouping") or "attribute")
    if grouping not in GROUPINGS:
        raise HTTPException(400, f"grouping must be one of {', '.join(GROUPINGS)}")
    rule_type = str(body.get("rule_type") or "required")
    if rule_type not in RULE_TYPES:
        raise HTTPException(400, f"rule_type must be one of {', '.join(RULE_TYPES)}")
    severity = str(body.get("severity") or "warning")
    if severity not in SEVERITIES:
        raise HTTPException(400, f"severity must be one of {', '.join(SEVERITIES)}")
    conn = storage._conn()
    cur = conn.execute(
        "INSERT INTO attribute_guidelines "
        "(attribute, grouping, group_value, rule_type, rule_value, severity, enabled, note, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (attribute, grouping, str(body.get("group_value") or ""), rule_type,
         str(body.get("rule_value") or ""), severity,
         1 if body.get("enabled", True) else 0,
         str(body.get("note") or ""), storage.now_iso()),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM attribute_guidelines WHERE id=?", (cur.lastrowid,)).fetchone()
    return {"guideline": _row_to_guideline(row)}


@router.put("/{guideline_id}")
def update_guideline(guideline_id: int, body: dict):
    conn = storage._conn()
    row = conn.execute("SELECT * FROM attribute_guidelines WHERE id=?", (guideline_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Guideline not found")
    allowed = {"attribute", "grouping", "group_value", "rule_type", "rule_value",
               "severity", "enabled", "note"}
    sets, vals = [], []
    for k, v in body.items():
        if k not in allowed:
            continue
        if k == "grouping" and v not in GROUPINGS:
            raise HTTPException(400, f"grouping must be one of {', '.join(GROUPINGS)}")
        if k == "rule_type" and v not in RULE_TYPES:
            raise HTTPException(400, f"rule_type must be one of {', '.join(RULE_TYPES)}")
        if k == "severity" and v not in SEVERITIES:
            raise HTTPException(400, f"severity must be one of {', '.join(SEVERITIES)}")
        if k == "enabled":
            v = 1 if v else 0
        sets.append(f"{k}=?")
        vals.append(v)
    if not sets:
        return {"guideline": _row_to_guideline(row)}
    vals.append(guideline_id)
    conn.execute(f"UPDATE attribute_guidelines SET {', '.join(sets)} WHERE id=?", vals)
    conn.commit()
    row = conn.execute("SELECT * FROM attribute_guidelines WHERE id=?", (guideline_id,)).fetchone()
    return {"guideline": _row_to_guideline(row)}


@router.delete("/{guideline_id}")
def delete_guideline(guideline_id: int):
    conn = storage._conn()
    conn.execute("DELETE FROM attribute_guidelines WHERE id=?", (guideline_id,))
    conn.commit()
    return {"ok": True}


@router.get("/attributes")
def list_attributes():
    """Distinct attribute names across products (for the attribute picker)."""
    std = ["sku", "name", "category", "market", "brand", "title", "description"]
    found = set(std)
    for p in storage.list_products(limit=1000):
        for k in (p.get("attributes") or {}).keys():
            found.add(str(k))
    return {"attributes": sorted(found, key=str.lower)}


@router.get("/options")
def options():
    """Fixed enums + distinct grouping values (for the editor's pickers)."""
    conn = storage._conn()
    cats = {r[0] for r in conn.execute(
        "SELECT DISTINCT category FROM products WHERE category != 'general' AND category != ''").fetchall()}
    markets = {r[0] for r in conn.execute("SELECT DISTINCT market FROM products WHERE market != ''").fetchall()}
    return {
        "groupings": GROUPINGS,
        "rule_types": RULE_TYPES,
        "severities": SEVERITIES,
        "group_values": {
            "category": sorted(cats),
            "market": sorted(markets),
        },
    }
