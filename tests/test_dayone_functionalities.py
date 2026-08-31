"""Tests for Day One primary workflows and features: Brand Onboarding, Keepa Search & AI Query, Compliance, and Asana Performance Hub."""
from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))
sys.path.insert(0, str(APP_DIR / "backend"))

import storage
from brand_onboarding import onboarding_router
from keepa import router as keepa_router
from kpi import kpi_router


@pytest.fixture(autouse=True)
def setup_temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_conductor.db"
    monkeypatch.setattr(storage, "DB_PATH", db_file)
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    storage._local = threading.local()
    storage.init_db()
    yield db_file


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(onboarding_router)
    app.include_router(keepa_router)
    app.include_router(kpi_router)
    return TestClient(app)


def test_brand_onboarding_workflow(client):
    res = client.post("/api/workflows/onboard-brand", json={"brand": "Luminize", "seller_id": "A1234"})
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["brand"] == "Luminize"
    assert "forecasted_cost" in data
    assert data["forecasted_cost"]["day_30"] > 0
    assert len(data["preview_tasks"]) > 0


def test_keepa_brand_search_and_ai_query(client):
    # Search
    s_res = client.post("/api/keepa/search", json={"query": "Luminize", "type": "brand", "domain": 1})
    assert s_res.status_code == 200
    s_data = s_res.json()
    assert s_data["ok"] is True

    # AI Query Writer
    q_res = client.post("/api/keepa/ai-query", json={"prompt": "Find top rank electronics for seller A1234 under $50"})
    assert q_res.status_code == 200
    q_data = q_res.json()
    assert q_data["ok"] is True
    assert "summary" in q_data
