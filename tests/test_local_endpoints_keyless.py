"""Locally hosted inference endpoints must never require an API key.

Previously keyless access was a hardcoded two-id whitelist ("ollama",
"lmstudio"), so llama.cpp server, vLLM, atomic-chat, unsloth, or any custom
baseUrl pointed at localhost were refused with "Add an API key in Settings".
Detection is now by host.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import providers


@pytest.mark.parametrize("url", [
    "http://localhost:11434/v1",       # ollama
    "http://127.0.0.1:1234/v1",        # lm studio
    "http://127.0.0.1:8098/v1",        # bundled llama.cpp server
    "http://localhost:8000/v1",        # vllm / unsloth
    "http://127.0.0.1:3000/v1",        # atomic-chat
    "http://[::1]:8080/v1",            # ipv6 loopback
    "http://0.0.0.0:5000/v1",          # bind-all
    "http://127.5.5.5:9999/v1",        # anywhere in 127/8
    "http://app.localhost:1234/v1",    # .localhost suffix
])
def test_loopback_hosts_are_local(url):
    assert providers.is_local_endpoint(url) is True


@pytest.mark.parametrize("url", [
    "https://api.openai.com/v1",
    "https://generativelanguage.googleapis.com/v1beta/openai",
    "https://openrouter.ai/api/v1",
    "http://192.168.1.50:11434/v1",    # LAN host is NOT loopback
    "http://10.0.0.4:8000/v1",
    "https://localhost.evil.com/v1",   # suffix-spoof must not match
    "",
])
def test_remote_hosts_are_not_local(url):
    assert providers.is_local_endpoint(url) is False


def test_custom_local_endpoint_builds_adapter_without_key(tmp_path, monkeypatch):
    """The real regression: a non-ollama/lmstudio local endpoint used to get
    build_adapter() -> None, surfacing as 'Provider is not configured'."""
    monkeypatch.setattr(providers, "CONFIG_PATH", tmp_path / "provider-config.json")
    monkeypatch.setattr(providers, "KEYS_PATH", tmp_path / "provider-keys.json")
    # point a normally key-requiring provider at a local runtime, no key stored
    providers.set_provider_config("openai", {"baseUrl": "http://127.0.0.1:8000/v1"})

    adapter = providers.build_adapter("openai", providers.resolve_api_key("openai"))
    assert adapter is not None, "local endpoint must not require an API key"


def test_remote_endpoint_still_requires_key(tmp_path, monkeypatch):
    """The guard must still refuse keyless access to real hosted providers."""
    monkeypatch.setattr(providers, "CONFIG_PATH", tmp_path / "provider-config.json")
    monkeypatch.setattr(providers, "KEYS_PATH", tmp_path / "provider-keys.json")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    assert providers.resolve_api_key("openai") is None
    assert providers.build_adapter("openai", None) is None


def test_local_source_label(tmp_path, monkeypatch):
    monkeypatch.setattr(providers, "CONFIG_PATH", tmp_path / "provider-config.json")
    monkeypatch.setattr(providers, "KEYS_PATH", tmp_path / "provider-keys.json")
    assert providers.is_local_endpoint(providers.effective_base_url("ollama")) is True
    assert providers.is_local_endpoint(providers.effective_base_url("lmstudio")) is True
    assert providers.is_local_endpoint(providers.effective_base_url("openai")) is False
