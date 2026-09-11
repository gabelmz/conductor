from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR / "backend"))

import reports
import storage


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "conductor.db")
    storage._local = threading.local()
    storage.init_db()
    app = FastAPI()
    app.include_router(reports.router)
    return TestClient(app)


def test_report_envelope_filters_and_lineage(client):
    first = client.post("/api/reports/generate", json={
        "kind": "cdq",
        "parameters": {"latestOnly": False, "sourceId": "sqlite", "ignored": "not persisted"},
    })
    assert first.status_code == 200
    report = first.json()["report"]
    assert report["schemaVersion"] == 1
    assert report["type"] == "cdq"
    assert report["source"]["system"] == "sqlite"
    assert report["parameters"] == {"latestOnly": False, "sourceId": "sqlite"}
    assert report["kind"] == "cdq"  # legacy field remains available

    rerun = client.post(f"/api/reports/{report['id']}/rerun", json={"parameters": {"dataType": "catalog"}})
    assert rerun.status_code == 200
    rerun_report = rerun.json()["report"]
    assert rerun_report["meta"]["rerun_of"] == report["id"]
    assert rerun_report["parameters"]["dataType"] == "catalog"

    latest = client.get("/api/reports?kind=cdq&source=live&latest_only=true")
    assert latest.status_code == 200
    assert [item["id"] for item in latest.json()["reports"]] == [rerun_report["id"]]

    replaced = client.post(f"/api/reports/{rerun_report['id']}/replace", json={})
    assert replaced.status_code == 200
    old = client.get(f"/api/reports/{rerun_report['id']}").json()["report"]
    assert old["meta"]["replaced_by"] == replaced.json()["report"]["id"]


def test_report_rejects_inverted_date_range(client):
    response = client.post("/api/reports/generate", json={
        "parameters": {"dateFrom": "2026-09-11", "dateTo": "2026-09-10"},
    })
    assert response.status_code == 400
    assert "cannot be after" in response.json()["detail"]

    malformed = client.post("/api/reports/generate", json={"parameters": ["not", "an", "object"]})
    assert malformed.status_code == 400
    assert "must be an object" in malformed.json()["detail"]
