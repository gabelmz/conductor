"""Tests for dataset store WAL checkpoint, pipeline, and diffing features."""
import json
import threading
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import storage
import dataset_store
from dataset_store import router as dataset_store_router


@pytest.fixture(autouse=True)
def setup_test_db(tmp_path, monkeypatch):
    storage._local = threading.local()
    test_data_dir = tmp_path / "data"
    test_data_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(storage, "DATA_DIR", test_data_dir)
    monkeypatch.setattr(storage, "DB_PATH", test_data_dir / "conductor.db")
    monkeypatch.setattr(dataset_store, "DATA_DIR", test_data_dir)
    monkeypatch.setattr(dataset_store, "LOCAL_STORE_DIR", test_data_dir / "local-store")
    monkeypatch.setattr(dataset_store, "BACKUPS_DIR", test_data_dir / "local-store" / "backups")
    monkeypatch.setattr(dataset_store, "RAW_DIR", test_data_dir / "local-store" / "raw")
    monkeypatch.setattr(dataset_store, "STAGING_DIR", test_data_dir / "local-store" / "staging")
    monkeypatch.setattr(dataset_store, "INTERMEDIARY_DIR", test_data_dir / "local-store" / "intermediary")
    monkeypatch.setattr(dataset_store, "VIEWS_DIR", test_data_dir / "local-store" / "views")
    monkeypatch.setattr(dataset_store, "STATES_DIR", test_data_dir / "local-store" / "states")
    monkeypatch.setattr(dataset_store, "PAGE_VIEWS_DIR", test_data_dir / "local-store" / "views" / "pages")

    storage.init_db()
    dataset_store.init_dataset_store()


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(dataset_store_router)
    return TestClient(app)


def test_wal_checkpoint(client):
    """Test WAL checkpoint endpoint."""
    resp = client.post("/api/dataset-store/wal-checkpoint", json={"mode": "PASSIVE"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["mode"] == "PASSIVE"


def test_pipeline_and_diff(client):
    """Test dropping raw file, running pipeline scan, and diffing states."""
    # Place raw file in raw/reports
    raw_dir = dataset_store.RAW_DIR / "reports"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_file = raw_dir / "sample_report.csv"
    raw_file.write_text("sku,name,price\nSKU100,Widget 100,19.99\nSKU200,Widget 200,29.99\n", encoding="utf-8")

    # Trigger pipeline run
    pipe_resp = client.post("/api/dataset-store/pipeline/run")
    assert pipe_resp.status_code == 200
    pipe_data = pipe_resp.json()
    assert pipe_data["status"] == "complete"
    assert pipe_data["processed_count"] >= 1

    # Verify staging copy created
    staging_file = dataset_store.STAGING_DIR / "reports" / "sample_report.csv"
    assert staging_file.exists()

    # Diff raw vs staging
    diff_resp = client.post("/api/dataset-store/diff", json={
        "raw_dataset_id": "raw_reports_sample_report.csv",
        "staging_dataset_id": "staging_reports_sample_report.csv",
        "db_table": "products",
    })
    assert diff_resp.status_code == 200
    diff_data = diff_resp.json()
    assert diff_data["counts"]["raw_records"] == 2
    assert diff_data["counts"]["staging_records"] == 2
    assert diff_data["headers"]["raw"] == ["sku", "name", "price"]
