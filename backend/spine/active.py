"""Spine 'active state' — the chat provider/model Conductor is using right
now, resolved live (never a fourth stored copy) by layering:

  1. an explicit per-request override (requested_provider/requested_model)
  2. the preferred-state layer (spine.preferred)
  3. the factory default: the first HOSTED_PROVIDERS entry with a resolvable
     key, else the plain first-declared provider's default model

Each layer is skipped, not errored, when it names a provider with no usable
key — an unusable preference must never break the chat request that reads it.
"""
from __future__ import annotations

from spine import preferred


_LOCAL_PROVIDER_IDS = frozenset({"ollama", "lmstudio"})


def _first_configured_provider() -> tuple[str, str]:
    """First *cloud* provider with a resolvable key, using its declared
    default model untouched — matches the same trust-the-constant pattern
    chat.py's own set_config() already uses elsewhere for cloud providers.

    Local providers (ollama/lmstudio) are deliberately excluded from this
    tier: `resolve_api_key` returns a truthy placeholder for both
    unconditionally (no key is ever required), but their real catalog is
    whatever happens to be installed on this machine, not a stable factory
    default — silently picking one here would mean auto-selecting a locally
    installed model the user never chose, and validating it would require a
    live network round-trip on every single call to this function (this is
    the resolver of last resort, hit on every chat request until the user
    saves an explicit selection — it must stay fast). A user who wants a
    local provider sets it explicitly via the preferred-state layer or a
    per-request override, where `_usable()`'s validation cost is paid once,
    not on every idle default lookup.
    """
    import providers as providers_mod

    for pid, meta in providers_mod.HOSTED_PROVIDERS.items():
        if pid in _LOCAL_PROVIDER_IDS:
            continue
        if providers_mod.resolve_api_key(pid):
            return pid, providers_mod.read_provider_config(pid).get("defaultModelId") or meta["default_model"]
    # Nothing configured at all — still return a deterministic, known cloud pair.
    for pid, meta in providers_mod.HOSTED_PROVIDERS.items():
        if pid not in _LOCAL_PROVIDER_IDS:
            return pid, meta["default_model"]
    raise RuntimeError("no non-local providers declared in HOSTED_PROVIDERS")


def _usable(provider_id: str | None, model_id: str | None) -> bool:
    import providers as providers_mod

    if not provider_id:
        return False
    if provider_id == "llama":
        return True
    if provider_id not in providers_mod.HOSTED_PROVIDERS:
        return False
    if not providers_mod.resolve_api_key(provider_id):
        return False
    return not model_id or providers_mod.model_is_allowed(provider_id, model_id)


def resolve_active_chat_target(requested_provider: str | None = None, requested_model: str | None = None) -> dict:
    if _usable(requested_provider, requested_model):
        return {"provider": requested_provider, "model": requested_model, "source": "user"}

    pref = preferred.get_preferred()
    if _usable(pref.get("provider"), pref.get("model")):
        return {"provider": pref["provider"], "model": pref["model"], "source": "preferred"}

    provider, model = _first_configured_provider()
    return {"provider": provider, "model": model, "source": "default"}


def resolve_fallback_target(exclude_provider: str) -> dict | None:
    pref = preferred.get_preferred()
    fb_provider = pref.get("fallback_provider")
    fb_model = pref.get("fallback_model")
    if not fb_provider or fb_provider == exclude_provider:
        return None
    if not _usable(fb_provider, fb_model):
        return None
    return {"provider": fb_provider, "model": fb_model}
