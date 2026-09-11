"""Local model search/discovery (backend/llama.py + backend/chat.py).

backend/llama.py's discover_models() already scans every known local GGUF
install (Conductor's own models/, Ollama, LM Studio, Jan/Atomic Chat) — but
until now two things were broken:

  1. backend/chat.py's GET /api/chat/models and GET /api/chat/config never
     called discover_models() at all, only the much narrower list_models()
     (Conductor's own models/ folder only) — so anything installed via
     Ollama/LM Studio/Jan was invisible to those endpoints.
  2. Even where the Settings UI already called GET /api/llama/discover
     directly and offered those models by id, llama.resolve_model() only
     ever searched MODELS_DIR — so picking a discovered-elsewhere model
     404'd the moment you tried to actually use it.

These tests cover both fixes.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))
sys.path.insert(0, str(APP_DIR / "backend"))

import chat
import llama


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(chat, "CONFIG_PATH", tmp_path / "chat.json")
    app = FastAPI()
    app.include_router(chat.router)
    return TestClient(app)


def _fake_discovered(tmp_path) -> list[dict]:
    ollama_dir = tmp_path / "ollama-store"
    lmstudio_dir = tmp_path / "lmstudio-store"
    ollama_dir.mkdir()
    lmstudio_dir.mkdir()
    ollama_model = ollama_dir / "llama-3.2-3b-instruct.gguf"
    lmstudio_model = lmstudio_dir / "qwen2.5-7b-instruct.gguf"
    ollama_model.write_bytes(b"fake-weights-ollama")
    lmstudio_model.write_bytes(b"fake-weights-lmstudio")
    return [
        {
            "id": "llama-3.2-3b-instruct", "name": "llama 3.2 3b instruct",
            "path": str(ollama_model), "sizeBytes": ollama_model.stat().st_size,
            "kind": "chat", "sourceDir": str(ollama_dir),
        },
        {
            "id": "qwen2.5-7b-instruct", "name": "qwen2.5 7b instruct",
            "path": str(lmstudio_model), "sizeBytes": lmstudio_model.stat().st_size,
            "kind": "chat", "sourceDir": str(lmstudio_dir),
        },
    ]


def test_resolve_model_finds_model_discovered_outside_models_dir(tmp_path, monkeypatch):
    """A model that only exists in an Ollama/LM Studio/Jan store (never copied
    into Conductor's own models/) must still resolve by the id the Settings
    picker (GET /api/llama/discover) already offers for it."""
    discovered = _fake_discovered(tmp_path)
    monkeypatch.setattr(llama, "discover_models", lambda **kw: {"models": discovered})
    monkeypatch.setattr(llama, "MODELS_DIR", tmp_path / "empty-conductor-models")

    resolved = llama.resolve_model("qwen2.5-7b-instruct")

    assert resolved == Path(discovered[1]["path"])


def test_resolve_model_still_finds_bare_name_in_models_dir_first(tmp_path, monkeypatch):
    """Existing behavior (bare filename inside Conductor's own models/) must
    keep working unchanged, without even needing to consult discover_models."""
    models_dir = tmp_path / "conductor-models"
    models_dir.mkdir()
    (models_dir / "local.gguf").write_bytes(b"fake-weights")
    monkeypatch.setattr(llama, "MODELS_DIR", models_dir)

    def _boom(**kw):
        raise AssertionError("discover_models should not be called when MODELS_DIR already has the file")

    monkeypatch.setattr(llama, "discover_models", _boom)

    resolved = llama.resolve_model("local")

    assert resolved == models_dir / "local.gguf"


def test_resolve_model_raises_helpful_404_when_nowhere_found(tmp_path, monkeypatch):
    monkeypatch.setattr(llama, "discover_models", lambda **kw: {"models": []})
    monkeypatch.setattr(llama, "MODELS_DIR", tmp_path / "empty-conductor-models")

    with pytest.raises(Exception) as exc_info:
        llama.resolve_model("nonexistent-model")

    assert "not found" in str(exc_info.value).lower()


def test_chat_models_endpoint_lists_models_from_every_discovered_location(client, tmp_path, monkeypatch):
    discovered = _fake_discovered(tmp_path)
    monkeypatch.setattr(llama, "discover_models", lambda **kw: {"models": discovered})

    response = client.get("/api/chat/models?provider=llama")

    assert response.status_code == 200
    payload = response.json()
    assert payload["providerId"] == "llama"
    ids = {m["id"] for m in payload["models"]}
    assert ids == {"llama-3.2-3b-instruct", "qwen2.5-7b-instruct"}
    source_dirs = {m["sourceDir"] for m in payload["models"]}
    assert source_dirs == {discovered[0]["sourceDir"], discovered[1]["sourceDir"]}


def test_chat_config_lists_discovered_local_models(client, tmp_path, monkeypatch):
    discovered = _fake_discovered(tmp_path)
    monkeypatch.setattr(llama, "discover_models", lambda **kw: {"models": discovered})

    response = client.get("/api/chat/config")

    assert response.status_code == 200
    assert set(response.json()["llama_models"]) == {"llama-3.2-3b-instruct", "qwen2.5-7b-instruct"}
