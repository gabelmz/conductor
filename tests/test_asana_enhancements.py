"""Tests for Asana REST Sync auto-pull hook and Supabase push endpoints."""
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

import asana_sync
import storage
from main import app as main_app


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
    return TestClient(main_app)


def test_asana_auto_pull_hook_no_creds(client, monkeypatch):
    monkeypatch.setattr(asana_sync, "has_credentials", lambda: False)
    res = client.post("/api/asana/hook/pull")
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is False
    assert data["triggered"] is False
    assert "No PAT" in data["reason"]


def test_asana_auto_pull_hook_fresh(client, monkeypatch):
    monkeypatch.setattr(asana_sync, "has_credentials", lambda: True)
    storage.record_asana_run(
        mode="delta",
        status="done",
        started_at=storage.now_iso(),
        finished_at=storage.now_iso(),
        counts={},
        error="",
    )

    res = client.post("/api/asana/hook/pull", json={"max_age_seconds": 900})
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["triggered"] is False
    assert data["reason"] == "fresh"
