"""Anthropic is removed from the app provider catalog (app scope only).

Scope note: this covers Conductor's own provider catalog. It deliberately does
NOT filter another provider's model list - OpenRouter legitimately serves
"anthropic/claude-*" ids from its own live catalog, and stripping them would
break OpenRouter for users.
"""
from __future__ import annotations

import sqlite3
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import providers


def test_anthropic_absent_from_catalog():
    assert "anthropic" not in providers.HOSTED_PROVIDERS


def test_catalog_still_has_the_other_presets():
    assert len(providers.HOSTED_PROVIDERS) == 22
    for pid in ("openai", "gemini", "openrouter", "deepseek", "grok", "mistral",
                "ollama", "lmstudio", "nvidia"):
        assert pid in providers.HOSTED_PROVIDERS


def test_every_provider_is_openai_compatible():
    """With Anthropic gone the catalog is format-uniform, which is what makes
    'default OpenAI format' structural rather than a convention."""
    kinds = {m["kind"] for m in providers.HOSTED_PROVIDERS.values()}
    assert kinds == {"openai-compatible"}


def test_anthropic_adapter_is_gone():
    assert not hasattr(providers, "AnthropicAdapter")


def test_build_adapter_never_returns_an_anthropic_adapter():
    adapter = providers.build_adapter("openai", "sk-test")
    assert type(adapter).__name__ == "OpenAICompatAdapter"


def test_seed_prunes_retired_provider_rows(tmp_path, monkeypatch):
    """Seeding is upsert-only, so a retired provider's rows would otherwise
    persist in spine_model_catalog forever."""
    import storage
    from spine import schema, default_state

    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "conductor.db")
    monkeypatch.setattr(storage, "UPLOAD_DIR", tmp_path / "uploads")
    storage._local = threading.local()
    storage.init_db()
    schema.init_tables()

    conn = storage._conn()
    # simulate a database seeded before the removal
    conn.execute(
        "INSERT INTO spine_model_catalog VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        ("anthropic", "claude-3-7-sonnet-20250219", "Anthropic", "[]", None,
         "[]", "[]", 0, 1, "{}", "2026-01-01T00:00:00Z"),
    )
    conn.execute(
        "INSERT INTO spine_model_presets VALUES (?,?,?,?,?,?,?,?,?,?)",
        ("anthropic-default", "Anthropic Default", "", "anthropic",
         "claude-3-7-sonnet-20250219", "default", "{}", 1, "{}", "2026-01-01T00:00:00Z"),
    )
    conn.commit()
    assert conn.execute(
        "SELECT COUNT(*) FROM spine_model_catalog WHERE provider_id='anthropic'"
    ).fetchone()[0] == 1

    default_state.seed_defaults()
    conn.commit()

    assert conn.execute(
        "SELECT COUNT(*) FROM spine_model_catalog WHERE provider_id='anthropic'"
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM spine_model_presets WHERE provider_id='anthropic'"
    ).fetchone()[0] == 0
    # a live provider must still be seeded
    assert conn.execute(
        "SELECT COUNT(*) FROM spine_model_catalog WHERE provider_id='openai'"
    ).fetchone()[0] >= 1


def test_prune_is_scoped_and_cannot_delete_user_providers():
    """The prune list is explicit, not 'anything missing from HOSTED_PROVIDERS',
    so a user-added provider can never be silently deleted."""
    from spine import default_state

    assert default_state.RETIRED_PROVIDER_IDS == ("anthropic",)
