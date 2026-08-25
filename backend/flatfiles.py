"""Amazon Flat File creation.

Stores editable flat-file templates per product type (the columns change with
product type, and users can add/edit/remove columns and store their edits).
Templates live in the `flatfile_templates` table; generation emits a CSV flat
file with a human-label header row + machine-key row, then data rows.

Router prefix: /api/flatfiles
"""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File, Form

import storage

router = APIRouter(prefix="/api/flatfiles", tags=["flatfiles"])


# --------------------------------------------------------------------------
# Standard Amazon column presets per product type (seed for new templates).
# --------------------------------------------------------------------------
def _cols(*names):
    return [{"key": n, "label": n.replace("-", " ").replace("_", " ").title(),
             "required": n in {"sku", "price", "quantity", "product-id", "product-id-type"},
             "values": [], "example": ""} for n in names]


_COMMON = ["sku", "product-id", "product-id-type", "item-condition", "price",
           "currency", "quantity", "fulfillment-channel", "merchant-shipping-group"]

PRODUCT_TYPE_COLUMNS = {
    "General": _cols(*_COMMON, "brand-name", "item-name", "item-description",
                     "generic-keywords", "item-type-keyword", "recommended-browse-nodes"),
    "Beauty": _cols(*_COMMON, "brand-name", "item-name", "item-description",
                    "bullet-point1", "bullet-point2", "bullet-point3",
                    "ingredients", "number-of-items", "unit-count",
                    "item-type-keyword", "recommended-browse-nodes"),
    "Grocery": _cols(*_COMMON, "brand-name", "item-name", "item-description",
                     "number-of-items", "unit-count", "item-form", "flavor",
                     "expiration-date", "item-type-keyword", "recommended-browse-nodes"),
    "Apparel": _cols(*_COMMON, "brand-name", "item-name", "item-description",
                     "color", "size", "material-composition", "department",
                     "style-keywords", "item-type-keyword", "recommended-browse-nodes"),
    "Consumer Electronics": _cols(*_COMMON, "brand-name", "item-name", "item-description",
                                 "model-number", "warranty-description", "voltage",
                                 "item-type-keyword", "recommended-browse-nodes"),
    "Home": _cols(*_COMMON, "brand-name", "item-name", "item-description",
                  "material", "color", "item-dimensions-length", "item-dimensions-width",
                  "item-dimensions-height", "item-type-keyword", "recommended-browse-nodes"),
}


def _template_row(r) -> dict:
    d = dict(r)
    d["columns"] = json.loads(d.get("columns") or "[]")
    return d


def _normalize_columns(columns) -> list[dict]:
    out = []
    for c in columns or []:
        key = str(c.get("key") or "").strip().lower().replace(" ", "_")
        if not key:
            continue
        out.append({
            "key": key,
            "label": str(c.get("label") or key).strip(),
            "required": bool(c.get("required")),
            "values": [str(v).strip() for v in (c.get("values") or []) if str(v).strip()],
            "example": str(c.get("example") or "").strip(),
        })
    return out


@router.get("/presets")
def presets():
    return {"product_types": sorted(PRODUCT_TYPE_COLUMNS.keys()),
            "templates": {k: v for k, v in PRODUCT_TYPE_COLUMNS.items()}}


def _norm_key(s: str) -> str:
    return str(s or "").strip().lower().replace(" ", "_")


# --------------------------------------------------------------------------
# Template upload: user supplies their own template file (CSV/TSV).
# Row 1 = human labels; row 2 (if machine keys) = field keys; row 3 = examples.
# --------------------------------------------------------------------------
@router.post("/upload", status_code=201)
async def upload_template(file: UploadFile = File(...), product_type: str = Form("Uploaded")):
    raw = await file.read()
    if len(raw) > 5 * 1024 * 1024:
        raise HTTPException(413, "Template file too large (max 5MB)")
    text = raw.decode("utf-8-sig", errors="replace")
    lines = text.splitlines()
    delim = "\t" if (lines and "\t" in lines[0]) else ","
    rows = [r for r in csv.reader(io.StringIO(text), delimiter=delim)
            if any(str(c).strip() for c in r)]
    if not rows:
        raise HTTPException(400, "Template file is empty")
    header = [str(c).strip() for c in rows[0]]
    if not header or not any(header):
        raise HTTPException(400, "Template file has no header row")

    # Second row is treated as machine keys when it is already normalized.
    keys = None
    if len(rows) > 1 and len(rows[1]) == len(header):
        cand = [str(c).strip() for c in rows[1]]
        if all(k and k == _norm_key(k) for k in cand):
            keys = cand
    labels = header
    if keys is None:
        keys = [_norm_key(c) for c in header]

    example = ([str(c).strip() for c in rows[2]]
               if len(rows) > 2 and len(rows[2]) == len(keys) else [])
    columns = _normalize_columns([
        {"key": k, "label": lbl, "required": k in {"sku", "price", "quantity", "product-id", "product-id-type"},
         "values": [], "example": (example[i] if i < len(example) else "")}
        for i, (k, lbl) in enumerate(zip(keys, labels))
    ])
    name = (Path(file.filename or "uploaded-template").stem or "uploaded-template").strip()
    now = storage.now_iso()
    cur = storage._conn().execute(
        "INSERT INTO flatfile_templates (name, product_type, columns, header_note, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?)",
        (name, product_type, json.dumps(columns),
         "Imported from uploaded template file", now, now),
    )
    storage._conn().commit()
    return get_template(cur.lastrowid)


@router.get("")
def list_templates():
    rows = storage._conn().execute(
        "SELECT * FROM flatfile_templates ORDER BY updated_at DESC").fetchall()
    out = []
    for r in rows:
        d = _template_row(r)
        out.append({"id": d["id"], "name": d["name"], "product_type": d["product_type"],
                    "column_count": len(d["columns"]), "header_note": d["header_note"],
                    "updated_at": d["updated_at"]})
    return out


@router.get("/{template_id}")
def get_template(template_id: int):
    r = storage._conn().execute(
        "SELECT * FROM flatfile_templates WHERE id=?", (template_id,)).fetchone()
    if not r:
        raise HTTPException(404, "Template not found")
    return _template_row(r)


@router.post("", status_code=201)
def create_template(body: dict):
    name = str(body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "name is required")
    product_type = str(body.get("product_type") or "General").strip()
    columns = _normalize_columns(body.get("columns"))
    if not columns and product_type in PRODUCT_TYPE_COLUMNS:
        columns = PRODUCT_TYPE_COLUMNS[product_type]
    header_note = str(body.get("header_note") or "").strip()
    now = storage.now_iso()
    cur = storage._conn().execute(
        "INSERT INTO flatfile_templates (name, product_type, columns, header_note, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?)",
        (name, product_type, json.dumps(columns), header_note, now, now),
    )
    storage._conn().commit()
    return get_template(cur.lastrowid)


@router.put("/{template_id}")
def update_template(template_id: int, body: dict):
    r = storage._conn().execute(
        "SELECT * FROM flatfile_templates WHERE id=?", (template_id,)).fetchone()
    if not r:
        raise HTTPException(404, "Template not found")
    sets, vals = [], []
    for field, key in (("name", "name"), ("product_type", "product_type"), ("header_note", "header_note")):
        if field in body:
            sets.append(f"{key}=?")
            vals.append(str(body[field]).strip())
    if "columns" in body:
        sets.append("columns=?")
        vals.append(json.dumps(_normalize_columns(body["columns"])))
    sets.append("updated_at=?")
    vals.append(storage.now_iso())
    vals.append(template_id)
    storage._conn().execute(f"UPDATE flatfile_templates SET {', '.join(sets)} WHERE id=?", vals)
    storage._conn().commit()
    return get_template(template_id)


@router.delete("/{template_id}", status_code=204)
def delete_template(template_id: int):
    storage._conn().execute("DELETE FROM flatfile_templates WHERE id=?", (template_id,))
    storage._conn().commit()
    return None


@router.post("/{template_id}/generate")
def generate(template_id: int, body: dict):
    tpl = get_template(template_id)
    columns = tpl["columns"]
    rows = body.get("rows") or []
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([c["label"] for c in columns])          # human header
    w.writerow([c["key"] for c in columns])            # machine keys
    for row in rows:
        w.writerow([str(row.get(c["key"], "")) for c in columns])
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in (tpl["name"] or "flatfile"))
    return {"filename": f"{safe}.csv", "csv": buf.getvalue(), "columns": columns}
