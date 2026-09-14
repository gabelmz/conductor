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
from spine import preferred
from spine.routes import router as spine_router
from spine.schema import init_tables


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "test_conductor.db")
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    storage._local = threading.local()
    storage.init_db()
    init_tables()
    preferred.invalidate_cache()
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


def test_preferred_caching_and_invalidation(client):
    body = {"provider": "openai", "model": "gpt-4o"}
    preferred.set_preferred(body)
    assert preferred.get_preferred()["model"] == "gpt-4o"

    # Direct DB mutation without going through preferred/user_config
    conn = storage._conn()
    conn.execute(
        "UPDATE spine_configurations SET value=? WHERE config_scope='chat' AND config_key='preferred'",
        ('{"provider":"openai","model":"gpt-3.5-turbo"}',),
    )
    conn.commit()

    # Cached value should still be returned
    assert preferred.get_preferred()["model"] == "gpt-4o"

    # Explicit invalidation should force a fresh DB read
    preferred.invalidate_cache()
    assert preferred.get_preferred()["model"] == "gpt-3.5-turbo"


def test_clear_preferred(client):
    preferred.set_preferred({"provider": "openai", "model": "gpt-4o"})
    assert preferred.get_preferred()["provider"] == "openai"

    res = client.delete("/api/spine/models/preferred")
    assert res.status_code == 200
    assert res.json() == {"provider": None, "model": None, "fallback_provider": None, "fallback_model": None}

    assert preferred.get_preferred()["provider"] is None


def test_thread_safe_concurrent_caching(client):
    preferred.set_preferred({"provider": "openai", "model": "gpt-4o-mini"})
    errors = []

    def reader():
        for _ in range(50):
            try:
                p = preferred.get_preferred()
                assert p["provider"] in ("openai", "deepseek", None)
            except Exception as e:
                errors.append(e)

    def writer():
        for i in range(20):
            try:
                if i % 2 == 0:
                    preferred.set_preferred({"provider": "deepseek", "model": "deepseek-chat"})
                else:
                    preferred.clear_preferred()
            except Exception as e:
                errors.append(e)

    threads = [threading.Thread(target=reader) for _ in range(5)]
    threads.extend([threading.Thread(target=writer) for _ in range(2)])

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
