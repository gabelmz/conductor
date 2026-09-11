from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR / "backend"))

import providers
import storage
from spine import active, preferred
from spine.schema import init_tables


@pytest.fixture(autouse=True)
def setup_temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "test_conductor.db")
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    storage._local = threading.local()
    storage.init_db()
    init_tables()
    monkeypatch.setattr(providers, "CONFIG_PATH", tmp_path / "provider-config.json")
    monkeypatch.setattr(providers, "KEYS_PATH", tmp_path / "provider-keys.json")


def test_active_falls_back_to_default_when_nothing_configured():
    result = active.resolve_active_chat_target()
    assert result["source"] == "default"
    assert result["provider"] in providers.HOSTED_PROVIDERS


def test_active_prefers_explicit_request_over_preferred_and_default():
    providers.set_key("openai", "c2stZmFrZQ==", encrypted=False)
    result = active.resolve_active_chat_target(requested_provider="openai", requested_model="gpt-4o-mini")
    assert result == {"provider": "openai", "model": "gpt-4o-mini", "source": "user"}


def test_active_uses_preferred_when_no_explicit_request():
    providers.set_key("deepseek", "c2stZmFrZQ==", encrypted=False)
    preferred.set_preferred({"provider": "deepseek", "model": "deepseek-chat"})
    result = active.resolve_active_chat_target()
    assert result == {"provider": "deepseek", "model": "deepseek-chat", "source": "preferred"}


def test_active_ignores_preferred_provider_with_no_key_configured():
    preferred.set_preferred({"provider": "openai", "model": "gpt-4o-mini"})
    result = active.resolve_active_chat_target()
    assert result["source"] == "default"


def test_resolve_fallback_target_reads_preferred_fallback():
    providers.set_key("deepseek", "c2stZmFrZQ==", encrypted=False)
    preferred.set_preferred({
        "provider": "openai", "model": "gpt-4o-mini",
        "fallback_provider": "deepseek", "fallback_model": "deepseek-chat",
    })
    fb = active.resolve_fallback_target(exclude_provider="openai")
    assert fb == {"provider": "deepseek", "model": "deepseek-chat"}


def test_resolve_fallback_target_none_when_fallback_equals_excluded():
    preferred.set_preferred({
        "provider": "openai", "model": "gpt-4o-mini",
        "fallback_provider": "openai", "fallback_model": "gpt-4o",
    })
    assert active.resolve_fallback_target(exclude_provider="openai") is None
