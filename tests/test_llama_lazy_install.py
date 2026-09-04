"""Tests for the local model's lazy first-use provisioning (backend/llama.py,
backend/chat.py) — the default GGUF is never bundled in the installer and
never downloaded eagerly at startup, only fetched the first time the local
assistant is actually used with no model configured yet.
"""
from __future__ import annotations

import asyncio
import sys
import threading
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))
sys.path.insert(0, str(APP_DIR / "backend"))

import chat
import hf
import llama
import storage


@pytest.fixture(autouse=True)
def setup_temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "test_conductor.db")
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    storage._local = threading.local()
    storage.init_db()
    monkeypatch.setattr(chat, "CONFIG_PATH", tmp_path / "chat.json")
    hf._downloads.clear()
    yield tmp_path


def _drain(resp) -> bytes:
    """StreamingResponse wraps a sync generator in an async iterator — drain it."""
    async def _collect():
        out = []
        async for chunk in resp.body_iterator:
            out.append(chunk if isinstance(chunk, bytes) else chunk.encode())
        return b"".join(out)
    return asyncio.run(_collect())


def test_ensure_default_model_already_on_disk(tmp_path, monkeypatch):
    """If the GGUF already exists, no download is triggered — just reports ready."""
    target = tmp_path / "dolphin.gguf"
    target.write_bytes(b"fake-weights")
    monkeypatch.setattr(hf, "_download_target", lambda repo, filename: target)

    called = []
    monkeypatch.setattr(hf, "download", lambda body: called.append(body))

    result = llama.ensure_default_model()

    assert result["status"] == "ready"
    assert result["path"] == str(target)
    assert called == []  # never asked hf to download anything


def test_ensure_default_model_triggers_download_when_missing(tmp_path, monkeypatch):
    """No file, no in-flight download -> kicks one off and reports 'downloading'."""
    target = tmp_path / "dolphin.gguf"
    monkeypatch.setattr(hf, "_download_target", lambda repo, filename: target)

    called = []
    monkeypatch.setattr(hf, "download", lambda body: called.append(body) or {"id": "dl1"})

    result = llama.ensure_default_model()

    assert result["status"] == "downloading"
    assert result["progress"] == 0
    assert called == [{"repo_id": llama.DEFAULT_MODEL_REPO, "filename": llama.DEFAULT_MODEL_FILE}]


def test_ensure_default_model_does_not_redownload_while_in_flight(tmp_path, monkeypatch):
    """A download already in progress is reused, not restarted."""
    target = tmp_path / "dolphin.gguf"
    monkeypatch.setattr(hf, "_download_target", lambda repo, filename: target)
    hf._downloads["dl1"] = {
        "repo_id": llama.DEFAULT_MODEL_REPO,
        "filename": llama.DEFAULT_MODEL_FILE,
        "status": "downloading",
        "progress": 42,
    }

    called = []
    monkeypatch.setattr(hf, "download", lambda body: called.append(body))

    result = llama.ensure_default_model()

    assert result == {"status": "downloading", "progress": 42}
    assert called == []


def test_llama_chat_streams_setup_message_instead_of_erroring(monkeypatch):
    """With no llama_model configured, chatting via provider='llama' should
    kick off the lazy download and stream a friendly one-time setup message
    instead of a 400/404 model-not-found error."""
    monkeypatch.setattr(
        llama, "ensure_default_model", lambda: {"status": "downloading", "progress": 10}
    )

    resp = chat._llama_chat([{"role": "user", "content": "hi"}], {"llama_model": ""})
    body = _drain(resp)

    assert b"downloading" in body.lower() or b"setting up" in body.lower()


def test_llama_chat_uses_provisioned_model_once_ready(monkeypatch):
    """Once ensure_default_model reports ready, the config is updated and
    normal local-server routing proceeds (rather than re-downloading)."""
    monkeypatch.setattr(
        llama, "ensure_default_model",
        lambda: {"status": "ready", "path": "/models/hf/dolphin.gguf", "model": "dolphin.gguf"},
    )
    monkeypatch.setattr(llama, "_find_running_server", lambda: None)
    monkeypatch.setattr(llama, "start_server", lambda body: {"ok": True})
    monkeypatch.setattr(llama, "resolve_model", lambda name: Path("/models/hf/dolphin.gguf"))

    def fake_stream_chat(messages, model, port=None, max_tokens=1200):
        yield "hello from local model"

    monkeypatch.setattr(llama, "stream_chat", fake_stream_chat)
    monkeypatch.setattr(llama, "take_last_usage", lambda: None)

    cfg = {"llama_model": "", "llama_ctx": 4096, "llama_port": 8098}
    resp = chat._llama_chat([{"role": "user", "content": "hi"}], cfg)
    body = _drain(resp)

    assert cfg["llama_model"] == "/models/hf/dolphin.gguf"  # persisted onto cfg for reuse
    assert b"hello from local model" in body


def test_default_llama_system_prompt_used_for_llama_provider():
    """chat()'s system-prompt selection uses the dedicated local-assistant
    prompt for provider='llama', not the cloud Conductor Assistant prompt."""
    cfg = chat._load_config()
    assert "Local Assistant" in cfg["llama_system_prompt"]
    assert cfg["llama_system_prompt"] != cfg["system_prompt"]
