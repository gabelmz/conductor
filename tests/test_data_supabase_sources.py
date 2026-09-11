"""Tests for backend/data.py's Supabase-backed sources (product.products,
product.suggested) — an allowlisted, read-only extension of the existing
Data Management SOURCES pattern, reusing the generic table/pivot/wrangler UI.
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest
import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR / "backend"))

import data
import storage
import supabase_sync


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "test_conductor.db")
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    storage._local = threading.local()
    storage.init_db()
    monkeypatch.setattr(supabase_sync, "CONFIG_PATH", tmp_path / "supabase.json")
    supabase_sync.save_config(url="https://example.supabase.co", service_key="test-service-key")
    app = FastAPI()
    app.include_router(data.router)
    return TestClient(app)


class _FakeResp:
    def __init__(self, json_body, headers=None, status=200):
        self._json = json_body
        self.headers = headers or {}
        self.status_code = status

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")


def test_supabase_sources_appear_in_sources_list(client, monkeypatch):
    def fake_get(url, headers=None, params=None, timeout=None):
        assert headers["Accept-Profile"] == "product"
        return _FakeResp([], headers={"content-range": "*/8656"})

    monkeypatch.setattr(requests, "get", fake_get)
    res = client.get("/api/data/sources")
    assert res.status_code == 200
    ids = {s["id"] for s in res.json()}
    assert "supabase_products" in ids
    assert "supabase_suggested" in ids
    entry = next(s for s in res.json() if s["id"] == "supabase_products")
    assert entry["count"] == 8656


def test_supabase_source_table_derives_columns_from_rows(client, monkeypatch):
    fake_rows = [{"sku": "ABC123", "vendor": "Acme", "platform": "amazon"}]

    def fake_get(url, headers=None, params=None, timeout=None):
        return _FakeResp(fake_rows)

    monkeypatch.setattr(requests, "get", fake_get)
    res = client.get("/api/data/table?source=supabase_products")
    assert res.status_code == 200
    body = res.json()
    assert body["columns"] == ["sku", "vendor", "platform"]
    assert body["rows"] == fake_rows


def test_supabase_source_search_filters_rows(client, monkeypatch):
    fake_rows = [{"sku": "ABC", "vendor": "Acme"}, {"sku": "XYZ", "vendor": "Globex"}]

    def fake_get(url, headers=None, params=None, timeout=None):
        return _FakeResp(fake_rows)

    monkeypatch.setattr(requests, "get", fake_get)
    res = client.get("/api/data/table?source=supabase_products&q=globex")
    assert res.status_code == 200
    rows = res.json()["rows"]
    assert len(rows) == 1
    assert rows[0]["vendor"] == "Globex"


def test_unconfigured_supabase_returns_empty_not_error(client, monkeypatch, tmp_path):
    monkeypatch.setattr(supabase_sync, "CONFIG_PATH", tmp_path / "unconfigured.json")
    res = client.get("/api/data/table?source=supabase_products")
    assert res.status_code == 200
    assert res.json()["rows"] == []


def test_supabase_request_failure_returns_empty_not_500(client, monkeypatch):
    def fake_get(url, headers=None, params=None, timeout=None):
        raise requests.ConnectionError("network unreachable")

    monkeypatch.setattr(requests, "get", fake_get)
    res = client.get("/api/data/table?source=supabase_products")
    assert res.status_code == 200
    assert res.json()["rows"] == []


def test_unknown_source_still_rejected(client):
    res = client.get("/api/data/table?source=not-a-real-source")
    assert res.status_code == 400


def test_asana_views_source_unwraps_payload_envelope(client, monkeypatch):
    """asana_views.* rows are {object_gid, payload: {...}, source_modified_at,
    fetched_at, synced_at} — the table view must show real task fields, not
    one opaque payload blob."""
    envelope_rows = [
        {
            "object_gid": "123456",
            "payload": {"name": "Fix the thing", "assignee": "Alice", "completed": False},
            "source_modified_at": "2026-09-10T00:00:00Z",
            "fetched_at": "2026-09-10T00:01:00Z",
            "synced_at": "2026-09-10T00:01:05Z",
        }
    ]

    def fake_get(url, headers=None, params=None, timeout=None):
        assert headers["Accept-Profile"] == "asana_views"
        return _FakeResp(envelope_rows)

    monkeypatch.setattr(requests, "get", fake_get)
    res = client.get("/api/data/table?source=supabase_asana_tasks")
    assert res.status_code == 200
    body = res.json()
    assert "payload" not in body["columns"]
    assert "name" in body["columns"]
    row = body["rows"][0]
    assert row["name"] == "Fix the thing"
    assert row["assignee"] == "Alice"
    assert row["object_gid"] == "123456"
