"""SvL (Suggested vs Live) comparison with fuzzy matching.

Takes suggested content (a proposed title, description, brand, etc.) and
compares it against live catalog data using Levenshtein distance, returning
ranked matches with a 0-1 similarity score.

Router prefix: /api/svl
"""
from __future__ import annotations

from fastapi import APIRouter

import storage

router = APIRouter(prefix="/api/svl", tags=["svl"])


# --------------------------------------------------------------------------
# Levenshtein (pure Python — no external dependency)
# --------------------------------------------------------------------------
def levenshtein(a: str, b: str) -> int:
    a, b = a or "", b or ""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(
                prev[j] + 1,          # deletion
                cur[j - 1] + 1,       # insertion
                prev[j - 1] + (ca != cb),  # substitution
            ))
        prev = cur
    return prev[-1]


def similarity(a: str, b: str) -> float:
    """0-1 normalized similarity (1 = identical)."""
    a, b = (a or "").strip().lower(), (b or "").strip().lower()
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    dist = levenshtein(a, b)
    return round(1.0 - dist / max(len(a), len(b)), 4)


def _brand(attrs: dict) -> str:
    for k in ("brand", "Brand", "BRAND", "manufacturer"):
        v = attrs.get(k)
        if v:
            return str(v).strip()
    return ""


def _field_value(product: dict, field: str) -> str:
    if field == "name":
        return (product.get("name") or "").strip()
    if field == "sku":
        return (product.get("sku") or "").strip()
    if field == "category":
        return (product.get("category") or "").strip()
    if field == "brand":
        return _brand(product.get("attributes") or {})
    if field == "market":
        return (product.get("market") or "").strip()
    # fall back to a combined haystack
    return " ".join(filter(None, [
        product.get("name") or "", product.get("sku") or "",
        product.get("category") or "", _brand(product.get("attributes") or {}),
    ])).strip()


@router.get("/sources")
def sources():
    return {
        "fields": [
            {"id": "name", "label": "Product name / title"},
            {"id": "brand", "label": "Brand"},
            {"id": "category", "label": "Category"},
            {"id": "sku", "label": "SKU"},
            {"id": "market", "label": "Market"},
        ],
        "sources": [
            {"id": "products", "label": "Catalog products", "count": storage.count_products()},
        ],
    }


@router.post("/compare")
def compare(body: dict):
    suggested = str(body.get("suggested") or "").strip()
    if not suggested:
        return {"suggested": "", "matches": [], "best": None}
    field = str(body.get("field") or "name")
    limit = int(body.get("limit") or 20)
    threshold = float(body.get("threshold") or 0.0)

    products = storage.list_products(limit=1000)
    matches = []
    for p in products:
        value = _field_value(p, field)
        if not value:
            continue
        sim = similarity(suggested, value)
        if sim < threshold:
            continue
        matches.append({
            "product_id": p["id"],
            "sku": p.get("sku") or "",
            "name": p.get("name") or "",
            "category": p.get("category") or "",
            "field": field,
            "field_value": value,
            "distance": levenshtein(suggested.lower(), value.lower()),
            "similarity": sim,
            "match": sim >= 0.9,
        })
    matches.sort(key=lambda m: (-m["similarity"], m["distance"]))
    best = matches[0] if matches else None
    return {"suggested": suggested, "field": field, "matches": matches[:limit], "best": best,
            "total": len(matches)}
