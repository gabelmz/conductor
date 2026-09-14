"""Spine 'preferred state' — the user's chosen chat target plus a fallback
target, distinct from whatever happens to be resolved as 'active' right now.
Stored in the existing spine_configurations table (scope='chat', key='preferred')
rather than a new table — it is exactly the non-secret, user-editable
configuration that table already exists for.
"""
from __future__ import annotations

import threading
from typing import Any

from fastapi import HTTPException

from spine import user_config

SCOPE = "chat"
KEY = "preferred"

_EMPTY = {"provider": None, "model": None, "fallback_provider": None, "fallback_model": None}

_cache_lock = threading.Lock()
_cache: dict[str, Any] | None = None


def invalidate_cache() -> None:
    """Invalidate the in-memory preferred state cache immediately."""
    global _cache
    with _cache_lock:
        _cache = None


def clear_cache() -> None:
    """Alias for invalidate_cache()."""
    invalidate_cache()


def get_preferred() -> dict:
    """Read preferred state, returning cached copy if available."""
    global _cache
    with _cache_lock:
        if _cache is not None:
            return dict(_cache)

    value = user_config.read_configuration_value(SCOPE, KEY, default=_EMPTY)
    res = {**_EMPTY, **value}

    with _cache_lock:
        _cache = res
    return dict(res)


def set_preferred(body: dict) -> dict:
    import providers as providers_mod

    provider = body.get("provider")
    fallback_provider = body.get("fallback_provider")
    for pid in (provider, fallback_provider):
        if pid is not None and pid not in providers_mod.HOSTED_PROVIDERS and pid != "llama":
            raise HTTPException(400, f"Unknown provider '{pid}'")
    value = {
        "provider": provider,
        "model": body.get("model"),
        "fallback_provider": fallback_provider,
        "fallback_model": body.get("fallback_model"),
    }
    user_config.put_configuration(SCOPE, KEY, {"value": value})
    invalidate_cache()
    return value


def clear_preferred() -> dict:
    """Reset preferred state in DB and invalidate cache immediately."""
    user_config.put_configuration(SCOPE, KEY, {"value": _EMPTY})
    invalidate_cache()
    return dict(_EMPTY)
