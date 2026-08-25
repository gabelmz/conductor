from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import context_menus as menus


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(menus, "CONFIG_PATH", tmp_path / "context-menus.json")
    app = FastAPI()
    app.include_router(menus.router)
    return TestClient(app)


def replace(client: TestClient, body: dict, revision: int = 0):
    return client.put("/api/context-menus", json={"baseRevision": revision, **body})


def test_missing_file_returns_v2_override_defaults(client):
    response = client.get("/api/context-menus")
    assert response.status_code == 200
    assert response.json() == {
        "version": 2,
        "revision": 0,
        "overrides": {},
        "customActions": [],
    }
    assert not menus.CONFIG_PATH.exists()


def test_roundtrip_is_atomic_and_preserves_unknown_command_ids(client):
    body = {
        "overrides": {
            "product": {
                "plugin.future-command": {"hidden": True, "label": "Later", "order": 7}
            }
        },
        "customActions": [
            {
                "id": "open-products",
                "label": "Products",
                "surface": "product",
                "action": {"type": "navigate-view", "viewId": "products"},
                "when": {"op": "eq", "path": "target.type", "value": "product"},
            }
        ],
    }
    saved = replace(client, body)
    assert saved.status_code == 200
    assert saved.json()["revision"] == 1
    assert saved.json()["overrides"] == body["overrides"]
    assert client.get("/api/context-menus").json() == saved.json()
    assert json.loads(menus.CONFIG_PATH.read_text(encoding="utf-8")) == saved.json()
    assert not menus.CONFIG_PATH.with_suffix(".json.tmp").exists()


def test_stale_revision_conflicts_without_overwriting(client):
    first = replace(client, {"overrides": {"global": {"copy": {"hidden": True}}}})
    stale = replace(client, {"overrides": {}}, revision=0)
    assert stale.status_code == 409
    assert stale.json()["detail"]["currentRevision"] == 1
    assert client.get("/api/context-menus").json() == first.json()


def test_legacy_config_migrates_to_v2_without_writing_on_read(client):
    legacy = {
        "version": 1,
        "revision": 4,
        "surfaces": {"chat": [{"id": "copy-message", "hidden": True}]},
        "customActions": [],
    }
    menus.CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    menus.CONFIG_PATH.write_text(json.dumps(legacy), encoding="utf-8")
    loaded = client.get("/api/context-menus")
    assert loaded.status_code == 200
    assert loaded.json() == {
        "version": 2,
        "revision": 4,
        "overrides": {"chat": {"copy-message": {"hidden": True}}},
        "customActions": [],
    }
    assert json.loads(menus.CONFIG_PATH.read_text(encoding="utf-8")) == legacy


def test_reset_surface_is_scoped_and_reset_all_clears_everything(client):
    saved = replace(
        client,
        {
            "overrides": {
                "chat": {"copy": {"hidden": True}},
                "product": {"delete": {"hidden": True}},
            },
            "customActions": [
                {"id": "chat-copy", "surface": "chat", "label": "Copy", "action": {"type": "copy-template", "template": "{message.text}"}},
                {"id": "products", "surface": "product", "label": "Products", "action": {"type": "navigate-view", "viewId": "products"}},
            ],
        },
    ).json()
    scoped = client.post("/api/context-menus/reset-surface", json={"surface": "chat", "baseRevision": saved["revision"]})
    assert scoped.status_code == 200
    assert scoped.json()["overrides"] == {"product": {"delete": {"hidden": True}}}
    assert [item["id"] for item in scoped.json()["customActions"]] == ["products"]

    cleared = client.post("/api/context-menus/reset-all", json={"baseRevision": scoped.json()["revision"]})
    assert cleared.status_code == 200
    assert cleared.json()["overrides"] == {}
    assert cleared.json()["customActions"] == []


@pytest.mark.parametrize(
    "predicate",
    [
        {"op": "eval", "path": "target.type", "value": "product"},
        {"op": "eq", "path": "__proto__.admin", "value": True},
        {"op": "eq", "path": "secrets.apiKey", "value": "x"},
        {"op": "matches", "path": "target.id", "value": "("},
        {"op": "matches", "path": "target.id", "value": "x" * 257},
        {"op": "not", "args": [{"op": "not", "args": [{"op": "not", "args": [{"op": "not", "args": [{"op": "not", "args": [{"op": "not", "args": [{"op": "not", "args": [{"op": "not", "args": [{"op": "not", "args": [{"op": "not", "args": [{"op": "not", "args": [{"op": "truthy", "path": "target.id"}]}]}]}]}]}]}]}]}]}]}]},
    ],
)
def test_invalid_predicates_are_rejected(client, predicate):
    response = replace(client, {"customActions": [{"id": "bad", "label": "Bad", "surface": "global", "action": {"type": "run-command", "commandId": "copy"}, "when": predicate}]})
    assert response.status_code == 422


@pytest.mark.parametrize(
    "action",
    [
        {"type": "javascript", "code": "alert(1)"},
        {"type": "open-url", "url": "javascript:alert(1)"},
        {"type": "open-url", "url": "data:text/html,bad"},
        {"type": "open-url", "url": "file:///etc/passwd"},
        {"type": "open-url", "url": "https://user:password@example.com"},
        {"type": "same-origin-api", "path": "https://evil.example/api/x", "method": "GET"},
        {"type": "same-origin-api", "path": "/admin", "method": "GET"},
        {"type": "same-origin-api", "path": "/api/products/1", "method": "TRACE"},
        {"type": "same-origin-api", "path": "/api/products/1", "method": "DELETE"},
        {"type": "same-origin-api", "path": "/api/products", "method": "POST", "headers": {"Authorization": "secret"}},
        {"type": "run-command", "commandId": "copy", "shell": "rm -rf /"},
        {"type": "copy-template", "template": "<script>alert(1)</script>"},
    ],
)
def test_unsafe_custom_actions_are_rejected(client, action):
    response = replace(client, {"customActions": [{"id": "bad", "label": "Bad", "surface": "global", "action": action}]})
    assert response.status_code == 422


def test_allowed_custom_action_vocabulary(client):
    actions = [
        {"id": "run", "label": "Run", "surface": "global", "action": {"type": "run-command", "commandId": "plugin.unknown"}},
        {"id": "nav", "label": "Nav", "surface": "global", "action": {"type": "navigate-view", "viewId": "catalog"}},
        {"id": "copy", "label": "Copy", "surface": "global", "action": {"type": "copy-template", "template": "SKU: {target.id}"}},
        {"id": "url", "label": "Docs", "surface": "global", "action": {"type": "open-url", "url": "https://example.com/docs"}},
        {"id": "api", "label": "Refresh", "surface": "global", "action": {"type": "same-origin-api", "path": "/api/products/refresh", "method": "POST", "confirmation": "Refresh products?"}},
    ]
    response = replace(client, {"customActions": actions})
    assert response.status_code == 200
    assert response.json()["customActions"] == actions


def test_oversized_payload_is_rejected_before_persistence(client):
    response = replace(client, {"overrides": {"global": {"copy": {"label": "x" * (menus.MAX_PAYLOAD_BYTES + 1)}}}})
    assert response.status_code == 413
    assert not menus.CONFIG_PATH.exists()
