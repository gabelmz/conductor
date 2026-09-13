"""Refresh must pull the model list FROM THE ENDPOINT.

The old behaviour swallowed every error and returned the hardcoded
default_model, so a dead or unconfigured endpoint was indistinguishable from a
one-model endpoint and Refresh appeared to succeed while showing a stale id.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import providers


@pytest.fixture(autouse=True)
def isolated_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(providers, "CONFIG_PATH", tmp_path / "provider-config.json")
    monkeypatch.setattr(providers, "KEYS_PATH", tmp_path / "provider-keys.json")
    monkeypatch.setattr(providers, "CATALOG_CACHE_PATH", tmp_path / "model-catalog.json")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


class FakeAdapter:
    def __init__(self, models=None, boom=None):
        self._models = models or []
        self._boom = boom

    def list_models(self):
        if self._boom:
            raise providers.ProviderListError("openai", self._boom)
        return self._models


def test_endpoint_models_are_returned_verbatim(monkeypatch):
    live = [{"id": "some-brand-new-model", "providerId": "openai"},
            {"id": "another-one", "providerId": "openai"}]
    monkeypatch.setattr(providers, "build_adapter", lambda *a, **k: FakeAdapter(live))

    result = providers.fetch_provider_models("openai")
    assert result["source"] == "endpoint"
    assert [m["id"] for m in result["models"]] == ["some-brand-new-model", "another-one"]
    assert result["error"] is None


def test_failed_endpoint_never_substitutes_the_hardcoded_default(monkeypatch):
    """The core regression."""
    monkeypatch.setattr(providers, "build_adapter", lambda *a, **k: FakeAdapter(boom="502 Bad Gateway"))

    result = providers.fetch_provider_models("openai")
    assert result["source"] == "error"
    assert result["models"] == []
    assert "502" in result["error"]
    hardcoded = providers.HOSTED_PROVIDERS["openai"]["default_model"]
    assert all(m["id"] != hardcoded for m in result["models"])


def test_cache_serves_last_successful_pull_when_endpoint_breaks(monkeypatch):
    live = [{"id": "pulled-earlier", "providerId": "openai"}]
    monkeypatch.setattr(providers, "build_adapter", lambda *a, **k: FakeAdapter(live))
    assert providers.fetch_provider_models("openai")["source"] == "endpoint"

    monkeypatch.setattr(providers, "build_adapter", lambda *a, **k: FakeAdapter(boom="timeout"))
    result = providers.fetch_provider_models("openai")
    assert result["source"] == "cache"
    assert [m["id"] for m in result["models"]] == ["pulled-earlier"]
    assert "timeout" in result["error"]


def test_refresh_bypasses_cache(monkeypatch):
    monkeypatch.setattr(providers, "build_adapter", lambda *a, **k: FakeAdapter([{"id": "x", "providerId": "openai"}]))
    providers.fetch_provider_models("openai")

    monkeypatch.setattr(providers, "build_adapter", lambda *a, **k: FakeAdapter(boom="down"))
    out = providers.refresh_catalog(["openai"])
    assert out["openai"]["source"] == "error", "refresh must hit the endpoint, not the cache"


def test_unconfigured_provider_is_labelled_curated_not_endpoint(monkeypatch):
    monkeypatch.setattr(providers, "build_adapter", lambda *a, **k: None)
    result = providers.fetch_provider_models("openai")
    assert result["source"] == "curated"
    assert result["error"] is not None, "must say why nothing was pulled"


def test_disabled_provider_reports_disabled():
    providers.set_provider_config("openai", {"enabled": False})
    assert providers.fetch_provider_models("openai")["source"] == "disabled"


def test_adapter_raises_instead_of_masking(monkeypatch):
    """OpenAICompatAdapter must not swallow errors into a fake one-item list."""
    adapter = providers.OpenAICompatAdapter("openai", "http://127.0.0.1:9/v1", "k", "gpt-x", "")
    with pytest.raises(providers.ProviderListError):
        adapter.list_models()


def test_offline_endpoint_does_not_invalidate_a_saved_model(monkeypatch):
    """Removing the silent fallback must not make model_is_allowed() reject
    everything when the endpoint is unreachable - that would break chat for
    every offline user. Only a SUCCESSFUL enumeration is authoritative."""
    providers.set_key("deepseek", "c2stZmFrZQ==", encrypted=False)
    monkeypatch.setattr(providers, "build_adapter", lambda *a, **k: FakeAdapter(boom="no route to host"))

    assert providers.fetch_provider_models("deepseek")["source"] == "error"
    assert providers.model_is_allowed("deepseek", "deepseek-chat") is True


def test_successful_enumeration_still_rejects_foreign_models(monkeypatch):
    """The authoritative case must keep working: endpoint answered, model absent."""
    monkeypatch.setattr(
        providers, "build_adapter",
        lambda *a, **k: FakeAdapter([{"id": "deepseek-chat", "providerId": "deepseek"}]),
    )
    assert providers.model_is_allowed("deepseek", "deepseek-chat") is True
    assert providers.model_is_allowed("deepseek", "gpt-4o-mini") is False
