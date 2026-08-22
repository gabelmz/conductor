from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from backend import supabase_sync


@dataclass
class FakeResponse:
    status_code: int = 200
    payload: object = None
    headers: dict | None = None
    text: str = ""

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise supabase_sync.requests.HTTPError(
                f"{self.status_code}: {self.text}", response=self
            )


class FakeSession:
    def __init__(self, responses=()):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if not self.responses:
            raise AssertionError(f"Unexpected request: {method} {url}")
        return self.responses.pop(0)


def test_config_is_persisted_and_status_redacts_service_key(tmp_path, monkeypatch):
    path = tmp_path / "supabase.json"
    monkeypatch.setattr(supabase_sync, "CONFIG_PATH", path)

    status = supabase_sync.save_config(
        url="https://demo.supabase.co/", service_key="super-secret"
    )

    assert json.loads(path.read_text(encoding="utf-8")) == {
        "url": "https://demo.supabase.co",
        "service_key": "super-secret",
        "schema": "public",
    }
    assert status == {
        "configured": True,
        "url": "https://demo.supabase.co",
        "has_service_key": True,
        "service_key_masked": "****cret",
        "schema": "public",
    }
    assert "super-secret" not in repr(status)


def test_connection_uses_postgrest_and_never_returns_secret(tmp_path, monkeypatch):
    monkeypatch.setattr(supabase_sync, "CONFIG_PATH", tmp_path / "supabase.json")
    supabase_sync.save_config(url="https://demo.supabase.co", service_key="super-secret")
    session = FakeSession([FakeResponse(payload=[])])

    result = supabase_sync.test_connection(session=session)

    assert result == {"ok": True, "message": "Connected to Supabase"}
    method, url, kwargs = session.calls[0]
    assert (method, url) == (
        "GET",
        "https://demo.supabase.co/rest/v1/conductor_records",
    )
    assert kwargs["params"] == {"select": "entity_type", "limit": 1}
    assert kwargs["headers"]["apikey"] == "super-secret"
    assert "super-secret" not in repr(result)


def test_push_upserts_products_and_asana_tasks_idempotently(tmp_path, monkeypatch):
    monkeypatch.setattr(supabase_sync, "CONFIG_PATH", tmp_path / "supabase.json")
    supabase_sync.save_config(url="https://demo.supabase.co", service_key="secret")
    product = {
        "sku": "SKU-1",
        "name": "Widget",
        "updated_at": "2026-08-20T10:00:00Z",
    }
    task = {
        "gid": "123",
        "name": "Review Widget",
        "modified_at": "2026-08-20T11:00:00Z",
    }
    adapters = {
        "products": supabase_sync.LocalAdapter(
            list_records=lambda: [product],
            upsert_record=lambda _record: None,
            key_field="sku",
            updated_field="updated_at",
        ),
        "asana_tasks": supabase_sync.LocalAdapter(
            list_records=lambda: [task],
            upsert_record=lambda _record: None,
            key_field="gid",
            updated_field="modified_at",
        ),
    }
    session = FakeSession([FakeResponse(payload=[])] * 4)

    result = supabase_sync.sync(
        direction="push", adapters=adapters, session=session
    )

    assert result["status"] == "done"
    assert result["counts"] == {"pushed": 2, "pulled": 0, "skipped": 0}
    record_calls = [call for call in session.calls if call[1].endswith("conductor_records")]
    assert len(record_calls) == 2
    for _, _, kwargs in record_calls:
        assert kwargs["params"] == {
            "on_conflict": "entity_type,record_key"
        }
        assert kwargs["headers"]["Prefer"] == "resolution=merge-duplicates,return=minimal"
    assert record_calls[0][2]["json"] == [{
        "entity_type": "products",
        "record_key": "SKU-1",
        "payload": product,
        "source_updated_at": "2026-08-20T10:00:00Z",
    }]
    assert record_calls[1][2]["json"][0]["record_key"] == "123"


def test_pull_applies_remote_payloads_through_local_adapter(tmp_path, monkeypatch):
    monkeypatch.setattr(supabase_sync, "CONFIG_PATH", tmp_path / "supabase.json")
    supabase_sync.save_config(url="https://demo.supabase.co", service_key="secret")
    applied = []
    adapter = supabase_sync.LocalAdapter(
        list_records=lambda: [],
        upsert_record=applied.append,
        key_field="sku",
        updated_field="updated_at",
    )
    session = FakeSession([
        FakeResponse(payload=[]),
        FakeResponse(payload=[{"record_key": "SKU-1", "payload": {"sku": "SKU-1", "name": "Remote"}}]),
        FakeResponse(payload=[]),
    ])

    result = supabase_sync.sync(direction="pull", adapters={"products": adapter}, session=session)

    assert result["counts"] == {"pushed": 0, "pulled": 1, "skipped": 0}
    assert applied == [{"sku": "SKU-1", "name": "Remote"}]
    assert session.calls[1][2]["params"]["entity_type"] == "eq.products"


def test_bidirectional_pulls_then_pushes(tmp_path, monkeypatch):
    monkeypatch.setattr(supabase_sync, "CONFIG_PATH", tmp_path / "supabase.json")
    supabase_sync.save_config(url="https://demo.supabase.co", service_key="secret")
    local = [{"sku": "SKU-1", "name": "Local"}]
    applied = []
    adapter = supabase_sync.LocalAdapter(lambda: local, applied.append, "sku")
    session = FakeSession([
        FakeResponse(payload=[]),
        FakeResponse(payload=[]),
        FakeResponse(payload=[]),
        FakeResponse(payload=[]),
    ])

    result = supabase_sync.sync(direction="bidirectional", adapters={"products": adapter}, session=session)

    assert result["counts"] == {"pushed": 1, "pulled": 0, "skipped": 0}
    assert any(call[0] == "GET" and call[1].endswith("conductor_records") for call in session.calls)
    assert any(call[0] == "POST" and call[1].endswith("conductor_records") for call in session.calls)


def test_pull_newest_skips_remote_record_when_local_is_newer(tmp_path, monkeypatch):
    monkeypatch.setattr(supabase_sync, "CONFIG_PATH", tmp_path / "supabase.json")
    supabase_sync.save_config(url="https://demo.supabase.co", service_key="secret")
    local = [{"sku": "SKU-1", "name": "Local", "updated_at": "2026-08-21T12:00:00Z"}]
    applied = []
    adapter = supabase_sync.LocalAdapter(lambda: local, applied.append, "sku", "updated_at")
    session = FakeSession([
        FakeResponse(payload=[]),
        FakeResponse(payload=[{
            "record_key": "SKU-1",
            "source_updated_at": "2026-08-20T12:00:00Z",
            "payload": {"sku": "SKU-1", "name": "Remote", "updated_at": "2026-08-20T12:00:00Z"},
        }]),
        FakeResponse(payload=[]),
    ])

    result = supabase_sync.sync(direction="pull", adapters={"products": adapter}, conflict="newest", session=session)

    assert result["counts"] == {"pushed": 0, "pulled": 0, "skipped": 1}
    assert applied == []
