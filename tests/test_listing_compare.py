import threading

import pytest
from fastapi.testclient import TestClient

import storage
from main import app


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "conductor.db")
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    storage._local = threading.local()
    storage.init_db()


def test_suggested_vs_live_uses_exact_levenshtein_phonetic_and_fuzzy_fields():
    client = TestClient(app)
    upload = client.post(
        "/api/listings/suggested/upload",
        files={"file": ("suggested.csv", "asin,title,feature_bullet_1,marketplace\nB000TEST01,Fresh Listing Title,Healthy natural ingredients,US\n", "text/csv")},
    )
    assert upload.status_code == 200
    source_id = upload.json()["source_id"]

    live = client.post("/api/listings/live/upsert", json={
        "source_id": "test-live", "source_kind": "test", "authority": "user_asserted",
        "record": {"asin": "B000TEST01", "marketplace": "US", "title": "Fresh Listing Title", "feature_bullet_1": "Healthy natural ingredient"},
    })
    assert live.status_code == 200

    compared = client.post("/api/listings/compare", json={"source_id": source_id, "strict_fresh": True})
    assert compared.status_code == 200
    rows = {row["field"]: row for row in compared.json()["rows"]}
    assert rows["title"]["match_status"] == "match"
    assert rows["feature_bullet_1"]["match_status"] in {"near_match", "mismatch"}
    assert rows["feature_bullet_1"]["levenshtein_similarity"] > 0.9


def test_comparison_does_not_call_stale_data_fresh():
    client = TestClient(app)
    upload = client.post("/api/listings/suggested/upload", files={"file": ("suggested.csv", "asin,title\nB000TEST02,Proposed\n", "text/csv")})
    result = client.post("/api/listings/compare", json={"source_id": upload.json()["source_id"], "strict_fresh": True})
    assert result.status_code == 200
    assert result.json()["comparison_status"] == "stale"
    assert result.json()["stale_records"] == 1
