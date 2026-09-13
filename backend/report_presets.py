"""Report-format presets — auto-recognition, typed field schemas, and user editing.

Every report the catalog department drops into Conductor is matched against a
preset so it lands in the right view with the right column types, immediately —
no manual format selection. A preset describes:

  * how to RECOGNISE the file (extension, delimiter, sheet name, header signature)
  * the typed FIELD SCHEMA (string / int / float / percent / currency / date / bool / json)
  * the entity it maps onto (cdq, listing, shipment, sales, asin_map, roster, ...)

Presets are user-editable and "tagged onto the spine": the canonical set lives in
this module (``BUILTIN_REPORT_PRESETS``, seeded into ``spine_registry`` by
``default_state.seed_report_presets``), while user overrides are persisted through
``spine.user_config`` under scope ``reports`` / key ``presets``. ``resolve_presets()``
merges the two so an edited preset survives a re-seed without clobbering the shipped
defaults.

Router prefix: /api/report-presets
"""
from __future__ import annotations

import csv
import io
import json
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/report-presets", tags=["report-presets"])

# --- Spine tagging -----------------------------------------------------------
# User overrides for presets live in the spine's user-config layer (non-secret,
# user-editable). The scope/key are deliberately distinct from reports.py's
# "scoring"/"presets" (CDQ scoring weights) to avoid any key collision.
SPINE_SCOPE = "reports"
SPINE_KEY = "presets"

# Registry kind used to "tag" each preset into spine_registry so it is visible in
# the spine feature glossary and Supabase `conductor.*` mirror.
REGISTRY_KIND = "report_preset"

# --- Field types -------------------------------------------------------------
FIELD_TYPES = ("string", "int", "float", "number", "percent", "currency",
               "date", "bool", "json")
NUMERIC_TYPES = {"int", "float", "number", "percent", "currency"}


def _f(key: str, label: str, ftype: str = "string", *, required: bool = False,
       aliases: tuple[str, ...] = ()) -> dict:
    return {"key": key, "label": label, "type": ftype, "required": required,
            "aliases": list(aliases)}


def _normalize(h: str) -> str:
    """Header token normalisation — matches the parser's `_clean_header`."""
    out = []
    for ch in str(h or "").lower():
        out.append(ch if ch.isalnum() else "_")
    return "_".join(part for part in "".join(out).split("_") if part)


# =============================================================================
# Built-in presets — one per report format the catalog dept actually receives.
# =============================================================================
BUILTIN_REPORT_PRESETS: dict[str, dict] = {
    # 1. KPI definitions — Sheet13.csv (two sections: Universal KPIs / Team KPIs)
    "kpi_definitions": {
        "key": "kpi_definitions",
        "label": "KPI Definitions",
        "category": "team",
        "description": "Universal + Team KPI definitions with unit type (#, %, $, D) and a plain-language description.",
        "entity": "kpi_definition",
        "is_document": False,
        "file": {
            "extensions": [".csv"],
            "delimiter": ",",
            "sheet": None,
            "header_row": 0,
            "multi_section": True,
            "header_signature": ["universal_kpis", "definitions", "type", "option_2",
                                 "team_kpis"],
        },
        "fields": [
            _f("kpi_name", "KPI Name", "string", required=True, aliases=("universal_kpis", "team_kpis", "kpi")),
            _f("definition", "Definition", "string", aliases=("definitions",)),
            _f("type", "Unit Type", "string", aliases=("option_2",)),
            _f("description", "Description", "string"),
            _f("section", "Section", "string"),
        ],
    },
    # 2. Catalog OPS — BASE v2.xlsx (employee roster / org chart, sheet "BASE")
    "catalog_ops": {
        "key": "catalog_ops",
        "label": "Catalog OPS — Employee Roster",
        "category": "team",
        "description": "Employee roster and org chart: identity, role, employment lifecycle, time/attendance, compensation.",
        "entity": "employee",
        "is_document": False,
        "file": {
            "extensions": [".xlsx", ".xlsm"],
            "delimiter": None,
            "sheet": "BASE",
            "header_row": 3,
            "multi_section": False,
            "header_signature": ["employee_name", "job_title", "team", "manager",
                                 "annual_salary", "segment"],
        },
        "fields": [
            _f("employee_name", "Employee Name", "string", required=True, aliases=("name",)),
            _f("alias", "Alias / Preferred", "string", aliases=("alias_or_preferred",)),
            _f("email", "Email", "string"),
            _f("employee_id", "Employee ID", "string"),
            _f("job_title", "Job Title", "string"),
            _f("team", "Team", "string"),
            _f("manager", "Manager", "string"),
            _f("location", "Location", "string"),
            _f("employment_status", "Employment Status", "string"),
            _f("start_date", "Start Date", "date"),
            _f("tenure_days", "Tenure (Days)", "int", aliases=("tenure",)),
            _f("pay_frequency", "Pay Frequency", "string"),
            _f("hourly_rate", "Hourly Rate", "currency"),
            _f("weekly_pay", "Weekly Pay", "currency"),
            _f("monthly_salary", "Monthly Salary", "currency"),
            _f("annual_salary", "Annual Salary", "currency"),
            _f("annual_cost_to_company", "Annual Cost to Company", "currency"),
            _f("segment", "Segment", "string"),
        ],
    },
    # 3. All Active ASIN List — gabe (1).csv (vendor -> ASIN -> SKU map)
    "asin_map": {
        "key": "asin_map",
        "label": "Active ASIN List",
        "category": "catalog",
        "description": "Vendor → ASIN → SKU mapping, plus marketplace platform and id type.",
        "entity": "asin_sku_map",
        "is_document": False,
        "file": {
            "extensions": [".csv"],
            "delimiter": ",",
            "sheet": None,
            "header_row": 0,
            "multi_section": False,
            "header_signature": ["vendor", "finsished_goods_id", "sku", "id_type", "platform"],
        },
        "fields": [
            _f("vendor", "Vendor", "string", required=True),
            _f("asin", "ASIN", "string", required=True, aliases=("finsished_goods_id", "finished_goods_id", "asin1")),
            _f("sku", "SKU", "string", required=True, aliases=("seller_sku",)),
            _f("id_type", "ID Type", "string"),
            _f("platform", "Platform", "string"),
        ],
    },
    # 4. CDQ_Report.csv (Catalog Data Quality)
    "cdq_report": {
        "key": "cdq_report",
        "label": "CDQ Report",
        "category": "catalog_quality",
        "description": "Catalog Data Quality v3: grades, scores, listing-completeness and policy flags per ASIN.",
        "entity": "cdq",
        "is_document": False,
        "file": {
            "extensions": [".csv"],
            "delimiter": ",",
            "sheet": None,
            "header_row": 0,
            "multi_section": False,
            "header_signature": ["parent_asin", "cdq_v3_grade", "cdq_v3_score",
                                 "title_quality_score", "image_quality_score"],
        },
        "fields": [
            _f("parent_asin", "Parent ASIN", "string"),
            _f("asins", "ASINs", "string", required=True),
            _f("marketplace", "Marketplace", "string"),
            _f("title", "Title", "string"),
            _f("brand_name", "Brand Name", "string"),
            _f("cdq_grade", "CDQ v3 Grade", "string"),
            _f("cdq_score", "CDQ v3 Score", "percent"),
            _f("has_retail_offer", "Has Retail Offer", "bool"),
            _f("has_list_price", "Has List Price", "bool"),
            _f("has_leaf_node", "Has Leaf Node", "bool"),
            _f("has_keywords", "Has Keywords", "bool"),
            _f("is_quarantined", "Is Quarantined", "bool"),
            _f("title_char_count", "Title Character Count", "int"),
            _f("bullet_points_count", "Bullet Points Count", "int"),
            _f("bullet_quality_score", "Bullet Point Quality Score", "percent"),
            _f("relevant_attributes_coverage", "Relevant Attributes Coverage Top 10", "percent"),
            _f("structured_attribute_quality", "Structured Attribute Quality Score", "percent"),
            _f("has_aplus", "Has A+", "bool"),
            _f("category", "Category", "string"),
            _f("subcategory", "Subcategory", "string"),
            _f("product_type", "Product Type", "string"),
            _f("is_policy_compliant", "Is Policy Compliant", "bool"),
            _f("title_quality_score", "Title Quality Score", "percent"),
            _f("image_quality_score", "Image Quality Score", "percent"),
            _f("aplus_score", "A+ Score", "percent"),
            _f("variations_score", "Variations Score", "percent"),
        ],
    },
    # 5. 20260910_reviews.xlsx (reviews + OPS sales, sheet "Export Data")
    "reviews_ops": {
        "key": "reviews_ops",
        "label": "Reviews + OPS",
        "category": "reviews",
        "description": "Per-ASIN rating, review count, net ordered units, OPS dollars, ASP, refund and return metrics.",
        "entity": "reviews_ops",
        "is_document": False,
        "file": {
            "extensions": [".xlsx", ".xlsm"],
            "delimiter": None,
            "sheet": "Export Data",
            "header_row": 0,
            "multi_section": False,
            "header_signature": ["display_rating", "total_rating_count", "parent_asin",
                                 "net_ordered_units", "ops", "refund_rate"],
        },
        "fields": [
            _f("display_rating", "Display Rating", "float"),
            _f("total_rating_count", "Total Rating Count", "int"),
            _f("parent_asin", "Parent ASIN", "string"),
            _f("parent_item_name", "Parent Item Name", "string"),
            _f("asin", "ASIN", "string", required=True),
            _f("item_name", "Item Name", "string"),
            _f("raw_rating", "Raw Rating", "float"),
            _f("preferred_display_name", "Preferred Display Name", "string"),
            _f("msku", "MSKU", "string"),
            _f("net_ordered_units", "Net Ordered Units", "int"),
            _f("ops", "OPS ($)", "currency"),
            _f("avg_selling_price", "CA Average Selling Price ($)", "currency"),
            _f("refund_rate", "Refund Rate (%)", "percent"),
            _f("total_refund_amount", "Total Refund Amount ($)", "currency"),
            _f("total_refund_units", "Total Refund Units", "int"),
            _f("gross_shipped_units", "Gross Shipped Units", "int"),
            _f("return_quantity", "Return Quantity", "int"),
        ],
    },
    # 6. All+Listings+Report_09-10-2026.txt (Amazon category listings, tab-delimited)
    "amazon_listings": {
        "key": "amazon_listings",
        "label": "Amazon Listings Report",
        "category": "catalog",
        "description": "Amazon category-listings export: item, price, quantity, condition, ASIN and fulfillment channel.",
        "entity": "listing",
        "is_document": False,
        "file": {
            "extensions": [".txt", ".tab", ".tsv"],
            "delimiter": "\t",
            "sheet": None,
            "header_row": 0,
            "multi_section": False,
            "header_signature": ["item_name", "item_description", "listing_id", "seller_sku",
                                 "price", "quantity", "fulfillment_channel"],
        },
        "fields": [
            _f("item_name", "Item Name", "string", required=True),
            _f("item_description", "Item Description", "string"),
            _f("listing_id", "Listing ID", "string"),
            _f("seller_sku", "Seller SKU", "string", aliases=("sku",)),
            _f("price", "Price", "currency"),
            _f("quantity", "Quantity", "int"),
            _f("open_date", "Open Date", "date"),
            _f("image_url", "Image URL", "string"),
            _f("product_id_type", "Product ID Type", "string"),
            _f("item_condition", "Item Condition", "string"),
            _f("asin", "ASIN", "string", aliases=("asin1", "asin2", "asin3", "product_id")),
            _f("fulfillment_channel", "Fulfillment Channel", "string"),
            _f("merchant_shipping_group", "Merchant Shipping Group", "string"),
            _f("status", "Status", "string"),
        ],
    },
    # 7. Handover Document_Zefran Barola.docx (narrative, no tabular schema)
    "handover_doc": {
        "key": "handover_doc",
        "label": "Handover / Process Document",
        "category": "document",
        "description": "Narrative handover or process document (DOCX/PDF). No column schema — routed to the document viewer.",
        "entity": "document",
        "is_document": True,
        "file": {
            "extensions": [".docx", ".pdf", ".md"],
            "delimiter": None,
            "sheet": None,
            "header_row": None,
            "multi_section": False,
            "header_signature": [],
        },
        "fields": [],
    },
    # 8. shipments-api - shipment-level.csv (FBA shipment-level)
    "shipments": {
        "key": "shipments",
        "label": "FBA Shipments (Shipment-level)",
        "category": "supply_chain",
        "description": "FBA shipment-level report: qty shipped/received, discrepancy, and COGs per shipment.",
        "entity": "shipment",
        "is_document": False,
        "file": {
            "extensions": [".csv"],
            "delimiter": ",",
            "sheet": None,
            "header_row": 0,
            "multi_section": False,
            "header_signature": ["date_created", "seller", "shipment_id", "qty_shipped",
                                 "qty_received", "cogs_shipped"],
        },
        "fields": [
            _f("date_created", "Date Created", "date"),
            _f("seller", "Seller", "string"),
            _f("shipment_id", "Shipment ID", "string", required=True),
            _f("date_closed", "Date Closed", "date"),
            _f("shipment_status", "Shipment Status", "string"),
            _f("destination_fc", "Destination FC", "string"),
            _f("unique_fnskus", "Unique FNSKUs", "int"),
            _f("unique_skus_outbound", "Unique SKUs Outbound", "int"),
            _f("unique_asins_outbound", "Unique ASINs Outbound", "int"),
            _f("unique_asins_received", "Unique ASINs Received", "int"),
            _f("qty_shipped", "Qty Shipped", "int"),
            _f("qty_received", "Qty Received", "int"),
            _f("diff", "Diff", "int"),
            _f("cogs_shipped", "COGs Shipped", "currency"),
            _f("cogs_received", "COGs Received", "currency"),
            _f("cogs_diff", "COGs Diff", "currency"),
        ],
    },
    # 9. sales-by-collection-quarterly-Q2-2026-all.csv (sales rollup by category)
    "sales_by_collection": {
        "key": "sales_by_collection",
        "label": "Sales by Collection (Quarterly)",
        "category": "sales",
        "description": "Quarterly sales rollup by collection/category with vs-previous-quarter and vs-prior-year deltas.",
        "entity": "sales",
        "is_document": False,
        "file": {
            "extensions": [".csv"],
            "delimiter": ",",
            "sheet": None,
            "header_row": 0,
            "multi_section": False,
            "header_signature": ["category", "total_sales", "percentage_of_total",
                                 "vs_previous_quarter", "vs_same_quarter_last_year"],
        },
        "fields": [
            _f("category", "Category", "string", required=True, aliases=("collection",)),
            _f("total_sales", "Total Sales", "currency"),
            _f("percentage_of_total", "Percentage of Total", "percent"),
            _f("vs_previous_quarter_pct", "vs Previous Quarter (%)", "percent"),
            _f("vs_previous_quarter_usd", "vs Previous Quarter ($)", "currency"),
            _f("vs_same_quarter_last_year_pct", "vs Same Quarter Last Year (%)", "percent"),
            _f("vs_same_quarter_last_year_usd", "vs Same Quarter Last Year ($)", "currency"),
        ],
    },
}


# --- Detection ---------------------------------------------------------------
def _read_header_tokens(filename: str | None, headers: list[str] | None,
                        first_rows: list[str] | None) -> set[str]:
    """Collect normalised header tokens from whatever the caller can provide."""
    tokens: set[str] = set()
    for h in (headers or []):
        tokens.add(_normalize(h))
    for row in (first_rows or []):
        for tok in row.replace(",", " ").replace("\t", " ").split():
            tokens.add(_normalize(tok))
    if filename:
        tokens.add(_normalize(filename))
    return tokens


def _score_preset(preset: dict, filename: str | None, extension: str | None,
                  sheet: str | None, tokens: set[str]) -> float:
    """0..1 confidence that `preset` describes this file."""
    f = preset["file"]
    score = 0.0
    # Extension match
    if extension:
        exts = [e.lower() for e in f["extensions"]]
        score += 0.25 if (extension.lower() in exts) else -0.3
    # Sheet name match (spreadsheets)
    if f.get("sheet"):
        score += 0.25 if (sheet and sheet.lower() == f["sheet"].lower()) else -0.2
    elif f["extensions"] and f["extensions"][0].lower() in (".xlsx", ".xlsm", ".xlsb"):
        # spreadsheet preset but sheet not confirmed — neutral
        pass
    # Header signature overlap
    sig = {_normalize(s) for s in f.get("header_signature", [])}
    if sig:
        overlap = len(sig & tokens)
        score += 0.5 * (overlap / len(sig))
    return round(score, 4)


def detect_report_format(filename: str | None = None, *, headers: list[str] | None = None,
                         sheet: str | None = None,
                         first_rows: list[str] | None = None) -> dict:
    """Recognise which preset (if any) a report matches.

    Returns ``{key, label, confidence, match_type}``. ``match_type`` is "exact"
    when the header signature is fully present, "partial" when it clears a
    minimum threshold, or "none" when nothing matches. Callers that get "none"
    should fall through to the generic Mapping page for user-assisted mapping.
    """
    extension = None
    if filename and "." in filename:
        extension = filename[filename.rfind("."):]
    tokens = _read_header_tokens(filename, headers, first_rows)

    best_key, best_label, best_score = None, None, -1.0
    for key, preset in BUILTIN_REPORT_PRESETS.items():
        s = _score_preset(preset, filename, extension, sheet, tokens)
        if s > best_score:
            best_key, best_label, best_score = key, preset["label"], s

    if best_key is None:
        return {"key": None, "label": None, "confidence": 0.0, "match_type": "none"}

    match_type = "exact" if best_score >= 0.9 else ("partial" if best_score >= 0.45 else "none")
    if match_type == "none":
        return {"key": None, "label": None, "confidence": best_score, "match_type": "none"}
    return {"key": best_key, "label": best_label, "confidence": best_score,
            "match_type": match_type}


# --- Spine-backed preset store ------------------------------------------------
def _spine_read(default: dict) -> dict:
    try:
        from spine import user_config
        value = user_config.read_configuration_value(SPINE_SCOPE, SPINE_KEY, default)
    except Exception:
        return dict(default)
    return value if isinstance(value, dict) else dict(default)


def _spine_write(value: dict) -> None:
    from spine.schema import init_tables
    from spine import user_config
    init_tables()
    user_config.put_configuration(SPINE_SCOPE, SPINE_KEY, {"value": value})


def stored_overrides() -> dict[str, dict]:
    value = _spine_read({})
    return {str(k): v for k, v in value.items() if isinstance(v, dict)}


def resolve_presets() -> dict[str, dict]:
    """Merged view: builtin defaults, overlaid with user overrides from the spine."""
    out = {k: dict(v) for k, v in BUILTIN_REPORT_PRESETS.items()}
    for key, body in stored_overrides().items():
        merged = dict(out.get(key, {}))
        merged.update(body)
        merged["key"] = key
        merged["builtin"] = key in BUILTIN_REPORT_PRESETS
        out[key] = merged
    for key, body in out.items():
        body.setdefault("builtin", True)
    return out


def _validate_preset(body: dict) -> dict:
    if not isinstance(body, dict):
        raise HTTPException(400, "preset must be an object")
    label = str(body.get("label") or "").strip()
    if not label:
        raise HTTPException(400, "preset.label is required")
    entity = str(body.get("entity") or "report")
    file_meta = body.get("file")
    if not isinstance(file_meta, dict):
        raise HTTPException(400, "preset.file must be an object")
    fields = body.get("fields")
    if not isinstance(fields, list):
        raise HTTPException(400, "preset.fields must be a list")
    out_fields: list[dict] = []
    for i, f in enumerate(fields):
        if not isinstance(f, dict):
            raise HTTPException(400, f"preset.fields[{i}] must be an object")
        ftype = str(f.get("type") or "string")
        if ftype not in FIELD_TYPES:
            raise HTTPException(400, f"preset.fields[{i}].type '{ftype}' not in {FIELD_TYPES}")
        fkey = str(f.get("key") or "").strip()
        if not fkey:
            raise HTTPException(400, f"preset.fields[{i}].key is required")
        out_fields.append({
            "key": fkey,
            "label": str(f.get("label") or fkey),
            "type": ftype,
            "required": bool(f.get("required")),
            "aliases": [str(a) for a in (f.get("aliases") or [])],
        })
    keys = [f["key"] for f in out_fields]
    if len(set(keys)) != len(keys):
        raise HTTPException(400, "preset.fields[].key must be unique")
    return {
        "label": label,
        "category": str(body.get("category") or "reports"),
        "description": str(body.get("description") or ""),
        "entity": entity,
        "is_document": bool(body.get("is_document")),
        "file": {
            "extensions": [str(e) for e in (file_meta.get("extensions") or [])],
            "delimiter": file_meta.get("delimiter"),
            "sheet": file_meta.get("sheet"),
            "header_row": file_meta.get("header_row"),
            "multi_section": bool(file_meta.get("multi_section")),
            "header_signature": [str(s) for s in (file_meta.get("header_signature") or [])],
        },
        "fields": out_fields,
    }


# --- API ---------------------------------------------------------------------
@router.get("/presets")
def list_presets():
    presets = resolve_presets()
    return {"presets": list(presets.values()), "count": len(presets)}


@router.get("/presets/{key}")
def get_preset(key: str):
    presets = resolve_presets()
    if key not in presets:
        raise HTTPException(404, f"Unknown report preset '{key}'")
    return presets[key]


@router.post("/detect")
def detect(body: dict):
    """Recognise a report from filename + header tokens without saving anything."""
    return detect_report_format(
        body.get("filename"),
        headers=body.get("headers"),
        sheet=body.get("sheet"),
        first_rows=body.get("first_rows"),
    )


@router.put("/presets/{key}")
def save_preset(key: str, body: dict):
    """Create or edit a report preset. Edits are stored on the spine (user-config)."""
    key = str(key or "").strip()
    if not key:
        raise HTTPException(400, "preset key is required")
    preset = _validate_preset(body)
    preset["key"] = key
    preset["builtin"] = key in BUILTIN_REPORT_PRESETS
    overrides = stored_overrides()
    overrides[key] = {k: v for k, v in preset.items() if k != "key" and k != "builtin"}
    _spine_write(overrides)
    return preset


@router.delete("/presets/{key}", status_code=204)
def delete_preset(key: str):
    overrides = stored_overrides()
    if key in BUILTIN_REPORT_PRESETS:
        raise HTTPException(400, f"'{key}' is a built-in preset — override it instead of deleting it.")
    if key not in overrides:
        raise HTTPException(404, f"Unknown report preset '{key}'")
    overrides.pop(key)
    _spine_write(overrides)
    return None


@router.post("/presets/{key}/reset", status_code=204)
def reset_preset(key: str):
    """Drop a user override, restoring the built-in default."""
    overrides = stored_overrides()
    overrides.pop(key, None)
    _spine_write(overrides)
    return None


@router.get("/field-types")
def field_types():
    return {"types": list(FIELD_TYPES), "numeric": sorted(NUMERIC_TYPES)}


# --- parser convenience (shared with ingestion) -------------------------------
def parse_delimited(path, preset: dict) -> list[dict]:
    """Parse a delimited report against a preset's typed field schema.

    Returns rows keyed by field key, with numeric/percent/currency fields coerced.
    Unparseable numeric cells are left as-is (never silently zeroed).
    """
    delimiter = preset["file"].get("delimiter") or ","
    with open(path, "r", encoding="utf-8-sig", errors="replace", newline="") as fh:
        reader = csv.reader(fh, delimiter=delimiter)
        rows = list(reader)
    if not rows:
        return []
    fields = {f["key"]: f for f in preset["fields"]}
    headers = [_normalize(h) for h in rows[preset["file"].get("header_row", 0)]]
    data_start = preset["file"].get("header_row", 0) + 1
    out = []
    for raw in rows[data_start:]:
        if not any(str(c).strip() for c in raw):
            continue
        record: dict[str, Any] = {}
        for idx, value in enumerate(raw):
            if idx >= len(headers):
                break
            # map header token back to a field key
            for fkey, f in fields.items():
                candidates = {_normalize(fkey), _normalize(f["label"])} | {_normalize(a) for a in f["aliases"]}
                if headers[idx] in candidates:
                    record[fkey] = _coerce(value, f)
                    break
            else:
                record[headers[idx]] = value
        out.append(record)
    return out


def _coerce(value: Any, field: dict) -> Any:
    text = str(value).strip()
    if text == "":
        return None
    ftype = field["type"]
    if ftype in ("int", "float", "number", "currency"):
        cleaned = text.replace("$", "").replace(",", "").replace("%", "").strip()
        try:
            return int(float(cleaned)) if ftype == "int" else float(cleaned)
        except (TypeError, ValueError):
            return text
    if ftype == "percent":
        cleaned = text.replace("%", "").replace(",", "").strip()
        try:
            value = float(cleaned)
        except (TypeError, ValueError):
            return text
        has_pct_sign = "%" in text
        if has_pct_sign:
            return value / 100.0
        # No "%" sign: a value like "0.024" is already a fraction (reviews
        # "Refund Rate(%)" ships as raw decimals), while "88.59" or "100" means
        # a percentage point. Disambiguate by magnitude.
        if abs(value) <= 1.0:
            return value
        return value / 100.0
    if ftype == "bool":
        return text.lower() in ("1", "yes", "true", "y", "on")
    return text
