from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR / "backend"))

import chat
import providers


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(chat, "CONFIG_PATH", tmp_path / "chat.json")
    monkeypatch.setattr(providers, "CONFIG_PATH", tmp_path / "provider-config.json")
    monkeypatch.setattr(providers, "KEYS_PATH", tmp_path / "provider-keys.json")
    app = FastAPI()
    app.include_router(chat.router)
    return TestClient(app)


def test_models_are_scoped_to_requested_provider(client):
    response = client.get("/api/chat/models?provider=openai")
    assert response.status_code == 200
    payload = response.json()
    assert payload["providerId"] == "openai"
    assert payload["models"]
    assert {model["providerId"] for model in payload["models"]} == {"openai"}


def test_provider_change_revalidates_known_cross_provider_model(client):
    first = client.post("/api/chat/config", json={"provider": "openai", "model": "gpt-4o-mini"})
    assert first.status_code == 200
    switched = client.post("/api/chat/config", json={"provider": "mistral"})
    assert switched.status_code == 200
    assert switched.json()["model"] == providers.HOSTED_PROVIDERS["mistral"]["default_model"]


def test_chat_rejects_known_cross_provider_model_before_request(client):
    response = client.post("/api/chat", json={
        "message": "hello",
        "provider": "mistral",
        "model": providers.HOSTED_PROVIDERS["openai"]["default_model"],
    })
    assert response.status_code == 400
    assert "not available" in response.json()["detail"]
