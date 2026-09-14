"""Tests for Unified Cross-Channel Search Engine (backend/search.py)."""
import threading
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import storage
import search
from search import router as search_router


@pytest.fixture(autouse=True)
def setup_test_db(tmp_path, monkeypatch):
    """Setup isolated test database."""
    storage._local = threading.local()
    test_data_dir = tmp_path / "data"
    test_data_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(storage, "DATA_DIR", test_data_dir)
    monkeypatch.setattr(storage, "DB_PATH", test_data_dir / "conductor.db")

    storage.init_db()

    # Seed sample products
    storage.create_product(
        sku="TEST-SKU-001",
        name="Acme Vitamin Supplement",
        category="Supplements",
        market="US",
        source="test",
    )


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(search_router)
    return TestClient(app)


def test_global_search(client):
    """Test cross-channel search endpoint."""
    resp = client.get("/api/search/global?q=Vitamin")
    assert resp.status_code == 200
    data = resp.json()

    assert data["query"] == "Vitamin"
    assert "results_by_channel" in data
    assert "catalog" in data["results_by_channel"]
    assert "gap_analysis" in data

    # Verify catalog result returned
    catalog_results = data["results_by_channel"]["catalog"]
    assert len(catalog_results) >= 1
    assert catalog_results[0]["sku"] == "TEST-SKU-001"


def test_gap_analysis(client):
    """Test channel gap analysis calculation."""
    sample_flat = [
        {"sku": "SKU-A", "channel": "catalog"},
        {"sku": "SKU-A", "channel": "keepa"},
        {"sku": "SKU-B", "channel": "asana"},
    ]
    analysis = search.compute_gap_analysis(sample_flat)
    assert analysis["total_unique_keys"] == 2
    assert analysis["items_with_gaps"] == 2
    assert len(analysis["channel_matrix"]) == 2
