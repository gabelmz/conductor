"""Tests for Dataset Store and Local DB Backup Manager (backend/dataset_store.py)."""
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import json
import threading
from datetime import datetime, timezone, timedelta
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import storage
import dataset_store
from dataset_store import router as dataset_store_router


@pytest.fixture(autouse=True)
def setup_test_db(tmp_path, monkeypatch):
    """Setup isolated test database and local-store directory."""
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


def test_init_and_summary(client):
    """Test folder initialization and summary endpoint."""
    resp = client.get("/api/dataset-store/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert "domains" in data
    assert "catalog_products" in data["domains"]
    assert "reports" in data["domains"]
    assert "states" in data
    assert data["states"] == ["raw", "staging", "intermediary", "views"]


def test_backup_local_db(client):
    """Test manual backup creation."""
    resp = client.post("/api/dataset-store/backup", json={"note": "test_backup"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "success"
    assert "backup_id" in data
    assert data["db_backup"].startswith("conductor_")

    # List backups
    list_resp = client.get("/api/dataset-store/backups")
    assert list_resp.status_code == 200
    backups = list_resp.json()["backups"]
    assert len(backups) == 1
    assert backups[0]["backup_id"] == data["backup_id"]


def test_register_and_promote_dataset(client):
    """Test uploading/registering a dataset and promoting it through lifecycle states."""
    content = b"sku,name,brand\nSKU001,Widget A,BrandX\nSKU002,Widget B,BrandY\n"
    files = {"file": ("catalog_sample.csv", content, "text/csv")}
    form_data = {
        "domain": "catalog_products",
        "state": "raw",
        "metadata": json.dumps({"source": "Catalog Ingest"}),
    }

    reg_resp = client.post("/api/dataset-store/datasets/register", files=files, data=form_data)
    assert reg_resp.status_code == 201
    reg_data = reg_resp.json()
    assert reg_data["domain"] == "catalog_products"
    assert reg_data["state"] == "raw"
    dataset_id = reg_data["dataset_id"]

    # Promote from raw to staging
    promote_resp = client.post(
        "/api/dataset-store/datasets/promote",
        json={"dataset_id": dataset_id, "target_state": "staging"},
    )
    assert promote_resp.status_code == 200
    promoted = promote_resp.json()
    assert promoted["state"] == "staging"
    assert promoted["new_dataset_id"] == f"staging_catalog_products_catalog_sample.csv"

    # List datasets
    list_resp = client.get("/api/dataset-store/datasets")
    assert list_resp.status_code == 200
    datasets = list_resp.json()["datasets"]
    assert len(datasets) == 2


def test_page_views_cache(client):
    """Test getting and updating cached page views."""
    get_resp = client.get("/api/dataset-store/views/dashboard")
    assert get_resp.status_code == 200
    d_data = get_resp.json()
    assert d_data["page_id"] == "dashboard"

    # Update dashboard view
    new_view = {"data": {"active_users": 5, "system_health": "100%"}}
    post_resp = client.post("/api/dataset-store/views/dashboard", json=new_view)
    assert post_resp.status_code == 200

    # Get updated view
    get_resp2 = client.get("/api/dataset-store/views/dashboard")
    assert get_resp2.status_code == 200
    assert get_resp2.json()["data"]["active_users"] == 5


def test_refresh_all_views(client):
    """Test refreshing views for all pages."""
    resp = client.post("/api/dataset-store/views/refresh-all")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert len(data["refreshed_pages"]) == 10


def test_configurable_domains_and_pages_env(client, monkeypatch):
    """Test domain and page lists configured via environment variables."""
    monkeypatch.setenv("DATASET_STORE_DOMAINS", "custom_dom_a, custom_dom_b")
    monkeypatch.setenv("DATASET_STORE_PAGES", "custom_page_a, custom_page_b")

    dataset_store.init_dataset_store()

    assert "custom_dom_a" in dataset_store.DOMAINS
    assert "custom_dom_b" in dataset_store.DOMAINS
    assert "custom_page_a" in dataset_store.PAGES
    assert "custom_page_b" in dataset_store.PAGES

    summary = client.get("/api/dataset-store/summary").json()
    assert "custom_dom_a" in summary["domains"]
    assert "custom_page_a" in summary["pages"]

    # Reset environment and reload defaults
    monkeypatch.delenv("DATASET_STORE_DOMAINS", raising=False)
    monkeypatch.delenv("DATASET_STORE_PAGES", raising=False)
    dataset_store.reload_config_from_env(force=True)


def test_dynamic_registration_domains_and_pages(client):
    """Test dynamic registration of domains and pages."""
    # Direct function registration
    doms = dataset_store.register_domain("dynamic_dom_1")
    assert "dynamic_dom_1" in doms
    assert (dataset_store.RAW_DIR / "dynamic_dom_1").exists()

    # API registration of domain
    resp_dom = client.post("/api/dataset-store/domains/register", json={"domain": "dynamic_dom_2"})
    assert resp_dom.status_code == 200
    assert "dynamic_dom_2" in resp_dom.json()["domains"]

    # Direct function page registration
    pages = dataset_store.register_page("dynamic_page_1")
    assert "dynamic_page_1" in pages
    assert (dataset_store.PAGE_VIEWS_DIR / "dynamic_page_1.json").exists()

    # API registration of page
    resp_pg = client.post("/api/dataset-store/pages/register", json={"page": "dynamic_page_2"})
    assert resp_pg.status_code == 200
    assert "dynamic_page_2" in resp_pg.json()["pages"]

    # Verify registered page view is accessible
    pv = client.get("/api/dataset-store/views/dynamic_page_2")
    assert pv.status_code == 200
    assert pv.json()["page_id"] == "dynamic_page_2"


def test_prune_backups_count(client):
    """Test pruning backups by max retention count limit."""
    # Create 12 backups
    for i in range(12):
        dataset_store.backup_local_db(note=f"test_backup_{i}")

    # Prior to prune, limit 10 was applied during backup, so 10 exist
    backups_before = dataset_store.list_backups()
    assert len(backups_before) == 10

    # Explicitly prune down to 4
    result = dataset_store.prune_backups(max_backups=4, max_age_days=30)
    assert result["status"] == "success"
    assert result["pruned_count"] == 6
    assert result["remaining_backups"] == 4

    backups_after = dataset_store.list_backups()
    assert len(backups_after) == 4


def test_prune_backups_age(client):
    """Test pruning backups exceeding max age in days."""
    b1 = dataset_store.backup_local_db(note="old_backup")
    b2 = dataset_store.backup_local_db(note="recent_backup")

    # Manually backdate the old backup record to 45 days ago
    conn = storage._conn()
    old_date = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
    conn.execute("UPDATE local_store_backups SET created_at=? WHERE backup_id=?", (old_date, b1["backup_id"]))
    conn.commit()

    # Prune with max_age_days=30
    result = dataset_store.prune_backups(max_backups=100, max_age_days=30)
    assert result["status"] == "success"
    assert result["pruned_count"] >= 1
    pruned_ids = [b["backup_id"] for b in result["pruned_backups"]]
    assert b1["backup_id"] in pruned_ids

    # Confirm remaining backups
    remaining = dataset_store.list_backups()
    rem_ids = [b["backup_id"] for b in remaining]
    assert b1["backup_id"] not in rem_ids
    assert b2["backup_id"] in rem_ids


def test_prune_backups_api_endpoint(client):
    """Test POST /api/dataset-store/prune endpoint."""
    for i in range(5):
        dataset_store.backup_local_db(note=f"api_prune_test_{i}")

    resp = client.post("/api/dataset-store/prune", json={"max_backups": 2, "max_age_days": 30})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["remaining_backups"] == 2
    assert len(dataset_store.list_backups()) == 2
