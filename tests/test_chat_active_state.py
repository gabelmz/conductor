from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR / "backend"))

import chat
import providers
import storage
from spine.schema import init_tables


@pytest.fixture(autouse=True)
def setup_temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "test_conductor.db")
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    storage._local = threading.local()
    storage.init_db()
    init_tables()
    monkeypatch.setattr(chat, "CONFIG_PATH", tmp_path / "chat.json")
    monkeypatch.setattr(providers, "CONFIG_PATH", tmp_path / "provider-config.json")
    monkeypatch.setattr(providers, "KEYS_PATH", tmp_path / "provider-keys.json")


def test_fresh_install_default_model_is_actually_valid_for_its_provider():
    """Regression test for the pre-existing deepseek-v4-flash vs. deepseek-chat
    mismatch: chat.py's own default must always be one providers.py actually
    declares for the same provider."""
    cfg = chat._load_config()
    assert providers.model_is_allowed(cfg["provider"], cfg["model"])


def test_default_model_matches_spine_active_state_source():
    from spine import active

    cfg = chat._load_config()
    resolved = active.resolve_active_chat_target()
    assert cfg["provider"] == resolved["provider"]
    assert cfg["model"] == resolved["model"]


def test_explicit_saved_selection_is_never_overridden():
    (tmp_path_cfg := chat.CONFIG_PATH).parent.mkdir(parents=True, exist_ok=True)
    chat._save_config({"provider": "mistral", "model": "mistral-large-latest"})
    cfg = chat._load_config()
    assert cfg["provider"] == "mistral"
    assert cfg["model"] == "mistral-large-latest"
