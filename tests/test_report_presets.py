import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import report_presets
from report_presets import (router, detect_report_format, resolve_presets,
                            stored_overrides, BUILTIN_REPORT_PRESETS, FIELD_TYPES)

app = FastAPI()
app.include_router(router)
client = TestClient(app)


# --- format recognition (immediate, no manual selection) ---------------------
DETECT_CASES = [
    # (filename, headers, sheet, expected_key)
    ("CDQ_Report.csv",
     ["Parent ASIN", "ASINs", "Marketplace", "Title", "Brand Name", "CDQ v3 Grade",
      "CDQ v3 Score", "Title Quality Score", "Image Quality Score", "Aplus Score"],
     None, "cdq_report"),
    ("shipments-api - shipment-level.csv",
     ["Date Created", "Seller", "Shipment ID", "Shipment Status", "Qty Shipped",
      "Qty Received", "COGs Shipped", "COGs Received", "COGs Diff"],
     None, "shipments"),
    ("sales-by-collection-quarterly-Q2-2026-all.csv",
     ["Category", "Total Sales", "Percentage of Total", "vs Previous Quarter (%)",
      "vs Same Quarter Last Year ($)"],
     None, "sales_by_collection"),
    ("All Active ASIN List - gabe (1).csv",
     ["vendor", "finsished_goods_id", "sku", "id_type", "platform"],
     None, "asin_map"),
    ("All+Listings+Report_09-10-2026.txt",
     ["item-name", "item-description", "listing-id", "seller-sku", "price", "quantity",
      "fulfillment-channel", "status"],
     None, "amazon_listings"),
    ("20260910_reviews.xlsx",
     ["Display rating", "Total rating count", "Parent ASIN", "Net Ordered Units",
      "OPS($)", "Refund Rate(%)"],
     "Export Data", "reviews_ops"),
    ("Catalog OPS - BASE v2.xlsx",
     ["Employee Name", "Job Title", "Team", "Manager", "Annual Salary", "Segment"],
     "BASE", "catalog_ops"),
]


@pytest.mark.parametrize("filename,headers,sheet,expected", DETECT_CASES)
def test_detect_format(filename, headers, sheet, expected):
    r = detect_report_format(filename, headers=headers, sheet=sheet)
    assert r["key"] == expected, f"{filename}: got {r}"


def test_kpi_definitions_detected():
    # multi-section CSV: signature tokens present across two header rows
    r = detect_report_format(
        "kpi definitions - Sheet13.csv",
        headers=["Universal KPIs", "Definitions", "Type", "Option 2"],
    )
    assert r["key"] == "kpi_definitions"
    # second section header alone should still match
    r2 = detect_report_format(
        "kpi definitions - Sheet13.csv",
        headers=["Team KPIs", "Definitions", "Type", "Option 2"],
    )
    assert r2["key"] == "kpi_definitions"


def test_document_preset_is_document():
    assert BUILTIN_REPORT_PRESETS["handover_doc"]["is_document"] is True
    assert BUILTIN_REPORT_PRESETS["handover_doc"]["fields"] == []


def test_no_match_returns_none():
    r = detect_report_format("unknown_file.csv", headers=["foo", "bar", "baz"])
    assert r["match_type"] == "none"
    assert r["key"] is None


# --- field types are valid ---------------------------------------------------
def test_all_builtin_field_types_valid():
    for key, preset in BUILTIN_REPORT_PRESETS.items():
        for f in preset["fields"]:
            assert f["type"] in FIELD_TYPES, f"{key}.{f['key']} has bad type {f['type']}"
        keys = [f["key"] for f in preset["fields"]]
        assert len(keys) == len(set(keys)), f"{key} has duplicate field keys"


def test_required_fields_present():
    # every non-document preset must identify its key columns
    for key, preset in BUILTIN_REPORT_PRESETS.items():
        if preset.get("is_document"):
            continue
        assert preset["fields"], f"{key} has no fields"
        assert any(f["required"] for f in preset["fields"]), f"{key} has no required field"


def test_currency_int_pct_coercion():
    assert report_presets._coerce("$38,619.67", {"type": "currency"}) == 38619.67
    assert report_presets._coerce("433", {"type": "int"}) == 433
    assert report_presets._coerce("100.00%", {"type": "percent"}) == 1.0
    assert report_presets._coerce("88.59%", {"type": "percent"}) == 0.8859
    assert report_presets._coerce("0.024", {"type": "percent"}) == 0.024  # already fractional
    assert report_presets._coerce("77", {"type": "percent"}) == 0.77        # bare percentage point
    assert report_presets._coerce("", {"type": "int"}) is None


# --- spine round-trip: edit + persist + reset --------------------------------
def _fresh_spine(monkeypatch, tmp_path):
    import threading
    import storage
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "conductor.db")
    storage._local = threading.local()
    storage.init_db()
    from spine.schema import init_tables
    init_tables()


def test_save_and_reset_preset(monkeypatch, tmp_path):
    _fresh_spine(monkeypatch, tmp_path)
    # edit a builtin: add a field
    body = {
        "label": "CDQ Report (edited)",
        "entity": "cdq",
        "category": "catalog_quality",
        "file": {"extensions": [".csv"], "delimiter": ",", "sheet": None,
                 "header_row": 0, "multi_section": False,
                 "header_signature": ["parent_asin", "cdq_v3_grade"]},
        "fields": [
            {"key": "parent_asin", "label": "Parent ASIN", "type": "string", "required": True},
            {"key": "cdq_score", "label": "CDQ Score", "type": "percent"},
            {"key": "my_new_field", "label": "My New Field", "type": "int"},
        ],
    }
    r = client.put("/api/report-presets/presets/cdq_report", json=body)
    assert r.status_code == 200
    assert r.json()["label"] == "CDQ Report (edited)"
    assert r.json()["builtin"] is True

    # it should now resolve with the override
    presets = client.get("/api/report-presets/presets").json()["presets"]
    edited = next(p for p in presets if p["key"] == "cdq_report")
    assert edited["label"] == "CDQ Report (edited)"
    assert any(f["key"] == "my_new_field" for f in edited["fields"])

    # reset restores the builtin
    rr = client.post("/api/report-presets/presets/cdq_report/reset")
    assert rr.status_code == 204
    presets = client.get("/api/report-presets/presets").json()["presets"]
    restored = next(p for p in presets if p["key"] == "cdq_report")
    assert restored["label"] == "CDQ Report"


def test_invalid_type_rejected(monkeypatch, tmp_path):
    _fresh_spine(monkeypatch, tmp_path)
    body = {
        "label": "Bad", "entity": "x", "category": "x",
        "file": {"extensions": [".csv"], "header_signature": []},
        "fields": [{"key": "a", "label": "A", "type": "not_a_type"}],
    }
    r = client.put("/api/report-presets/presets/bad", json=body)
    assert r.status_code == 400
    assert "not in" in r.json()["detail"]


def test_builtin_cannot_be_deleted(monkeypatch, tmp_path):
    _fresh_spine(monkeypatch, tmp_path)
    r = client.delete("/api/report-presets/presets/cdq_report")
    assert r.status_code == 400
