"""Generic user-settings store.

One persistence path for every user-editable preference: the command registry,
per-module product-tag prefs, model filters, and anything future.

Model: a bundle baseline (``DEFAULTS``, shipped in code) overlaid with user
deltas (rows in the ``settings`` table in ``conductor.db``). A user edit writes
a delta row; ``reset()`` removes it so the baseline applies again. Nothing is
stored inside the app bundle — deltas live in the repo's gitignored ``data/``
dir, so edits survive restarts and app updates.

This is deliberately the *only* settings persistence path; it reuses the
existing thread-local SQLite connection from ``storage`` rather than spawning a
second file or a second database.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone

from storage import _conn  # thread-local sqlite connection

# --- Bundle baseline: shipped defaults, keyed by namespace ----------------
# A version bump changes only these; existing user deltas keep winning.
DEFAULTS: dict = {
    "tagPref.data": "all",      # per-module product-tag preference
    # "tagPref.<module>": "all",  # per-module product-tag preference
    # "registry.<surface>.<id>": ...  # seeded by context_menus / settings editor
    # "model.filters": "...",
}

_listeners: list = []


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _decode(raw: str):
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return raw


def _encode(value) -> str:
    if isinstance(value, str):
        return value  # keep plain strings human-readable in the DB
    return json.dumps(value)


def _row(key: str):
    return _conn().execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()


def get(key: str, default=None):
    """User override if present, else the code baseline, else ``default``."""
    row = _row(key)
    if row is not None:
        return _decode(row["value"])
    return DEFAULTS.get(key, default)


def set(key: str, value):
    """Write a user delta (survives restart + update). Returns the stored value."""
    conn = _conn()
    conn.execute(
        "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (key, _encode(value), _now()),
    )
    conn.commit()
    _emit(key)
    return get(key)


def reset(key: str):
    """Drop the user delta; the code baseline applies again. Returns the value."""
    conn = _conn()
    conn.execute("DELETE FROM settings WHERE key = ?", (key,))
    conn.commit()
    _emit(key)
    return get(key)


def reset_all() -> None:
    conn = _conn()
    conn.execute("DELETE FROM settings")
    conn.commit()
    for cb in list(_listeners):
        try:
            cb(None)
        except Exception:
            pass


def resolve() -> dict:
    """Full merged view: baseline overlaid with every user delta."""
    merged = dict(DEFAULTS)
    rows = _conn().execute("SELECT key, value FROM settings").fetchall()
    for r in rows:
        merged[r["key"]] = _decode(r["value"])
    return merged


def subscribe(cb):
    """Register ``cb(key)`` for live editor binding. Returns an unsubscribe fn."""
    _listeners.append(cb)

    def _unsub():
        if cb in _listeners:
            _listeners.remove(cb)

    return _unsub


def _emit(key) -> None:
    for cb in list(_listeners):
        try:
            cb(key)
        except Exception:
            pass
