# Spine State Layering & Supabase Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn `backend/spine.py` into a real package with four explicit state layers (default, user config, preferred, active), make chat/model selection resolve through it instead of duplicated hardcoded constants, add active→preferred/fallback chat error recovery, and get the `conductor.*` Supabase mirror actually built and synced.

**Architecture:** `backend/spine.py` becomes `backend/spine/` with one file per responsibility (schema/DDL, default-state seed data, user-config passthrough, preferred-state CRUD, active-state resolver, FastAPI routes). `chat.py` stops owning its own `DEFAULT_PROVIDER`/`DEFAULT_MODEL` constants and instead calls `spine.active.resolve_active_chat_target()`; on an outright provider failure it retries once against `spine.active.resolve_fallback_target()`. Supabase gets a new migration that actually creates the `conductor` schema (today only `public.*` tables are real — confirmed via `docs/sync-architecture.md`'s prior audit and by reading every existing migration) plus a push-only sync job reusing `backend/sync_runner.py`'s lease/checkpoint primitives.

**Tech Stack:** Python 3.11 / FastAPI / SQLite (existing `backend/storage.py` conventions) / Postgres (Supabase, existing `supabase/migrations/` conventions, PostgREST-over-HTTP per `supabase_sync.py`).

**Spec:** This document. Originating request: layer the spine into default/user-config/preferred/active state, make every model/config reference in the app go through the spine, add chat active→fallback error recovery, and get `conductor.*` actually synced and cleaned up (memory/table-format hazards).

## Global Constraints

- Never write secrets (API keys, tokens) into any `spine_*` table or into Supabase — `secret_refs` names a local reference only (existing rule, `backend/spine.py`'s own docstring).
- `tests/test_spine.py`'s three existing tests must keep passing unmodified — the package refactor is behavior-preserving for every existing `/api/spine/*` route.
- `main.py`'s `from spine import init_spine_db, router as spine_router` (line 53) and `init_spine_db()` (line 64) must keep working with zero changes to `main.py`.
- No destructive migration of `data/chat.json` / `data/provider-config.json` / `data/provider-keys.json` — those stay the write-path for secrets and user-entered values; the spine reads them, it does not replace their storage.
- Every new Supabase table: RLS enabled, no public policies (service-role only), matching `supabase/conductor-schema.sql`'s existing convention.
- Full `pytest` suite (currently 172 passing) must stay green after every task.

---

### Task 1: Convert `backend/spine.py` into a `backend/spine/` package

**Files:**
- Create: `backend/spine/__init__.py`, `backend/spine/schema.py`, `backend/spine/default_state.py`, `backend/spine/user_config.py`, `backend/spine/routes.py`
- Delete: `backend/spine.py` (content redistributed, nothing dropped)
- Test: `tests/test_spine.py` (unmodified — must still pass as the acceptance check)

**Interfaces:**
- Produces: `spine.init_spine_db()`, `spine.router` (re-exported from `__init__.py`, same names `main.py` already imports)
- Produces: `spine.schema.init_tables()` (DDL only, no seeding)
- Produces: `spine.default_state.seed_defaults(conn, now)` (moved verbatim from old `seed_defaults`/`_seed_models`/`_seed_registry`)
- Produces: `spine.user_config.get_configuration(scope, key)`, `spine.user_config.put_configuration(scope, key, body)` (moved verbatim from old `get_configuration`/`put_configuration`)

- [ ] **Step 1: Create `backend/spine/schema.py`** — move `init_spine_db`'s `CREATE TABLE` script (old `backend/spine.py:100-159`) into a standalone `init_tables()`:

```python
"""Spine SQLite schema — table DDL only. No seed data, no seeding logic."""
from __future__ import annotations

import storage


def init_tables() -> None:
    conn = storage._conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS spine_registry (
          kind TEXT NOT NULL, registry_key TEXT NOT NULL, label TEXT NOT NULL,
          description TEXT NOT NULL DEFAULT '', route TEXT NOT NULL DEFAULT '', icon TEXT NOT NULL DEFAULT '',
          status_key TEXT NOT NULL DEFAULT 'active', lifecycle_key TEXT NOT NULL DEFAULT 'stable',
          capabilities TEXT NOT NULL DEFAULT '[]', metadata TEXT NOT NULL DEFAULT '{}', source_hash TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY(kind, registry_key)
        );
        CREATE TABLE IF NOT EXISTS spine_status_definitions (
          status_key TEXT PRIMARY KEY, label TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', category TEXT NOT NULL,
          color_token TEXT NOT NULL DEFAULT '', sort_order INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1,
          metadata TEXT NOT NULL DEFAULT '{}', updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS spine_lifecycle_definitions (
          lifecycle_key TEXT PRIMARY KEY, label TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', sort_order INTEGER NOT NULL DEFAULT 0,
          terminal INTEGER NOT NULL DEFAULT 0, transitions TEXT NOT NULL DEFAULT '[]', metadata TEXT NOT NULL DEFAULT '{}', updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS spine_file_type_definitions (
          extension TEXT PRIMARY KEY, label TEXT NOT NULL, category TEXT NOT NULL, parse_handler TEXT NOT NULL DEFAULT '',
          mime_types TEXT NOT NULL DEFAULT '[]', max_bytes INTEGER, enabled INTEGER NOT NULL DEFAULT 1,
          metadata TEXT NOT NULL DEFAULT '{}', updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS spine_model_catalog (
          provider_id TEXT NOT NULL, model_id TEXT NOT NULL, label TEXT NOT NULL DEFAULT '', capabilities TEXT NOT NULL DEFAULT '[]',
          context_window INTEGER, input_modalities TEXT NOT NULL DEFAULT '["text"]', output_modalities TEXT NOT NULL DEFAULT '["text"]',
          is_embedding INTEGER NOT NULL DEFAULT 0, is_active INTEGER NOT NULL DEFAULT 1, metadata TEXT NOT NULL DEFAULT '{}', updated_at TEXT NOT NULL,
          PRIMARY KEY(provider_id, model_id)
        );
        CREATE TABLE IF NOT EXISTS spine_model_presets (
          preset_key TEXT PRIMARY KEY, label TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', provider_id TEXT NOT NULL, model_id TEXT NOT NULL,
          system_prompt_key TEXT NOT NULL DEFAULT 'default', parameters TEXT NOT NULL DEFAULT '{}', enabled INTEGER NOT NULL DEFAULT 1,
          metadata TEXT NOT NULL DEFAULT '{}', updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS spine_configurations (
          config_scope TEXT NOT NULL, config_key TEXT NOT NULL, value TEXT NOT NULL DEFAULT '{}', version INTEGER NOT NULL DEFAULT 1,
          secret_refs TEXT NOT NULL DEFAULT '[]', updated_at TEXT NOT NULL, PRIMARY KEY(config_scope, config_key)
        );
        CREATE TABLE IF NOT EXISTS spine_node_library (
          node_type TEXT PRIMARY KEY, label TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', category TEXT NOT NULL, icon TEXT NOT NULL DEFAULT '',
          input_schema TEXT NOT NULL DEFAULT '{}', output_schema TEXT NOT NULL DEFAULT '{}', config_schema TEXT NOT NULL DEFAULT '{}',
          execution_mode TEXT NOT NULL DEFAULT 'local', lifecycle_key TEXT NOT NULL DEFAULT 'stable', enabled INTEGER NOT NULL DEFAULT 1,
          metadata TEXT NOT NULL DEFAULT '{}', updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS spine_node_presets (
          preset_key TEXT PRIMARY KEY, node_type TEXT NOT NULL, label TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', config TEXT NOT NULL DEFAULT '{}',
          enabled INTEGER NOT NULL DEFAULT 1, metadata TEXT NOT NULL DEFAULT '{}', updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS spine_datasets (
          dataset_key TEXT PRIMARY KEY, label TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', entity_type TEXT NOT NULL, source_type TEXT NOT NULL,
          lifecycle_key TEXT NOT NULL DEFAULT 'active', freshness_seconds INTEGER, schema_definition TEXT NOT NULL DEFAULT '{}',
          source_config TEXT NOT NULL DEFAULT '{}', metadata TEXT NOT NULL DEFAULT '{}', updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS spine_global_filter_definitions (
          filter_key TEXT PRIMARY KEY, label TEXT NOT NULL, entity_type TEXT NOT NULL, field_path TEXT NOT NULL, control_type TEXT NOT NULL,
          options_source TEXT NOT NULL DEFAULT '{}', default_value TEXT, enabled INTEGER NOT NULL DEFAULT 1, sort_order INTEGER NOT NULL DEFAULT 0,
          metadata TEXT NOT NULL DEFAULT '{}', updated_at TEXT NOT NULL
        );
    """)
    conn.commit()
```

- [ ] **Step 2: Create `backend/spine/default_state.py`** — move the seed constants and `seed_defaults`/`_seed_models`/`_seed_registry` verbatim from old `backend/spine.py:24-83` and `:164-222`, unchanged except imports (`import storage`, `from pathlib import Path`, `import hashlib, json, re`). Keep function names identical: `seed_defaults()`, `_seed_models(conn, now)`, `_seed_registry(conn, now)`.

- [ ] **Step 3: Create `backend/spine/user_config.py`** — move `_json`, `_decode`, `get_configuration`, `put_configuration` verbatim from old `backend/spine.py:86-97` and `:269-288`, dropping the `@router` decorators (routes move to `routes.py`, which imports these as plain functions):

```python
"""Spine 'user config' layer — non-secret, user-editable configuration.

Secrets never live here: `secret_refs` only names a local secret reference
(e.g. a provider key stored in data/provider-keys.json), never a raw value.
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException

import storage


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _decode(row: Any, json_columns: tuple[str, ...]) -> dict:
    item = dict(row)
    for key in json_columns:
        try:
            item[key] = json.loads(item.get(key) or ("[]" if key.endswith(("s", "ies")) else "{}"))
        except (TypeError, json.JSONDecodeError):
            item[key] = [] if key.endswith(("s", "ies")) else {}
    return item


def put_configuration(scope: str, key: str, body: dict) -> dict:
    if "value" not in body:
        raise HTTPException(400, "value is required")
    value = body["value"]
    secret_refs = body.get("secret_refs") or []
    now = storage.now_iso()
    conn = storage._conn()
    conn.execute(
        "INSERT INTO spine_configurations VALUES (?,?,?,?,?,?) ON CONFLICT(config_scope,config_key) "
        "DO UPDATE SET value=excluded.value,version=spine_configurations.version+1,"
        "secret_refs=excluded.secret_refs,updated_at=excluded.updated_at",
        (scope, key, _json(value), 1, _json(secret_refs), now),
    )
    conn.commit()
    return {"ok": True, "scope": scope, "key": key}


def get_configuration(scope: str, key: str) -> dict:
    r = storage._conn().execute(
        "SELECT * FROM spine_configurations WHERE config_scope=? AND config_key=?", (scope, key)
    ).fetchone()
    if not r:
        raise HTTPException(404, "configuration not found")
    return _decode(r, ("value", "secret_refs"))


def read_configuration_value(scope: str, key: str, default: dict | None = None) -> dict:
    """Non-raising variant for internal callers (e.g. the active-state resolver)."""
    r = storage._conn().execute(
        "SELECT * FROM spine_configurations WHERE config_scope=? AND config_key=?", (scope, key)
    ).fetchone()
    if not r:
        return default or {}
    return _decode(r, ("value", "secret_refs"))["value"]
```

- [ ] **Step 4: Create `backend/spine/routes.py`** — move `snapshot`, `glossary`, `models`, `nodes`, `filters` verbatim from old `backend/spine.py:225-266`, plus the two config routes as thin wrappers calling `user_config.py`, plus the two new routes Tasks 2/3 add (declared here now, implemented then):

```python
"""Spine FastAPI routes — local-first snapshot/glossary/models/nodes/filters/config."""
from __future__ import annotations

from fastapi import APIRouter

import storage
from spine import active, preferred, user_config
from spine.user_config import _decode

router = APIRouter(prefix="/api/spine", tags=["spine"])


@router.get("/snapshot")
def snapshot() -> dict:
    conn = storage._conn()
    return {
        "registry": [_decode(r, ("capabilities", "metadata")) for r in conn.execute("SELECT * FROM spine_registry ORDER BY kind,label")],
        "statuses": [_decode(r, ("metadata",)) for r in conn.execute("SELECT * FROM spine_status_definitions ORDER BY sort_order")],
        "lifecycles": [_decode(r, ("transitions", "metadata")) for r in conn.execute("SELECT * FROM spine_lifecycle_definitions ORDER BY sort_order")],
        "file_types": [_decode(r, ("mime_types", "metadata")) for r in conn.execute("SELECT * FROM spine_file_type_definitions ORDER BY category,label")],
        "models": [_decode(r, ("capabilities", "input_modalities", "output_modalities", "metadata")) for r in conn.execute("SELECT * FROM spine_model_catalog WHERE is_active=1 ORDER BY provider_id,model_id")],
        "model_presets": [_decode(r, ("parameters", "metadata")) for r in conn.execute("SELECT * FROM spine_model_presets WHERE enabled=1 ORDER BY label")],
        "nodes": [_decode(r, ("input_schema", "output_schema", "config_schema", "metadata")) for r in conn.execute("SELECT * FROM spine_node_library WHERE enabled=1 ORDER BY category,label")],
        "datasets": [_decode(r, ("schema_definition", "source_config", "metadata")) for r in conn.execute("SELECT * FROM spine_datasets ORDER BY label")],
        "filters": [_decode(r, ("options_source", "default_value", "metadata")) for r in conn.execute("SELECT * FROM spine_global_filter_definitions WHERE enabled=1 ORDER BY sort_order")],
    }


@router.get("/glossary")
def glossary(q: str = "", kind: str = "") -> dict:
    query = q.strip().lower()
    items = snapshot()["registry"]
    if kind:
        items = [x for x in items if x["kind"] == kind]
    if query:
        items = [x for x in items if query in (x["label"] + " " + x["description"] + " " + x["registry_key"]).lower()]
    return {"count": len(items), "items": items}


@router.get("/models")
def models() -> dict:
    data = snapshot()
    return {"models": data["models"], "presets": data["model_presets"]}


@router.get("/models/preferred")
def get_preferred_model() -> dict:
    return preferred.get_preferred()


@router.put("/models/preferred")
def put_preferred_model(body: dict) -> dict:
    return preferred.set_preferred(body)


@router.get("/models/active")
def get_active_model() -> dict:
    return active.resolve_active_chat_target()


@router.get("/nodes")
def nodes() -> dict:
    return {"nodes": snapshot()["nodes"]}


@router.get("/filters")
def filters() -> dict:
    return {"filters": snapshot()["filters"]}


@router.put("/config/{scope}/{key}")
def put_configuration(scope: str, key: str, body: dict) -> dict:
    return user_config.put_configuration(scope, key, body)


@router.get("/config/{scope}/{key}")
def get_configuration(scope: str, key: str) -> dict:
    return user_config.get_configuration(scope, key)
```

- [ ] **Step 5: Create `backend/spine/__init__.py`**:

```python
"""Conductor local-first application spine — see docs/CONDUCTOR-SPINE.md.

Four state layers, all resolved locally before any cloud round-trip:
  - default:      spine.default_state  (factory seed: providers.HOSTED_PROVIDERS, node
                  library, statuses, lifecycles, file types, datasets, filters)
  - user config:  spine.user_config    (spine_configurations table — non-secret,
                  user-editable; secrets never enter this layer)
  - preferred:    spine.preferred      (the user's chosen chat target + fallback target)
  - active:       spine.active         (computed: user config > preferred > default)
"""
from __future__ import annotations

from spine.default_state import seed_defaults
from spine.routes import router
from spine.schema import init_tables


def init_spine_db() -> None:
    init_tables()
    seed_defaults()


__all__ = ["init_spine_db", "router"]
```

- [ ] **Step 6: Delete the old `backend/spine.py` file** (its content is now fully redistributed across the five new files).

- [ ] **Step 7: Run the existing spine test to confirm the refactor is behavior-preserving**

Run: `cd backend && PYTHONPATH=.. ../.venv/Scripts/python.exe -m pytest ../tests/test_spine.py -v` (or from repo root: `PYTHONPATH=backend .venv/Scripts/python.exe -m pytest tests/test_spine.py -v`)
Expected: all 3 existing tests PASS unchanged.

- [ ] **Step 8: Commit**

```bash
git add backend/spine backend/spine.py tests/test_spine.py
git commit -m "refactor: split backend/spine.py into a spine/ package"
```
(Note: `git add backend/spine.py` stages its deletion since the file no longer exists on disk.)

---

### Task 2: Add the "preferred state" layer

**Files:**
- Create: `backend/spine/preferred.py`
- Test: `tests/test_spine_preferred.py`

**Interfaces:**
- Consumes: `spine.user_config.read_configuration_value(scope, key, default)`, `spine.user_config.put_configuration(scope, key, body)` (Task 1)
- Produces: `spine.preferred.get_preferred() -> dict`, `spine.preferred.set_preferred(body: dict) -> dict`, `spine.preferred.PREFERRED_SCOPE = "chat"`, `spine.preferred.PREFERRED_KEY = "preferred"` — later consumed by `spine.active` (Task 3) and `spine/routes.py` (Task 1, already wired above)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_spine_preferred.py
from __future__ import annotations

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_preferred_defaults_to_empty_until_set():
    response = client.get("/api/spine/models/preferred")
    assert response.status_code == 200
    assert response.json() == {"provider": None, "model": None, "fallback_provider": None, "fallback_model": None}


def test_preferred_can_be_set_and_read_back():
    body = {"provider": "openai", "model": "gpt-4o-mini", "fallback_provider": "deepseek", "fallback_model": "deepseek-chat"}
    saved = client.put("/api/spine/models/preferred", json=body)
    assert saved.status_code == 200
    assert saved.json() == body

    loaded = client.get("/api/spine/models/preferred")
    assert loaded.status_code == 200
    assert loaded.json() == body


def test_preferred_rejects_unknown_provider():
    response = client.put("/api/spine/models/preferred", json={"provider": "not-a-real-provider", "model": "x"})
    assert response.status_code == 400
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=backend .venv/Scripts/python.exe -m pytest tests/test_spine_preferred.py -v`
Expected: FAIL — `GET /api/spine/models/preferred` 404s (route doesn't exist yet).

- [ ] **Step 3: Write `backend/spine/preferred.py`**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=backend .venv/Scripts/python.exe -m pytest tests/test_spine_preferred.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/spine/preferred.py tests/test_spine_preferred.py
git commit -m "feat: add spine preferred-state layer for chat provider/model + fallback"
```

---

### Task 3: Add the "active state" resolver

**Files:**
- Create: `backend/spine/active.py`
- Test: `tests/test_spine_active.py`

**Interfaces:**
- Consumes: `spine.preferred.get_preferred()` (Task 2), `providers.HOSTED_PROVIDERS`, `providers.resolve_api_key(provider_id)`, `providers.model_is_allowed(provider_id, model_id)` (all existing, `backend/providers.py`)
- Produces: `spine.active.resolve_active_chat_target(requested_provider=None, requested_model=None) -> dict` with keys `provider`, `model`, `source` (`"user"|"preferred"|"default"`) — consumed by Task 4 (`chat.py`)
- Produces: `spine.active.resolve_fallback_target(exclude_provider: str) -> dict | None` with keys `provider`, `model` — consumed by Task 5 (`chat.py`)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_spine_active.py
from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR / "backend"))

import providers
import storage
from spine import active, preferred, user_config


@pytest.fixture(autouse=True)
def setup_temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "test_conductor.db")
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    storage._local = threading.local()
    storage.init_db()
    from spine.schema import init_tables
    init_tables()
    monkeypatch.setattr(providers, "CONFIG_PATH", tmp_path / "provider-config.json")
    monkeypatch.setattr(providers, "KEYS_PATH", tmp_path / "provider-keys.json")


def test_active_falls_back_to_default_when_nothing_configured():
    result = active.resolve_active_chat_target()
    assert result["source"] == "default"
    assert result["provider"] in providers.HOSTED_PROVIDERS


def test_active_prefers_explicit_request_over_preferred_and_default(monkeypatch):
    providers.set_key("openai", "c2stZmFrZQ==", encrypted=False)
    result = active.resolve_active_chat_target(requested_provider="openai", requested_model="gpt-4o-mini")
    assert result == {"provider": "openai", "model": "gpt-4o-mini", "source": "user"}


def test_active_uses_preferred_when_no_explicit_request(monkeypatch):
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=backend .venv/Scripts/python.exe -m pytest tests/test_spine_active.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'spine.active'`.

- [ ] **Step 3: Write `backend/spine/active.py`**

```python
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


def _first_configured_provider() -> tuple[str, str]:
    import providers as providers_mod

    for pid, meta in providers_mod.HOSTED_PROVIDERS.items():
        if providers_mod.resolve_api_key(pid):
            return pid, providers_mod.read_provider_config(pid).get("defaultModelId") or meta["default_model"]
    # Nothing configured at all yet — still return a deterministic, known-valid pair.
    first_pid = next(iter(providers_mod.HOSTED_PROVIDERS))
    return first_pid, providers_mod.HOSTED_PROVIDERS[first_pid]["default_model"]


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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=backend .venv/Scripts/python.exe -m pytest tests/test_spine_active.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/spine/active.py tests/test_spine_active.py
git commit -m "feat: add spine active-state resolver (user > preferred > default)"
```

---

### Task 4: Wire `chat.py` to resolve provider/model through the spine

**Files:**
- Modify: `backend/chat.py` (`_load_config`, `DEFAULT_PROVIDER`/`DEFAULT_MODEL` usage)
- Test: `tests/test_chat_active_state.py`

**Interfaces:**
- Consumes: `spine.active.resolve_active_chat_target()` (Task 3)
- Produces: `chat._load_config()` now returns a provider/model resolved through the spine when the on-disk config has never been explicitly set (fixes the `deepseek-v4-flash` vs. `providers.py`'s `deepseek-chat` mismatch — the two disagreed because neither ever consulted the other)

This directly fixes a real, already-diagnosed bug: `chat.py`'s own `DEFAULT_MODEL = "deepseek-v4-flash"` (`backend/chat.py:88`) does not match `providers.HOSTED_PROVIDERS["deepseek"]["default_model"] == "deepseek-chat"` (`backend/providers.py:66`) — a fresh install with no saved config would request a chat model no provider config table actually declares.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_chat_active_state.py
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


@pytest.fixture(autouse=True)
def setup_temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "test_conductor.db")
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    storage._local = threading.local()
    storage.init_db()
    from spine.schema import init_tables
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=backend .venv/Scripts/python.exe -m pytest tests/test_chat_active_state.py -v`
Expected: FAIL on `test_fresh_install_default_model_is_actually_valid_for_its_provider` (`deepseek-v4-flash` is not in DeepSeek's allowed catalog).

- [ ] **Step 3: Edit `backend/chat.py`** — replace the hardcoded fallback in `_load_config` with the spine's active-state resolver, keeping `DEFAULT_BASE_URL` as-is (base URL still comes from `providers.HOSTED_PROVIDERS`, unaffected by this change):

```python
def _load_config() -> dict:
    cfg = {}
    if CONFIG_PATH.exists():
        try:
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            cfg = {}
    provider = cfg.get("provider")
    model = cfg.get("model")
    if not provider or not model:
        from spine.active import resolve_active_chat_target
        resolved = resolve_active_chat_target(requested_provider=provider, requested_model=model)
        provider = provider or resolved["provider"]
        model = model or resolved["model"]
    return {
        "provider": provider,
        "base_url": (cfg.get("base_url") or DEFAULT_BASE_URL).rstrip("/"),
        "model": model,
        "api_key": cfg.get("api_key") or os.environ.get("DEEPSEEK_API_KEY", ""),
        "system_prompt": cfg.get("system_prompt") or DEFAULT_SYSTEM_PROMPT,
        "llama_system_prompt": cfg.get("llama_system_prompt") or DEFAULT_LLAMA_SYSTEM_PROMPT,
        "llama_model": cfg.get("llama_model") or "",
        "llama_ctx": int(cfg.get("llama_ctx") or 4096),
        "llama_port": int(cfg.get("llama_port") or 8098),
    }
```

Remove the now-unused `DEFAULT_MODEL = "deepseek-v4-flash"` and `DEFAULT_PROVIDER = "deepseek"` constants (`backend/chat.py:88-89`) — grep the file first to confirm nothing else references them before deleting.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=backend .venv/Scripts/python.exe -m pytest tests/test_chat_active_state.py tests/test_provider_scoping.py tests/test_llama_lazy_install.py -v`
Expected: all PASS (the two existing files must not regress).

- [ ] **Step 5: Commit**

```bash
git add backend/chat.py tests/test_chat_active_state.py
git commit -m "fix: resolve chat default provider/model through the spine active-state layer"
```

---

### Task 5: Chat active→fallback error recovery

**Files:**
- Modify: `backend/chat.py` (`chat()`'s `generate()`)
- Test: `tests/test_chat_fallback.py`

**Interfaces:**
- Consumes: `spine.active.resolve_fallback_target(exclude_provider)` (Task 3), `providers.stream_provider(...)` (existing, `backend/providers.py:777-794`)

Only retries when the **very first** streamed event is an error (the call failed outright before any text reached the user) — a mid-stream failure after partial text is surfaced as-is, never silently retried into a second, confusing partial answer.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_chat_fallback.py
from __future__ import annotations

import asyncio
import sys
import threading
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR / "backend"))

import chat
import providers
import storage


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "test_conductor.db")
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    storage._local = threading.local()
    storage.init_db()
    from spine.schema import init_tables
    init_tables()
    monkeypatch.setattr(chat, "CONFIG_PATH", tmp_path / "chat.json")
    monkeypatch.setattr(providers, "CONFIG_PATH", tmp_path / "provider-config.json")
    monkeypatch.setattr(providers, "KEYS_PATH", tmp_path / "provider-keys.json")
    app = FastAPI()
    app.include_router(chat.router)
    return TestClient(app)


def test_outright_provider_failure_falls_back_to_configured_target(client, monkeypatch):
    from spine import preferred
    preferred.set_preferred({
        "provider": "openai", "model": "gpt-4o-mini",
        "fallback_provider": "deepseek", "fallback_model": "deepseek-chat",
    })

    def fake_stream(provider_id, messages, model=None, api_key=None, max_tokens=1200, temperature=0.6):
        if provider_id == "openai":
            yield {"type": "error", "code": "HTTP_401", "message": "invalid key"}
        else:
            yield {"type": "text", "text": "fallback answer"}

    monkeypatch.setattr(providers, "stream_provider", fake_stream)

    response = client.post("/api/chat", json={"message": "hi", "provider": "openai", "model": "gpt-4o-mini"})
    assert response.status_code == 200
    assert "fallback answer" in response.text
    assert "deepseek" in response.text.lower()


def test_mid_stream_failure_is_not_retried(client, monkeypatch):
    calls = []

    def fake_stream(provider_id, messages, model=None, api_key=None, max_tokens=1200, temperature=0.6):
        calls.append(provider_id)
        yield {"type": "text", "text": "partial answer"}
        yield {"type": "error", "code": "HTTP_500", "message": "server hiccup"}

    monkeypatch.setattr(providers, "stream_provider", fake_stream)

    response = client.post("/api/chat", json={"message": "hi", "provider": "openai", "model": "gpt-4o-mini"})
    assert "partial answer" in response.text
    assert calls == ["openai"]  # never retried
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=backend .venv/Scripts/python.exe -m pytest tests/test_chat_fallback.py -v`
Expected: FAIL — today's `generate()` has no fallback path at all, so the first test's `"fallback answer"` never appears.

- [ ] **Step 3: Edit `backend/chat.py`'s `chat()` handler** — replace the `generate()` closure with a fallback-aware version:

```python
    def generate():
        started = time.time()
        usage_obj = None
        active_provider = provider
        try:
            events = providers.stream_provider(active_provider, messages, model=model, api_key=api_key)
            first = next(events, None)
            if first is not None and first["type"] == "error":
                from spine.active import resolve_fallback_target
                fallback = resolve_fallback_target(exclude_provider=active_provider)
                if fallback:
                    yield f"[falling back to {fallback['provider']}/{fallback['model']}]\n"
                    active_provider = fallback["provider"]
                    events = providers.stream_provider(
                        active_provider, messages, model=fallback["model"], api_key=None
                    )
                    first = next(events, None)
            remaining = ([first] if first is not None else []) 
            for ev in remaining + list(events):
                if ev["type"] == "text":
                    yield ev["text"]
                elif ev["type"] == "thinking":
                    yield f"⧙THINK⧚{ev['text']}⧙/THINK⧚"
                elif ev["type"] == "usage":
                    usage_obj = ev
                elif ev["type"] == "error":
                    yield f"\n[ERROR] {ev['code']}: {ev['message']}"
        except ValueError as exc:
            yield f"\n[ERROR] {exc}"
        finally:
            if usage_obj:
                usage.record(
                    input_tokens=usage_obj.get("prompt_tokens") or 0,
                    output_tokens=usage_obj.get("completion_tokens") or 0,
                )
            elapsed = time.time() - started
            yield f"\n\n_({elapsed:.1f}s · {active_provider})_"
```

Note: `remaining + list(events)` fully drains the (potentially large) `events` generator into a list eagerly, which defeats streaming for the common case. Prefer an explicit chain instead — replace that line and the loop with:

```python
            import itertools
            for ev in itertools.chain([first] if first is not None else [], events):
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=backend .venv/Scripts/python.exe -m pytest tests/test_chat_fallback.py tests/test_provider_scoping.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add backend/chat.py tests/test_chat_fallback.py
git commit -m "feat: fall back to the configured spine fallback target on an outright chat provider failure"
```

---

### Task 6: `conductor.*` Supabase schema — actually create it

**Files:**
- Create: `supabase/migrations/20260910_0003_conductor_schema.sql`
- Modify: `docs/CONDUCTOR-SPINE.md` (replace the unverified "already contains" claim)
- Delete: `spine_sync_supabase.sql`, `spine_sync_models_registry.sql` (repo-root orphans — confirmed by the prior sync-architecture audit to be hand-written seed dumps never wired to any migration or code, targeting a schema that never existed; their intent is fully superseded by this real migration)

Per `docs/sync-architecture.md`'s existing audit (already read this session): only `public.*` tables are real today; `conductor.*` has never been migrated anywhere in this repo. This task creates it for real, mirroring every `spine_*` SQLite table's shape (per `docs/CONDUCTOR-SPINE.md`'s own mapping table) plus a new `conductor.preferred_state` table for Task 2's addition.

- [ ] **Step 1: Write `supabase/migrations/20260910_0003_conductor_schema.sql`**

```sql
-- Actually creates the `conductor` schema that docs/CONDUCTOR-SPINE.md has
-- documented since before this migration existed. Prior audit
-- (docs/sync-architecture.md, section 1) confirmed no CREATE SCHEMA/CREATE
-- TABLE for `conductor.*` exists anywhere in this repo's migrations — only
-- public.conductor_records/sync_runs/sync_leases/sync_checkpoints/sync_outbox
-- are real. This migration is additive only; nothing in `public.*` is touched.
--
-- Table shapes mirror backend/spine/schema.py's spine_* SQLite tables
-- one-for-one (see docs/CONDUCTOR-SPINE.md's mapping table), plus a new
-- conductor.preferred_state table for the spine's preferred-state layer.
-- Secrets never enter this schema — spine_configurations.secret_refs only
-- ever names a local secret reference, never a raw value, and that
-- constraint is preserved here unchanged.

create schema if not exists conductor;

create table if not exists conductor.registry (
  kind text not null, registry_key text not null, label text not null,
  description text not null default '', route text not null default '', icon text not null default '',
  status_key text not null default 'active', lifecycle_key text not null default 'stable',
  capabilities jsonb not null default '[]'::jsonb, metadata jsonb not null default '{}'::jsonb,
  source_hash text not null default '', created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(), primary key (kind, registry_key)
);

create table if not exists conductor.status_definitions (
  status_key text primary key, label text not null, description text not null default '',
  category text not null, color_token text not null default '', sort_order integer not null default 0,
  active boolean not null default true, metadata jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

create table if not exists conductor.lifecycle_definitions (
  lifecycle_key text primary key, label text not null, description text not null default '',
  sort_order integer not null default 0, terminal boolean not null default false,
  transitions jsonb not null default '[]'::jsonb, metadata jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

create table if not exists conductor.file_type_definitions (
  extension text primary key, label text not null, category text not null,
  parse_handler text not null default '', mime_types jsonb not null default '[]'::jsonb,
  max_bytes bigint, enabled boolean not null default true, metadata jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

create table if not exists conductor.model_catalog (
  provider_id text not null, model_id text not null, label text not null default '',
  capabilities jsonb not null default '[]'::jsonb, context_window integer,
  input_modalities jsonb not null default '["text"]'::jsonb, output_modalities jsonb not null default '["text"]'::jsonb,
  is_embedding boolean not null default false, is_active boolean not null default true,
  metadata jsonb not null default '{}'::jsonb, updated_at timestamptz not null default now(),
  primary key (provider_id, model_id)
);

create table if not exists conductor.model_presets (
  preset_key text primary key, label text not null, description text not null default '',
  provider_id text not null, model_id text not null, system_prompt_key text not null default 'default',
  parameters jsonb not null default '{}'::jsonb, enabled boolean not null default true,
  metadata jsonb not null default '{}'::jsonb, updated_at timestamptz not null default now()
);

-- Non-secret configuration only — secret_refs names a local reference, never a value.
create table if not exists conductor.configurations (
  config_scope text not null, config_key text not null, value jsonb not null default '{}'::jsonb,
  version integer not null default 1, secret_refs jsonb not null default '[]'::jsonb,
  updated_at timestamptz not null default now(), primary key (config_scope, config_key)
);

create table if not exists conductor.node_library (
  node_type text primary key, label text not null, description text not null default '',
  category text not null, icon text not null default '', input_schema jsonb not null default '{}'::jsonb,
  output_schema jsonb not null default '{}'::jsonb, config_schema jsonb not null default '{}'::jsonb,
  execution_mode text not null default 'local', lifecycle_key text not null default 'stable',
  enabled boolean not null default true, metadata jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

create table if not exists conductor.node_presets (
  preset_key text primary key, node_type text not null, label text not null,
  description text not null default '', config jsonb not null default '{}'::jsonb,
  enabled boolean not null default true, metadata jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

create table if not exists conductor.datasets (
  dataset_key text primary key, label text not null, description text not null default '',
  entity_type text not null, source_type text not null, lifecycle_key text not null default 'active',
  freshness_seconds integer, schema_definition jsonb not null default '{}'::jsonb,
  source_config jsonb not null default '{}'::jsonb, metadata jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

create table if not exists conductor.global_filter_definitions (
  filter_key text primary key, label text not null, entity_type text not null, field_path text not null,
  control_type text not null, options_source jsonb not null default '{}'::jsonb, default_value text,
  enabled boolean not null default true, sort_order integer not null default 0,
  metadata jsonb not null default '{}'::jsonb, updated_at timestamptz not null default now()
);

-- New in this migration: mirrors backend/spine/preferred.py's spine_configurations
-- (scope='chat', key='preferred') row as a typed row for easier hosted-side reads.
create table if not exists conductor.preferred_state (
  scope text primary key, provider text, model text, fallback_provider text, fallback_model text,
  updated_at timestamptz not null default now()
);

alter table conductor.registry enable row level security;
alter table conductor.status_definitions enable row level security;
alter table conductor.lifecycle_definitions enable row level security;
alter table conductor.file_type_definitions enable row level security;
alter table conductor.model_catalog enable row level security;
alter table conductor.model_presets enable row level security;
alter table conductor.configurations enable row level security;
alter table conductor.node_library enable row level security;
alter table conductor.node_presets enable row level security;
alter table conductor.datasets enable row level security;
alter table conductor.global_filter_definitions enable row level security;
alter table conductor.preferred_state enable row level security;
-- Conductor uses a service-role key server-side; no public policies are
-- created (matches supabase/conductor-schema.sql's existing convention).

-- PostgREST only exposes schemas listed in the API's exposed-schemas setting;
-- `conductor` must be added there (Dashboard -> Settings -> API -> Exposed
-- schemas, or via the Management API) before any REST call against it will
-- work. This migration cannot do that from SQL — flagged here so it is not
-- silently missed the way the original conductor.* claim in
-- docs/CONDUCTOR-SPINE.md was.

-- =====================================================================================
-- ROLLBACK
-- =====================================================================================
-- drop table if exists conductor.preferred_state;
-- drop table if exists conductor.global_filter_definitions;
-- drop table if exists conductor.datasets;
-- drop table if exists conductor.node_presets;
-- drop table if exists conductor.node_library;
-- drop table if exists conductor.configurations;
-- drop table if exists conductor.model_presets;
-- drop table if exists conductor.model_catalog;
-- drop table if exists conductor.file_type_definitions;
-- drop table if exists conductor.lifecycle_definitions;
-- drop table if exists conductor.status_definitions;
-- drop table if exists conductor.registry;
-- drop schema if exists conductor;
```

- [ ] **Step 2: Delete the orphaned seed files**

```bash
git rm spine_sync_supabase.sql spine_sync_models_registry.sql
```

- [ ] **Step 3: Update `docs/CONDUCTOR-SPINE.md`'s "Cloud Target" section** — replace:

```
## Cloud Target

Supabase project `dfvylthyfrcarucyqgru` now contains the `conductor.*` mirror
tables with RLS enabled. Backend/server credentials are required before an
application sync job writes to those tables.
```

with:

```
## Cloud Target

`conductor.*` is created by `supabase/migrations/20260910_0003_conductor_schema.sql`
— apply it with `supabase db push` (or run it directly against the project)
before any sync job can write to it. RLS is enabled with no public policies
(service-role only). The `conductor` schema must also be added to PostgREST's
exposed-schemas list (Dashboard -> Settings -> API -> Exposed schemas) before
a REST call against it will succeed — creating the schema alone is not
sufficient. `backend/spine_sync.py` (see the next task) is the only writer.
```

- [ ] **Step 4: Verify the migration is syntactically valid SQL** (no live Supabase connection required/available in this environment)

Run: `PYTHONPATH=backend .venv/Scripts/python.exe -c "import sqlparse, pathlib; sql = pathlib.Path('supabase/migrations/20260910_0003_conductor_schema.sql').read_text(); print(len(sqlparse.parse(sql))); print('OK')"` — if `sqlparse` is not installed, instead visually re-read the file end-to-end checking every `create table`/`alter table` statement ends with `;` and every parenthesis balances (no automated linter is available in this environment).

- [ ] **Step 5: Commit**

```bash
git add supabase/migrations/20260910_0003_conductor_schema.sql docs/CONDUCTOR-SPINE.md
git rm spine_sync_supabase.sql spine_sync_models_registry.sql
git commit -m "feat: create the conductor.* Supabase schema for real, retire orphaned seed sql"
```

---

### Task 7: Push-only spine → Supabase sync job

**Files:**
- Create: `backend/spine_sync.py`
- Modify: `backend/main.py` (mount nothing new — this is invoked on demand, not a router; add one call site, see Step 3)
- Test: `tests/test_spine_sync.py`

**Interfaces:**
- Consumes: `sync_runner.SyncAdapter`, `sync_runner.run_sync` (existing, `backend/sync_runner.py:315-481`)
- Produces: `spine_sync.push_all(session=None) -> dict` — one `run_sync()` call per spine table, pushed to its `conductor.*` mirror

Push-only (spine SQLite is authoritative; Supabase is a mirror per `docs/CONDUCTOR-SPINE.md`'s own "Cloud sync is a mirror, never a prerequisite" principle) — there is no pull path to build, which keeps this task small and avoids inventing a two-way conflict policy nothing asked for.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_spine_sync.py
from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR / "backend"))

import spine_sync
import storage
from spine.schema import init_tables
from spine.default_state import seed_defaults


@pytest.fixture(autouse=True)
def setup_temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "test_conductor.db")
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    storage._local = threading.local()
    storage.init_db()
    init_tables()
    seed_defaults()


class _FakeSession:
    def __init__(self):
        self.requests = []

    def request(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs))
        class _Resp:
            status_code = 201
            def json(self_inner):
                return []
            def raise_for_status(self_inner):
                pass
        return _Resp()


def test_push_all_sends_one_batch_per_spine_table():
    session = _FakeSession()
    result = spine_sync.push_all(session=session)
    assert result["status"] == "done"
    pushed_tables = {call[1].split("/")[-1].split("?")[0] for call in session.requests}
    assert "model_catalog" in pushed_tables
    assert "status_definitions" in pushed_tables


def test_push_all_never_sends_a_secret_ref_value():
    session = _FakeSession()
    spine_sync.push_all(session=session)
    for _method, _url, kwargs in session.requests:
        body = kwargs.get("json") or []
        for row in body:
            assert "secret_refs" not in row or row.get("secret_refs") in (None, [], "[]")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=backend .venv/Scripts/python.exe -m pytest tests/test_spine_sync.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'spine_sync'`.

- [ ] **Step 3: Write `backend/spine_sync.py`**

```python
"""Push-only spine -> Supabase conductor.* mirror.

Spine SQLite is authoritative (docs/CONDUCTOR-SPINE.md: "cloud sync is a
mirror, never a prerequisite for normal local operation"), so this is push-
only — no pull path, no conflict policy to invent. Reuses sync_runner's
lease/checkpoint primitives (backend/sync_runner.py) so a hosted job and this
local push can never race on the same table.

configurations rows are pushed with secret_refs always cleared to '[]' before
leaving this process, even though spine_configurations.secret_refs is already
documented as reference-only, never a raw value — belt-and-suspenders, since
this is the one function whose entire job is deciding what leaves the machine.
"""
from __future__ import annotations

import json
from typing import Any

import requests as _requests

import storage
import sync_runner

TABLES = (
    "registry", "status_definitions", "lifecycle_definitions", "file_type_definitions",
    "model_catalog", "model_presets", "configurations", "node_library", "node_presets",
    "datasets", "global_filter_definitions",
)

_SPINE_TABLE = {name: f"spine_{name}" for name in TABLES}


def _rows_for(table: str) -> list[dict[str, Any]]:
    conn = storage._conn()
    rows = [dict(r) for r in conn.execute(f"SELECT * FROM {_SPINE_TABLE[table]}")]
    if table == "configurations":
        for row in rows:
            row["secret_refs"] = "[]"
    return rows


def _push_table(table: str, *, session, base_url: str, headers: dict) -> None:
    rows = _rows_for(table)
    if not rows:
        return
    session.request(
        "POST", f"{base_url}/{table}",
        params={"on_conflict": _primary_key_columns(table)},
        json=rows,
        headers={**headers, "Prefer": "resolution=merge-duplicates,return=minimal"},
    )


_PRIMARY_KEYS = {
    "registry": "kind,registry_key", "status_definitions": "status_key",
    "lifecycle_definitions": "lifecycle_key", "file_type_definitions": "extension",
    "model_catalog": "provider_id,model_id", "model_presets": "preset_key",
    "configurations": "config_scope,config_key", "node_library": "node_type",
    "node_presets": "preset_key", "datasets": "dataset_key",
    "global_filter_definitions": "filter_key",
}


def _primary_key_columns(table: str) -> str:
    return _PRIMARY_KEYS[table]


def push_all(session: Any = None) -> dict:
    import supabase_sync

    session = session or _requests
    status = supabase_sync.get_status()
    if not status.get("configured"):
        return {"status": "skipped", "reason": "supabase_not_configured"}

    cfg = supabase_sync._load_config()
    base_url = f"{cfg['url'].rstrip('/')}/rest/v1/conductor"
    headers = {
        "apikey": cfg["service_key"], "Authorization": f"Bearer {cfg['service_key']}",
        "Content-Type": "application/json",
    }

    def fetch_since(_cursor):
        for table in TABLES:
            _push_table(table, session=session, base_url=base_url, headers=headers)
        return [], storage.now_iso()

    adapter = sync_runner.SyncAdapter(
        entity="spine", fetch_since=fetch_since,
        key_of=lambda item: "spine", apply=lambda item: None,
    )
    return sync_runner.run_sync(
        adapter=adapter, lease_owner="spine-sync",
        health_check=lambda: supabase_sync.test_connection().get("ok", False),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=backend .venv/Scripts/python.exe -m pytest tests/test_spine_sync.py -v`
Expected: PASS. If `supabase_sync._load_config()`'s actual field names (`url`/`service_key`) differ from what's assumed above, read `backend/supabase_sync.py`'s `_load_config` before finalizing this step — adjust the two dict-key lookups in `push_all` to match, this is the one place in this task most likely to need a small correction against the real file.

- [ ] **Step 5: Commit**

```bash
git add backend/spine_sync.py tests/test_spine_sync.py
git commit -m "feat: add push-only spine to conductor.* Supabase sync job"
```

---

### Task 8: Quick stability fix — dead `api_post` branch

**Files:**
- Modify: `backend/asana_sync.py` (add `api_post`), `backend/main.py:757` (remove the now-unnecessary `hasattr` guard)
- Test: extend `tests/test_asana_enhancements.py` (or add `tests/test_asana_api_post.py` if that file's fixtures don't fit)

Already-diagnosed in `docs/sync-architecture.md` (risk register #5, read this session): `backend/main.py:757` guards on `hasattr(asana_sync, "api_post")`, which has never existed, so task creation always falls through to a raw `urllib` call that bypasses `asana_sync`'s rate limiting and 429/5xx retry entirely.

- [ ] **Step 1: Write the failing test** (adapt to whatever fixture pattern `tests/test_asana_enhancements.py` already uses for mocking `asana_sync.api_get`'s retry behavior — read that file first for the exact mock/monkeypatch shape before writing this)

```python
def test_api_post_exists_and_reuses_the_paced_retrying_client(monkeypatch):
    import asana_sync
    assert hasattr(asana_sync, "api_post")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=backend .venv/Scripts/python.exe -m pytest tests/test_asana_enhancements.py -k api_post -v`
Expected: FAIL — `api_post` does not exist yet.

- [ ] **Step 3: Add `api_post` to `backend/asana_sync.py`**, mirroring `api_get`'s retry/pacing (read `api_get`'s exact implementation at `backend/asana_sync.py:158-182` before writing this, to match its retry/backoff/rate-limit behavior rather than approximating it) and remove the dead `hasattr` guard at `backend/main.py:757`, calling `asana_sync.api_post(...)` unconditionally.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=backend .venv/Scripts/python.exe -m pytest tests/test_asana_enhancements.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/asana_sync.py backend/main.py tests/test_asana_enhancements.py
git commit -m "fix: give Asana task creation the same paced/retrying client as every other call"
```

---

## Self-Review Notes

- **Spec coverage:** default state (Task 1, unchanged existing tables) / user config state (Task 1, existing `spine_configurations` formalized as its own module) / preferred state (Task 2) / active state (Task 3) / "all references reference the spine" (Task 4 fixes `chat.py`'s independent defaults) / chat active→fallback (Task 5) / `conductor.*` sync (Tasks 6-7) / "clean up memory issues, table formats" (Task 8, the one still-open diagnosed bug; the `weight`-clobber `INSERT OR REPLACE` hazard from the same audit was independently confirmed already fixed via `storage.merge_upsert` — no task needed for it).
- **Frontend:** no frontend changes are required by Tasks 1-5 — every response shape consumed by `frontend/app.js` today is preserved; Task 2/3's new routes are additive.
- **Risk flagged inline:** Task 7 Step 4 flags the one place (`supabase_sync._load_config()`'s exact field names) that must be checked against the live file rather than assumed, since this plan was written without re-reading that function's current field names in full.
