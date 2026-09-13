"""Header mapping and schema reconciliation engine.

All new uploads, report arrivals, schemas, and syncs land here to reconcile incoming file
headers with known domain fields (e.g. sku, product_name, category, price, brand, quantity).

Match sequence for incoming report headers:
  1. Exact header-set match (order agnostic, normalized).
  2. Fuzzy match against known spine presets / field definitions (difflib SequenceMatcher).
  3. If top match confidence is < 90%, flag as `needs_user_mapping` so the user is prompted to map header -> field/field-type pairs.
  4. Saving user mapping persists it as a re-usable preset.

Router prefix: /api/mapping
"""
from __future__ import annotations

import difflib
import json
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

import storage
from storage import DATA_DIR, now_iso

router = APIRouter(prefix="/api/mapping", tags=["mapping"])

PRESETS_PATH = DATA_DIR / "mapping_presets.json"

KNOWN_FIELDS = [
    {"key": "sku", "label": "SKU", "type": "string", "aliases": ["product_sku", "seller_sku", "item_sku", "sku_number"]},
    {"key": "name", "label": "Product Name", "type": "string", "aliases": ["title", "product_name", "item_name", "title_quality"]},
    {"key": "category", "label": "Category", "type": "string", "aliases": ["product_category", "item_category", "department", "type"]},
    {"key": "price", "label": "Price", "type": "number", "aliases": ["unit_price", "msrp", "listing_price", "cost"]},
    {"key": "brand", "label": "Brand", "type": "string", "aliases": ["brand_name", "manufacturer", "make"]},
    {"key": "quantity", "label": "Quantity", "type": "integer", "aliases": ["stock", "qty", "inventory", "units"]},
    {"key": "asin", "label": "ASIN", "type": "string", "aliases": ["amazon_asin", "product_id", "item_id"]},
    {"key": "status", "label": "Status", "type": "string", "aliases": ["item_status", "compliance_status", "state"]},
    {"key": "upc", "label": "UPC / Barcode", "type": "string", "aliases": ["gtin", "ean", "barcode"]},
    {"key": "description", "label": "Description", "type": "string", "aliases": ["item_description", "product_description", "summary"]},
]


def _normalize_header(h: str) -> str:
    return str(h or "").strip().lower().replace("-", "_").replace(" ", "_")


def _read_presets() -> list[dict[str, Any]]:
    if PRESETS_PATH.exists():
        try:
            data = json.loads(PRESETS_PATH.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
        except Exception:
            pass
    return []


def _save_presets(presets: list[dict[str, Any]]) -> None:
    PRESETS_PATH.write_text(json.dumps(presets, indent=2), encoding="utf-8")


def _fuzzy_field_match(header: str) -> tuple[str, str, float]:
    """Find the best matching known field for an incoming header using fuzzy similarity."""
    norm = _normalize_header(header)
    best_key = "unknown"
    best_type = "string"
    best_ratio = 0.0

    for field in KNOWN_FIELDS:
        key = field["key"]
        ftype = field["type"]
        candidates = [key, _normalize_header(field["label"])] + [_normalize_header(a) for a in field["aliases"]]
        for cand in candidates:
            if norm == cand:
                return key, ftype, 1.0
            ratio = difflib.SequenceMatcher(None, norm, cand).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_key = key
                best_type = ftype

    return best_key, best_type, round(best_ratio, 4)


@router.get("/known-fields")
def get_known_fields():
    return {"fields": KNOWN_FIELDS}


@router.get("/presets")
def get_presets():
    return {"presets": _read_presets()}


@router.post("/match")
def match_headers(body: dict[str, Any]):
    headers = body.get("headers") or []
    if not isinstance(headers, list) or not headers:
        raise HTTPException(400, "headers list is required")

    norm_incoming = set(_normalize_header(h) for h in headers)
    presets = _read_presets()

    # 1. Exact header-set match (order agnostic)
    for preset in presets:
        preset_headers = set(_normalize_header(h) for h in preset.get("headers", []))
        if norm_incoming == preset_headers:
            return {
                "match_type": "exact",
                "confidence": 1.0,
                "needs_user_mapping": False,
                "preset": preset,
                "mappings": preset.get("mappings", {}),
            }

    # 2. Fuzzy match field-by-field
    field_mappings: dict[str, dict[str, Any]] = {}
    total_confidence = 0.0

    for h in headers:
        best_key, ftype, score = _fuzzy_field_match(h)
        field_mappings[h] = {
            "mapped_field": best_key,
            "field_type": ftype,
            "confidence": score,
        }
        total_confidence += score

    overall_confidence = round(total_confidence / max(len(headers), 1), 4)
    needs_user = overall_confidence < 0.90

    return {
        "match_type": "fuzzy",
        "confidence": overall_confidence,
        "needs_user_mapping": needs_user,
        "preset": None,
        "mappings": field_mappings,
    }


@router.post("/save-preset", status_code=201)
def save_preset(body: dict[str, Any]):
    name = str(body.get("name") or "").strip()
    headers = body.get("headers") or []
    mappings = body.get("mappings") or {}

    if not name:
        raise HTTPException(400, "Preset name is required")
    if not isinstance(headers, list) or not headers:
        raise HTTPException(400, "headers list is required")

    presets = _read_presets()
    new_preset = {
        "id": f"preset_{len(presets) + 1}",
        "name": name,
        "headers": headers,
        "mappings": mappings,
        "created_at": now_iso(),
    }
    presets.append(new_preset)
    _save_presets(presets)
    return new_preset


@router.get("/pending")
def list_pending():
    """List pending uploads, schemas, and syncs that require or have landed for mapping."""
    files = storage.list_files(limit=50)
    pending = []
    for f in files:
        fn = f.get("filename") or ""
        pending.append({
            "id": f.get("upload_id") or str(f.get("id")),
            "name": fn,
            "source": "file_upload",
            "status": f.get("status") or "ready",
            "created_at": f.get("created_at") or "",
            "records": f.get("record_count") or 0,
        })
    return {"pending": pending}
