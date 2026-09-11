from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR / "backend"))

import storage
from spine.routes import router as spine_router
from spine.schema import init_tables


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "test_conductor.db")
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    storage._local = threading.local()
    storage.init_db()
    init_tables()
    app = FastAPI()
    app.include_router(spine_router)
    return TestClient(app)


def test_preferred_defaults_to_empty_until_set(client):
    response = client.get("/api/spine/models/preferred")
    assert response.status_code == 200
    assert response.json() == {"provider": None, "model": None, "fallback_provider": None, "fallback_model": None}


def test_preferred_can_be_set_and_read_back(client):
    body = {"provider": "openai", "model": "gpt-4o-mini", "fallback_provider": "deepseek", "fallback_model": "deepseek-chat"}
    saved = client.put("/api/spine/models/preferred", json=body)
    assert saved.status_code == 200
    assert saved.json() == body

    loaded = client.get("/api/spine/models/preferred")
    assert loaded.status_code == 200
    assert loaded.json() == body


def test_preferred_rejects_unknown_provider(client):
    response = client.put("/api/spine/models/preferred", json={"provider": "not-a-real-provider", "model": "x"})
    assert response.status_code == 400
