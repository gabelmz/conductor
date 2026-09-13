import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mapping import router, match_headers, _fuzzy_field_match, PRESETS_PATH

app = FastAPI()
app.include_router(router)
client = TestClient(app)


def test_fuzzy_field_match():
    key, ftype, ratio = _fuzzy_field_match("Product SKU")
    assert key == "sku"
    assert ratio >= 0.8

    key2, ftype2, ratio2 = _fuzzy_field_match("Title")
    assert key2 == "name"
    assert ratio2 >= 0.8


def test_match_and_save_preset(tmp_path, monkeypatch):
    monkeypatch.setattr("mapping.PRESETS_PATH", tmp_path / "mapping_presets.json")

    # Match unknown headers -> fuzzy match, needs_user_mapping True if low confidence
    res = client.post("/api/mapping/match", json={"headers": ["X_Custom_Col_1", "Y_Custom_Col_2"]})
    assert res.status_code == 200
    data = res.json()
    assert data["needs_user_mapping"] is True

    # Save preset
    save_res = client.post("/api/mapping/save-preset", json={
        "name": "Custom Product Preset",
        "headers": ["X_Custom_Col_1", "Y_Custom_Col_2"],
        "mappings": {
            "X_Custom_Col_1": {"mapped_field": "sku", "field_type": "string"},
            "Y_Custom_Col_2": {"mapped_field": "name", "field_type": "string"},
        }
    })
    assert save_res.status_code == 201
    assert save_res.json()["name"] == "Custom Product Preset"

    # Match again -> exact match from preset
    res2 = client.post("/api/mapping/match", json={"headers": ["Y_Custom_Col_2", "X_Custom_Col_1"]})
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["match_type"] == "exact"
    assert data2["confidence"] == 1.0
    assert data2["needs_user_mapping"] is False


def test_pending_and_known_fields():
    res = client.get("/api/mapping/known-fields")
    assert res.status_code == 200
    assert len(res.json()["fields"]) > 0

    res_pending = client.get("/api/mapping/pending")
    assert res_pending.status_code == 200
    assert "pending" in res_pending.json()
