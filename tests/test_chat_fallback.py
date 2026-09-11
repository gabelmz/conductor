from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR / "backend"))

import chat
import providers
import storage
from spine.schema import init_tables


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "test_conductor.db")
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    storage._local = threading.local()
    storage.init_db()
    init_tables()
    monkeypatch.setattr(chat, "CONFIG_PATH", tmp_path / "chat.json")
    monkeypatch.setattr(providers, "CONFIG_PATH", tmp_path / "provider-config.json")
    monkeypatch.setattr(providers, "KEYS_PATH", tmp_path / "provider-keys.json")
    app = FastAPI()
    app.include_router(chat.router)
    return TestClient(app)


def test_outright_provider_failure_falls_back_to_configured_target(client, monkeypatch):
    from spine import preferred

    preferred.set_preferred({
        "provider": "openai", "model": "gpt-4o-mini",
        "fallback_provider": "deepseek", "fallback_model": "deepseek-chat",
    })
    providers.set_key("deepseek", "c2stZmFrZQ==", encrypted=False)

    def fake_stream(provider_id, messages, model=None, api_key=None, max_tokens=1200, temperature=0.6):
        if provider_id == "openai":
            yield {"type": "error", "code": "HTTP_401", "message": "invalid key"}
        else:
            yield {"type": "text", "text": "fallback answer"}

    monkeypatch.setattr(providers, "stream_provider", fake_stream)

    response = client.post("/api/chat", json={"message": "hi", "provider": "openai", "model": "gpt-4o-mini"})
    assert response.status_code == 200
    assert "fallback answer" in response.text
    assert "deepseek" in response.text.lower()


def test_no_retry_when_no_fallback_configured(client, monkeypatch):
    calls = []

    def fake_stream(provider_id, messages, model=None, api_key=None, max_tokens=1200, temperature=0.6):
        calls.append(provider_id)
        yield {"type": "error", "code": "HTTP_401", "message": "invalid key"}

    monkeypatch.setattr(providers, "stream_provider", fake_stream)

    response = client.post("/api/chat", json={"message": "hi", "provider": "openai", "model": "gpt-4o-mini"})
    assert "[ERROR] HTTP_401" in response.text
    assert calls == ["openai"]


def test_mid_stream_failure_is_not_retried(client, monkeypatch):
    calls = []

    def fake_stream(provider_id, messages, model=None, api_key=None, max_tokens=1200, temperature=0.6):
        calls.append(provider_id)
        yield {"type": "text", "text": "partial answer"}
        yield {"type": "error", "code": "HTTP_500", "message": "server hiccup"}

    monkeypatch.setattr(providers, "stream_provider", fake_stream)

    from spine import preferred
    preferred.set_preferred({
        "provider": "openai", "model": "gpt-4o-mini",
        "fallback_provider": "deepseek", "fallback_model": "deepseek-chat",
    })
    providers.set_key("deepseek", "c2stZmFrZQ==", encrypted=False)

    response = client.post("/api/chat", json={"message": "hi", "provider": "openai", "model": "gpt-4o-mini"})
    assert "partial answer" in response.text
    assert calls == ["openai"]  # never retried — text had already streamed
