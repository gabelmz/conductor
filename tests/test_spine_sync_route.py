"""GET/POST /api/spine/sync/push — the manual trigger for backend/spine_sync.py's
push_all(), mounted on the spine router so it's reachable, not just importable."""
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
import supabase_sync
from spine.routes import router as spine_router
from spine.schema import init_tables


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "test_conductor.db")
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    storage._local = threading.local()
    storage.init_db()
    init_tables()
    monkeypatch.setattr(supabase_sync, "CONFIG_PATH", tmp_path / "supabase.json")
    app = FastAPI()
    app.include_router(spine_router)
    return TestClient(app)


def test_sync_push_skips_cleanly_when_supabase_not_configured(client):
    response = client.post("/api/spine/sync/push")
    assert response.status_code == 200
    assert response.json() == {"status": "skipped", "reason": "supabase_not_configured"}


def test_sync_push_calls_spine_sync_push_all_when_configured(client, monkeypatch):
    supabase_sync.save_config(url="https://example.supabase.co", service_key="test-service-key")

    import spine_sync

    called = {}

    def fake_push_all(session=None):
        called["ran"] = True
        return {"status": "done", "entity": "spine", "rows": 0, "errors": []}

    monkeypatch.setattr(spine_sync, "push_all", fake_push_all)

    response = client.post("/api/spine/sync/push")
    assert response.status_code == 200
    assert response.json()["status"] == "done"
    assert called == {"ran": True}
