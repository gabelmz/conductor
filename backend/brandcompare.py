"""Brand & Category Competitive Comparison.

"I have brand X — show me what the top competitors are doing."

Takes a brand (the operator's) + an optional category/market scope, groups the
catalog by brand, and compares how each brand expresses the *T3 value
attributes* — the advanced listing-content dimensions that signal a product's
value proposition:

    Included Components · Target Audience · Recommended Uses · Specific Uses
    Product Benefit · Active Ingredients · Special Ingredients

Two paths:

  1. `compare` — catalog-grounded. Ranks brands in scope by product count,
     aggregates each value attribute per brand, and reports per-brand coverage.
  2. `brief`  — AI-synthesised competitive brief (uses the hosted provider,
     same plumbing as Feature Studio). Clearly labelled "AI-generated — not
     sourced from your catalog". Graceful when no key is configured.

Router prefix: /api/brandcompare
"""
from __future__ import annotations

import json
import re

from fastapi import APIRouter, HTTPException

import storage

router = APIRouter(prefix="/api/brandcompare", tags=["brandcompare"])

# --------------------------------------------------------------------------
# T3 value attributes — the comparison dimensions.
# Each entry maps a canonical id/label to the attribute keys a parser may
# have written onto the product (matched case-insensitively, punctuation
# normalised to underscores).
# --------------------------------------------------------------------------
VALUE_ATTRIBUTES = [
    {"id": "included_components", "label": "Included Components",
     "keys": ["included_components", "whats_included", "in_the_box", "components",
              "kit_includes", "included_items", "package_contents", "contents"]},
    {"id": "target_audience", "label": "Target Audience",
     "keys": ["target_audience", "audience", "intended_for", "ideal_for",
              "age_range", "who_for"]},
    {"id": "recommended_uses", "label": "Recommended Uses",
     "keys": ["recommended_uses", "recommended_use", "use_cases", "applications",
              "suitable_for"]},
    {"id": "specific_uses", "label": "Specific Uses",
     "keys": ["specific_uses", "specific_use", "uses", "intended_use", "purpose"]},
    {"id": "product_benefit", "label": "Product Benefit",
     "keys": ["product_benefit", "benefits", "benefit", "key_benefit",
              "value_proposition", "selling_points"]},
    {"id": "active_ingredients", "label": "Active Ingredients",
     "keys": ["active_ingredients", "active_ingredient", "key_ingredients",
              "ingredients", "ingredient"]},
    {"id": "special_ingredients", "label": "Special Ingredients",
     "keys": ["special_ingredients", "special_ingredient", "featured_ingredients",
              "hero_ingredients", "proprietary_blend", "signature_ingredients"]},
]

_MAX_CELL = 180  # chars per aggregated cell before truncation
_DEFAULT_TOP = 6


def _brand(attrs: dict) -> str:
    for k in ("brand", "Brand", "BRAND", "manufacturer"):
        v = attrs.get(k)
        if v:
            return str(v).strip()
    return ""


def _norm_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(key or "").lower()).strip("_")


def _attr_keys() -> dict[str, set[str]]:
    """id -> set of normalised synonym keys."""
    return {a["id"]: {_norm_key(k) for k in a["keys"]} for a in VALUE_ATTRIBUTES}


def _extract_attributes(attrs: dict) -> dict[str, str]:
    """Map a product's attribute dict onto the T3 value dimensions."""
    out: dict[str, str] = {}
    keys_by_id = _attr_keys()
    for k, v in (attrs or {}).items():
        nk = _norm_key(k)
        for aid, syns in keys_by_id.items():
            if nk in syns:
                out.setdefault(aid, str(v).strip())
                break
    return out


def _flatten(v) -> list[str]:
    """Normalise an attribute value into a list of distinct non-empty strings."""
    if v is None:
        return []
    if isinstance(v, list):
        parts = []
        for item in v:
            parts.extend(_flatten(item))
        return parts
    s = str(v).strip()
    if not s:
        return []
    # split on common list separators, but keep prose intact when short
    parts = [p.strip() for p in re.split(r"\s*[;\n]\s*|\s*,\s*", s) if p.strip()]
    return parts or [s]


def _summarise(values: list[str]) -> dict:
    """Dedupe + join a list of attribute values into a display summary."""
    seen: list[str] = []
    for v in values:
        if v and v not in seen:
            seen.append(v)
    joined = " · ".join(seen)
    if len(joined) > _MAX_CELL:
        joined = joined[:_MAX_CELL].rstrip(" ·") + "…"
    return {"distinct": len(seen), "text": joined}


def _brand_summary(brand: str, products: list[dict]) -> dict:
    """Aggregate the T3 value attributes across a brand's products in scope."""
    collected: dict[str, list[str]] = {a["id"]: [] for a in VALUE_ATTRIBUTES}
    skus: list[str] = []
    for p in products:
        skus.append(p.get("sku") or "")
        extracted = _extract_attributes(p.get("attributes") or {})
        for aid, val in extracted.items():
            collected.setdefault(aid, []).extend(_flatten(val))
    attributes = {}
    covered = 0
    for aid, vals in collected.items():
        summary = _summarise(vals)
        if summary["distinct"]:
            covered += 1
        attributes[aid] = summary
    return {
        "brand": brand,
        "product_count": len(products),
        "coverage": covered,
        "coverage_pct": round(covered / len(VALUE_ATTRIBUTES) * 100) if VALUE_ATTRIBUTES else 0,
        "attributes": attributes,
        "sample_skus": skus[:6],
    }


def _scope_products(brand: str, category: str, market: str) -> list[dict]:
    """All products with a brand, filtered to the comparison scope."""
    out = []
    for p in storage.list_products(limit=2000):
        b = _brand(p.get("attributes") or {})
        if not b:
            continue
        if category and (p.get("category") or "") != category:
            continue
        if market and (p.get("market") or "") != market:
            continue
        out.append(p)
    return out


def _known_brands() -> list[str]:
    seen: list[str] = []
    for p in storage.list_products(limit=2000):
        b = _brand(p.get("attributes") or {})
        if b and b not in seen:
            seen.append(b)
    return sorted(seen, key=str.lower)


def _known_categories() -> list[str]:
    seen: list[str] = []
    for p in storage.list_products(limit=2000):
        c = (p.get("category") or "").strip()
        if c and c not in seen:
            seen.append(c)
    return sorted(seen, key=str.lower)


def _known_markets() -> list[str]:
    seen: list[str] = []
    for p in storage.list_products(limit=2000):
        m = (p.get("market") or "").strip()
        if m and m not in seen:
            seen.append(m)
    return sorted(seen, key=str.lower)


# --------------------------------------------------------------------------
# routes
# --------------------------------------------------------------------------
@router.get("/meta")
def meta():
    return {
        "attributes": VALUE_ATTRIBUTES,
        "brands": _known_brands(),
        "categories": _known_categories(),
        "markets": _known_markets(),
        "product_count": storage.count_products(),
    }


@router.post("/compare")
def compare(body: dict):
    brand = str(body.get("brand") or "").strip()
    category = str(body.get("category") or "").strip()
    market = str(body.get("market") or "").strip()
    limit = int(body.get("limit") or _DEFAULT_TOP)
    if not brand:
        raise HTTPException(400, "brand is required — pick (or type) the brand to compare.")

    products = _scope_products(brand, category, market)

    grouped: dict[str, list[dict]] = {}
    for p in products:
        grouped.setdefault(_brand(p.get("attributes") or {}), []).append(p)

    your_brand = _brand_summary(brand, grouped.get(brand, []))
    competitors = [
        _brand_summary(b, prods)
        for b, prods in grouped.items() if b.lower() != brand.lower()
    ]
    competitors.sort(key=lambda s: (-s["product_count"], -s["coverage"], s["brand"].lower()))
    competitors = competitors[: max(0, limit)]

    return {
        "brand": brand,
        "category": category,
        "market": market,
        "scope_product_count": len(products),
        "scope_brand_count": len(grouped),
        "attributes": VALUE_ATTRIBUTES,
        "your_brand": your_brand,
        "competitors": competitors,
        "catalog_sourced": True,
        "note": (f"{len(products)} products matched this scope; "
                 f"{len(grouped)} distinct brand(s) found."),
    }


# --------------------------------------------------------------------------
# AI competitive brief (hosted provider; graceful no-key)
# --------------------------------------------------------------------------
def _strip_code_fences(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    return text.strip()


def _extract_json(text: str):
    text = _strip_code_fences(text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except Exception:
        return None


def _provider_ready():
    try:
        from ai_ingest import _provider_ready as ready
        return ready()
    except Exception:
        return None


BRIEF_SYSTEM = """You are a competitive-intelligence analyst inside Conductor, a desktop app for an
e-commerce operator selling on Amazon/Walmart/TikTok. Given a brand and a product category,
summarise what the TOP competitors in that category typically do, across these seven
T3 value attributes:

  Included Components, Target Audience, Recommended Uses, Specific Uses,
  Product Benefit, Active Ingredients, Special Ingredients

Respond with STRICT JSON ONLY — a single object:

{
  "overview": "<2-3 sentence summary of the competitive landscape for this category>",
  "attributes": [
    {"id": "<one of the seven ids below>", "label": "<label>",
     "summary": "<what top competitors typically claim/do for this attribute>"}
  ]
}

RULES:
- "id" MUST be one of: included_components, target_audience, recommended_uses,
  specific_uses, product_benefit, active_ingredients, special_ingredients.
- Include ALL seven attributes, in the order given above.
- Each "summary" is 1-2 sentences, specific to the category and useful for a
  brand owner deciding how to position their listing.
- Where the attribute does not apply to the category (e.g. Active Ingredients
  for electronics), say so plainly.
- Only output the JSON object — no prose, no markdown."""


@router.post("/brief")
def brief(body: dict):
    brand = str(body.get("brand") or "").strip()
    category = str(body.get("category") or "").strip()
    if not brand:
        raise HTTPException(400, "brand is required")
    if not category:
        raise HTTPException(400, "category is required for an AI brief")

    ready = _provider_ready()
    if not ready:
        return {"brand": brand, "category": category, "ai": False,
                "error": "No AI provider key configured — add one in Settings → AI Chat, or import competitor data into the catalog.",
                "brief": None}

    provider, model, api_key = ready
    import providers
    messages = [
        {"role": "system", "content": BRIEF_SYSTEM},
        {"role": "user", "content": f"Brand: {brand}\nCategory: {category}"},
    ]
    try:
        text = ""
        for ev in providers.stream_provider(provider, messages, model=model, api_key=api_key):
            if ev["type"] == "text":
                text += ev["text"]
            elif ev["type"] == "error":
                raise ValueError(f"Provider error: {ev.get('code')} {ev.get('message')}")
        parsed = _extract_json(text)
        if not isinstance(parsed, dict):
            raise ValueError("AI returned unparseable output (expected JSON).")
        return {"brand": brand, "category": category, "ai": True, "error": None,
                "brief": {"overview": str(parsed.get("overview") or "").strip(),
                          "attributes": parsed.get("attributes") or []}}
    except Exception as exc:
        return {"brand": brand, "category": category, "ai": False, "error": str(exc),
                "brief": None}
