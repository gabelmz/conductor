"""Spine 'preferred state' — the user's chosen chat target plus a fallback
target, distinct from whatever happens to be resolved as 'active' right now.
Stored in the existing spine_configurations table (scope='chat', key='preferred')
rather than a new table — it is exactly the non-secret, user-editable
configuration that table already exists for.
"""
from __future__ import annotations

from fastapi import HTTPException

from spine import user_config

SCOPE = "chat"
KEY = "preferred"

_EMPTY = {"provider": None, "model": None, "fallback_provider": None, "fallback_model": None}


def get_preferred() -> dict:
    value = user_config.read_configuration_value(SCOPE, KEY, default=_EMPTY)
    return {**_EMPTY, **value}


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
    return value
