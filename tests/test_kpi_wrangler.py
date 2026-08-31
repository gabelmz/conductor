"""Tests for KPI Studio, Employee Evaluation Scorecards, NLP Agent Conversion & DataWrangler endpoints."""
from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Ensure root & backend are on sys.path
APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))
sys.path.insert(0, str(APP_DIR / "backend"))

import storage
from kpi import init_kpi_db, kpi_router, wrangler_router


@pytest.fixture(autouse=True)
def setup_temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_conductor.db"
    monkeypatch.setattr(storage, "DB_PATH", db_file)
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    storage._local = threading.local()
    storage.init_db()
    init_kpi_db()
    yield db_file


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(kpi_router)
    app.include_router(wrangler_router)
    return TestClient(app)


def test_seed_and_list_kpis(client):
    res = client.post("/api/kpis/seed")
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True

    # List KPIs
    list_res = client.get("/api/kpis")
    assert list_res.status_code == 200
    kpis = list_res.json()
    assert isinstance(kpis, list)
    assert len(kpis) > 0


def test_create_kpi_and_entry(client):
    create_payload = {
        "department": "Catalog",
        "owner": "Gabe",
        "kpi_name": "Test SLA Rate",
        "expected_value": 95.0,
        "metric_type": "%",
        "weight": 1.0,
    }
    res = client.post("/api/kpis", json=create_payload)
    assert res.status_code == 200
    kpi_id = res.json()["id"]

    # Insert entry
    entry_payload = {
        "kpi_id": kpi_id,
        "period_date": "2026-06-01",
        "actual_value": 98.5,
    }
    entry_res = client.post("/api/kpis/entries", json=entry_payload)
    assert entry_res.status_code == 200
    assert entry_res.json()["ok"] is True

    # List to confirm
    kpis = client.get("/api/kpis?owner=Gabe").json()
    match = [k for k in kpis if k["id"] == kpi_id]
    assert len(match) == 1
    assert match[0]["latest_entry"]["actual_value"] == 98.5


def test_employee_evaluation_scorecards(client):
    client.post("/api/kpis/seed")
    res = client.get("/api/kpis/employee-evaluation")
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert "scorecards" in data
    scorecards = data["scorecards"]
    assert len(scorecards) > 0

    # Verify expected owners exist (Gabe, Alice, Carlos, Jelena, Francis)
    owners = [s["owner"] for s in scorecards]
    assert "Gabe" in owners
    assert "Alice" in owners


def test_nlp_to_kpi_conversion(client):
    # Performance report prompt
    res1 = client.post("/api/kpis/nlp-convert", json={"prompt": "Generate employee performance review for Gabe"})
    assert res1.status_code == 200
    d1 = res1.json()
    assert d1["ok"] is True
    assert "summary" in d1

    # New KPI creation prompt
    res2 = client.post(
        "/api/kpis/nlp-convert",
        json={"prompt": "Create new KPI Internal SLA target 95% for Gabe in Catalog"},
    )
    assert res2.status_code == 200
    d2 = res2.json()
    assert d2["ok"] is True
    assert d2["type"] == "kpi_created"


def test_wrangler_dataset_transform(client):
    rows = [
        {"sku": "SKU1", "val": 10},
        {"sku": "SKU2", "val": 20},
        {"sku": "SKU3", "val": 0},
    ]
    columns = ["sku", "val"]
    transformations = [
        {"kind": "filter", "column": "sku", "mode": "contains", "value": "SKU"},
        {"kind": "add_formula", "new_column": "val_doubled", "formula": "val * 2"},
    ]

    res = client.post(
        "/api/wrangler/transform",
        json={"columns": columns, "rows": rows, "transformations": transformations},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert len(data["rows"]) == 3
    assert "val_doubled" in data["columns"]
    assert data["rows"][0]["val_doubled"] == 20.0
