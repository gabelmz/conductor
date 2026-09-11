"""Tests for backend/spine_sync.py — push-only spine -> conductor.* mirror."""
from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR / "backend"))

import spine_sync
import storage
import supabase_sync
import sync_runner
from spine.default_state import seed_defaults
from spine.schema import init_tables


@pytest.fixture(autouse=True)
def setup_temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "test_conductor.db")
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    storage._local = threading.local()
    storage.init_db()
    init_tables()
    seed_defaults()
    sync_runner.init()  # (re)create sync_leases/sync_checkpoints/sync_outbox against this temp DB
    # Hermetic Supabase config — a throwaway file with dummy values, never the
    # real data/supabase.json credential (a fake session below intercepts every
    # HTTP call regardless, but this also keeps the real service-role key out
    # of this process entirely rather than merely unsent).
    monkeypatch.setattr(supabase_sync, "CONFIG_PATH", tmp_path / "supabase.json")
    supabase_sync.save_config(url="https://example.supabase.co", service_key="test-service-key")


class _FakeSession:
    def __init__(self):
        self.requests = []

    def request(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs))

        class _Resp:
            status_code = 201

            def json(self_inner):
                return []

            def raise_for_status(self_inner):
                pass

        return _Resp()


def test_push_all_sends_one_batch_per_spine_table():
    session = _FakeSession()
    result = spine_sync.push_all(session=session)
    assert result["status"] == "done"
    pushed_tables = {call[1].split("/")[-1].split("?")[0] for call in session.requests}
    assert "model_catalog" in pushed_tables
    assert "status_definitions" in pushed_tables


def test_push_all_never_sends_a_secret_ref_value():
    session = _FakeSession()
    spine_sync.push_all(session=session)
    for _method, _url, kwargs in session.requests:
        body = kwargs.get("json") or []
        for row in body:
            assert "secret_refs" not in row or row.get("secret_refs") in (None, [], "[]")


def test_push_all_uses_content_profile_header_not_a_path_segment():
    """PostgREST selects a non-public schema via the Content-Profile header
    (POST/PATCH/DELETE) or Accept-Profile (GET) — never a `/conductor/` URL
    path segment. This must match supabase_sync._request's own
    `profile_header` convention rather than inventing a second one."""
    session = _FakeSession()
    spine_sync.push_all(session=session)
    push_calls = [
        (method, url, kwargs)
        for method, url, kwargs in session.requests
        if url.rsplit("/", 1)[-1] in spine_sync.TABLES
    ]
    assert push_calls, "push_all should have pushed at least one spine table"
    for method, url, kwargs in push_calls:
        assert "/conductor/" not in url
        assert url.startswith("https://example.supabase.co/rest/v1/")
        headers = kwargs.get("headers") or {}
        assert headers.get("Content-Profile") == "conductor"


def test_push_all_skips_when_supabase_not_configured(tmp_path, monkeypatch):
    monkeypatch.setattr(supabase_sync, "CONFIG_PATH", tmp_path / "unconfigured-supabase.json")
    session = _FakeSession()
    result = spine_sync.push_all(session=session)
    assert result == {"status": "skipped", "reason": "supabase_not_configured"}
    assert session.requests == []


def test_push_all_never_leaks_the_real_service_key_into_requests():
    session = _FakeSession()
    spine_sync.push_all(session=session)
    for _method, _url, kwargs in session.requests:
        headers = kwargs.get("headers") or {}
        assert headers.get("apikey") == "test-service-key"
        assert headers.get("Authorization") == "Bearer test-service-key"
