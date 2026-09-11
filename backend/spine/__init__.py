"""Conductor local-first application spine — see docs/CONDUCTOR-SPINE.md.

Four state layers, all resolved locally before any cloud round-trip:
  - default:      spine.default_state  (factory seed: providers.HOSTED_PROVIDERS, node
                  library, statuses, lifecycles, file types, datasets, filters)
  - user config:  spine.user_config    (spine_configurations table — non-secret,
                  user-editable; secrets never enter this layer)
  - preferred:    spine.preferred      (the user's chosen chat target + fallback target)
  - active:       spine.active         (computed: user config > preferred > default)

`conductor.*` in Supabase mirrors the default/user-config layers when cloud
sync is configured (backend/spine_sync.py); secrets never enter the spine and
stay in the local keychain/config store.
"""
from __future__ import annotations

from spine.default_state import seed_defaults
from spine.routes import router
from spine.schema import init_tables


def init_spine_db() -> None:
    init_tables()
    seed_defaults()


__all__ = ["init_spine_db", "router"]
