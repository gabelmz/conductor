"""HTTP surface for the settings store."""
from __future__ import annotations

import threading

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import storage
from backend import settings_api


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "conductor.db")
    monkeypatch.setattr(storage, "UPLOAD_DIR", tmp_path / "uploads")
    storage._local = threading.local()
    storage.init_db()
    app = FastAPI()
    app.include_router(settings_api.router)
    return TestClient(app)


def test_get_all_returns_merged_baseline(client):
    resp = client.get("/api/settings")
    assert resp.status_code == 200
    assert resp.json()["settings"]["tagPref.data"] == "all"


def test_put_get_delete_roundtrip(client):
    put = client.put("/api/settings/tagPref.data", json={"value": "keepa"})
    assert put.status_code == 200
    assert put.json() == {"key": "tagPref.data", "value": "keepa"}
    assert client.get("/api/settings/tagPref.data").json()["value"] == "keepa"
    assert client.get("/api/settings").json()["settings"]["tagPref.data"] == "keepa"
    # reset returns to baseline
    delete = client.delete("/api/settings/tagPref.data")
    assert delete.json() == {"key": "tagPref.data", "value": "all"}
    assert client.get("/api/settings/tagPref.data").json()["value"] == "all"


def test_stores_non_string_values(client):
    client.put("/api/settings/model.filters", json={"value": ["custom", "fuzzy"]})
    assert client.get("/api/settings/model.filters").json()["value"] == ["custom", "fuzzy"]
