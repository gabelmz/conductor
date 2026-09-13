"""Regressions for four latent bugs that had no coverage.

Each shipped broken because nothing exercised the path:
  - flatfiles used `re` without importing it (NameError on markdown upload)
  - supabase_sync / usage ignored CONDUCTOR_DATA_DIR, writing into the app
    bundle in packaged builds, so credentials were lost on every update
  - automation._asana_client read a config key get_config() never returns,
    which made every live Asana automation action silently dead code
"""
from __future__ import annotations

import importlib
import sys
import threading
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

MARKDOWN_TEMPLATE = "| Item Name | SKU |\n| --- | --- |\n| Example Widget | EX-1 |\n"


@pytest.fixture()
def flatfiles_client(tmp_path, monkeypatch):
    import storage
    from backend import flatfiles

    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "conductor.db")
    monkeypatch.setattr(storage, "UPLOAD_DIR", tmp_path / "uploads")
    storage._local = threading.local()
    storage.init_db()
    app = FastAPI()
    app.include_router(flatfiles.router)
    return TestClient(app)


def test_flatfiles_markdown_upload_does_not_raise_nameerror(flatfiles_client):
    """The .md branch calls re.match() but `re` was never imported, so every
    markdown template upload died with NameError. Only CSV/TSV were covered."""
    resp = flatfiles_client.post(
        "/api/flatfiles/upload",
        files={"file": ("beauty-us.md", MARKDOWN_TEMPLATE, "text/markdown")},
    )
    assert resp.status_code == 201, resp.text
    cols = resp.json()["columns"]
    assert [c["label"] for c in cols] == ["Item Name", "SKU"]
    # the |---| separator row must be filtered out by the re.match guard
    assert all("---" not in c["label"] for c in cols)


def test_supabase_sync_honors_conductor_data_dir(tmp_path, monkeypatch):
    """Packaged builds set CONDUCTOR_DATA_DIR; creds must land there, not in
    the read-only app bundle."""
    monkeypatch.setenv("CONDUCTOR_DATA_DIR", str(tmp_path))
    import supabase_sync

    importlib.reload(supabase_sync)
    try:
        assert supabase_sync.CONFIG_PATH == tmp_path / "supabase.json"
    finally:
        monkeypatch.delenv("CONDUCTOR_DATA_DIR", raising=False)
        importlib.reload(supabase_sync)


def test_usage_honors_conductor_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CONDUCTOR_DATA_DIR", str(tmp_path))
    import usage

    importlib.reload(usage)
    try:
        assert usage.USAGE_PATH == tmp_path / "usage.json"
    finally:
        monkeypatch.delenv("CONDUCTOR_DATA_DIR", raising=False)
        importlib.reload(usage)


def test_asana_client_returns_headers_when_pats_configured(monkeypatch):
    """get_config() exposes has_pat/pat_masked but never `pat`, so the old
    implementation always returned (None, None)."""
    import asana_sync
    import automation

    monkeypatch.setattr(asana_sync, "has_credentials", lambda: True)
    monkeypatch.setattr(asana_sync, "_load_config", lambda: {"pats": ["tok-abc"]})
    monkeypatch.setattr(asana_sync, "_last_use", [])

    headers, base = automation._asana_client()
    assert headers is not None, "live Asana actions must not be dead code"
    assert headers["Authorization"] == "Bearer tok-abc"
    assert base == asana_sync.BASE_URL


def test_asana_client_returns_none_without_credentials(monkeypatch):
    import asana_sync
    import automation

    monkeypatch.setattr(asana_sync, "has_credentials", lambda: False)
    assert automation._asana_client() == (None, None)
