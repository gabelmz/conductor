"""Tests for asana_sync.api_post and the two main.py write endpoints that
depend on it (task creation, task comments) — previously bypassed via a
`hasattr(asana_sync, "api_post")` guard that was always False, since the
function never existed, so these calls never got api_get's 429/5xx retry.
"""
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
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "test_conductor.db")
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    storage._local = threading.local()
    storage.init_db()
    yield tmp_path


@pytest.fixture
def client():
    return TestClient(main_app)


def test_api_post_exists_and_retries_429_like_api_get(monkeypatch):
    assert hasattr(asana_sync, "api_post")

    calls = []

    class _FakeResp:
        def __init__(self, body: bytes):
            self._body = body

        def read(self):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=60):
        calls.append(req)
        if len(calls) == 1:
            import urllib.error
            raise urllib.error.HTTPError(req.full_url, 429, "rate limited", {"Retry-After": "0"}, None)
        return _FakeResp(b'{"data": {"gid": "999"}}')

    monkeypatch.setattr(asana_sync.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(asana_sync.time, "sleep", lambda *_: None)

    result = asana_sync.api_post({"Authorization": "Bearer x"}, "/tasks", {"data": {"name": "hi"}})

    assert result == {"data": {"gid": "999"}}
    assert len(calls) == 2  # retried once after the 429


def test_asana_create_task_uses_api_post(client, monkeypatch):
    monkeypatch.setattr(asana_sync, "has_credentials", lambda: True)
    monkeypatch.setattr(asana_sync, "_headers", lambda: {"Authorization": "Bearer x"})

    seen = {}

    def fake_api_post(headers, path, body):
        seen["headers"] = headers
        seen["path"] = path
        seen["body"] = body
        return {"data": {"gid": "123"}}

    monkeypatch.setattr(asana_sync, "api_post", fake_api_post)

    res = client.post("/api/asana/tasks/create", json={"data": {"name": "New task"}})
    assert res.status_code == 200
    assert res.json() == {"data": {"gid": "123"}}
    assert seen["path"] == "/tasks"
    assert seen["body"] == {"data": {"name": "New task"}}


def test_asana_add_comment_uses_api_post(client, monkeypatch):
    monkeypatch.setattr(asana_sync, "has_credentials", lambda: True)
    monkeypatch.setattr(asana_sync, "_headers", lambda: {"Authorization": "Bearer x"})

    seen = {}

    def fake_api_post(headers, path, body):
        seen["path"] = path
        seen["body"] = body
        return {"data": {"gid": "story-1"}}

    monkeypatch.setattr(asana_sync, "api_post", fake_api_post)

    res = client.post("/api/asana/tasks/task-1/comments", json={"text": "hello"})
    assert res.status_code == 200
    assert seen["path"] == "/tasks/task-1/stories"
    assert seen["body"] == {"data": {"text": "hello"}}
