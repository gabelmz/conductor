from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR / "backend"))

import storage
from main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    # Isolated from the real data/conductor.db — this file previously wrote
    # directly to it via the shared `main.app` instance (no fixture at all),
    # so every local test run silently bumped a real spine_configurations row
    # (scope='chat', key='default') and, once backend/spine_sync.py existed,
    # pushed that test artifact into the live conductor.* Supabase mirror too.
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "test_conductor.db")
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    storage._local = threading.local()
    storage.init_db()
    from spine.schema import init_tables
    from spine.default_state import seed_defaults
    init_tables()
    seed_defaults()
    return TestClient(app)


def test_spine_snapshot_exposes_local_first_catalog(client):
    response = client.get("/api/spine/snapshot")
    assert response.status_code == 200
    snapshot = response.json()

    assert len(snapshot["registry"]) >= 8
    assert len(snapshot["models"]) >= 20
    assert {node["node_type"] for node in snapshot["nodes"]} >= {
        "trigger", "http", "ai", "sheet", "drive", "flush"
    }
    assert {dataset["dataset_key"] for dataset in snapshot["datasets"]} >= {
        "catalog_products", "keepa_products", "asana_tasks", "suggested_content", "live_listing_content"
    }


def test_spine_configuration_never_requires_a_secret_value(client):
    body = {"value": {"default_model_preset": "openai-default"}, "secret_refs": ["provider-key:openai"]}
    saved = client.put("/api/spine/config/chat/default", json=body)
    assert saved.status_code == 200

    loaded = client.get("/api/spine/config/chat/default")
    assert loaded.status_code == 200
    assert loaded.json()["value"] == body["value"]
    assert loaded.json()["secret_refs"] == body["secret_refs"]


def test_spine_glossary_filters_local_registry(client):
    response = client.get("/api/spine/glossary", params={"q": "Keepa", "kind": "feature"})
    assert response.status_code == 200
    assert response.json()["count"] >= 1


def test_sqlite_pragmas_applied():
    conn = storage._conn()
    journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    synchronous = conn.execute("PRAGMA synchronous").fetchone()[0]
    busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
    foreign_keys = conn.execute("PRAGMA foreign_keys").fetchone()[0]

    assert str(journal_mode).lower() == "wal"
    assert synchronous == 1  # 1 corresponds to NORMAL in SQLite
    assert busy_timeout == 5000
    assert foreign_keys == 1  # 1 corresponds to ON in SQLite
