"""Tests for Asana REST Sync auto-pull hook and Supabase push endpoints."""
from __future__ import annotations

import sys
import threading
from datetime import datetime, timedelta, timezone
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


def test_asana_auto_pull_hook_stale(client, monkeypatch):
    """Regression test: asana_auto_pull_hook must actually detect stale data.

    Prior to the datetime/timezone import fix in main.py, the staleness check
    (datetime.fromisoformat / timezone.utc) raised a NameError that was silently
    swallowed by a bare `except Exception: pass`, so `should_pull` was permanently
    stuck at False and the app could never auto-refresh after the first sync ever
    recorded. This test fails against that bug and passes once the names resolve.
    """
    monkeypatch.setattr(asana_sync, "has_credentials", lambda: True)
    monkeypatch.setattr(
        asana_sync, "sync_all",
        lambda mode="all", deep=False, progress=None: {"tasks": 0, "projects": 0},
    )
    stale_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    storage.record_asana_run(
        mode="delta",
        status="done",
        started_at=stale_time,
        finished_at=stale_time,
        counts={},
        error="",
    )

    res = client.post("/api/asana/hook/pull", json={"max_age_seconds": 60})
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["triggered"] is True
    assert data["reason"] == "stale_or_forced"
