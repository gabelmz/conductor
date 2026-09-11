"""Push-only spine -> Supabase conductor.* mirror.

Spine SQLite is authoritative (docs/CONDUCTOR-SPINE.md: "cloud sync is a
mirror, never a prerequisite for normal local operation"), so this is push-
only — no pull path, no conflict policy to invent. Reuses sync_runner's
lease/checkpoint primitives (backend/sync_runner.py) so a hosted job and this
local push can never race on the same table.

Schema selection: PostgREST does not select a non-default schema via a URL
path segment. It is addressed with the SAME /rest/v1/<table> URL used for
`public.*` tables; the target schema is named in the Accept-Profile header
(GET/HEAD) or Content-Profile header (POST/PATCH/DELETE) — see
supabase_sync.py's own `_request()` (the `profile_header` branch), whose
convention this module matches exactly rather than inventing a second one.
PostgREST also only recognizes a schema named in those headers if it has
been added to the project's exposed-schemas list (Dashboard -> Settings ->
API -> Exposed schemas) — see the migration's own comment on this, since it
cannot be done from SQL.

configurations rows are pushed with secret_refs always cleared to '[]' before
leaving this process, even though spine_configurations.secret_refs is already
documented as reference-only, never a raw value — belt-and-suspenders, since
this is the one function whose entire job is deciding what leaves the machine.
"""
from __future__ import annotations

from typing import Any

import requests as _requests

import storage
import sync_runner

CONDUCTOR_SCHEMA = "conductor"

TABLES = (
    "registry", "status_definitions", "lifecycle_definitions", "file_type_definitions",
    "model_catalog", "model_presets", "configurations", "node_library", "node_presets",
    "datasets", "global_filter_definitions",
)

_SPINE_TABLE = {name: f"spine_{name}" for name in TABLES}

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
        headers=headers,
    )


def push_all(session: Any = None) -> dict:
    import supabase_sync

    session = session or _requests
    status = supabase_sync.get_status()
    if not status.get("configured"):
        return {"status": "skipped", "reason": "supabase_not_configured"}

    cfg = supabase_sync._load_config()
    base_url = f"{cfg['url'].rstrip('/')}/rest/v1"
    headers = {
        "apikey": cfg["service_key"],
        "Authorization": f"Bearer {cfg['service_key']}",
        "Content-Type": "application/json",
        "Content-Profile": CONDUCTOR_SCHEMA,
        "Prefer": "resolution=merge-duplicates,return=minimal",
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
        health_check=lambda: supabase_sync.test_connection(session=session).get("ok", False),
    )
