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
    # The payload deliberately supports only non-secret configuration.
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
    """Non-raising variant for internal callers (e.g. the active-state resolver).

    Returns `default` even if spine_configurations itself doesn't exist yet —
    callers like spine.active.resolve_active_chat_target() must never break a
    chat request just because init_spine_db() happens to run after them in
    some test or startup ordering; production always calls it first
    (main.py's startup event), but this stays defensive against that not
    holding true everywhere.
    """
    import sqlite3

    try:
        r = storage._conn().execute(
            "SELECT * FROM spine_configurations WHERE config_scope=? AND config_key=?", (scope, key)
        ).fetchone()
    except sqlite3.OperationalError:
        return default if default is not None else {}
    if not r:
        return default if default is not None else {}
    return _decode(r, ("value", "secret_refs"))["value"]
