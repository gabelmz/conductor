"""Sync runner — the shared contract for hosted and local-fallback sync execution.

`supabase/functions/asana-sync/index.ts` (hosted, Deno/Postgres) and Conductor's own desktop
backend (local fallback, this process) both need to sync Asana into Supabase without ever
writing the same records at the same time, without losing data when Supabase is briefly
unreachable, and without re-processing a batch that already landed. This module is the local
(Python) half of that contract:

  - ``SyncLease``     — mutual-exclusion lock so only one runner writes at a time.
  - ``Checkpoint``     — a persistent "how far did we get" cursor per entity.
  - ``Outbox``         — a durable local queue used while Supabase is unhealthy.
  - ``run_sync()``     — the one entry point that ties the three together: pull from the
                          adapter's source, write directly when Supabase is healthy, or queue
                          into the Outbox when it isn't; on recovery, drain the Outbox before
                          taking on new work.

Persistence follows the same idiom as backend/bernie.py:35 ``init()`` — plain
``CREATE TABLE IF NOT EXISTS`` executed once via ``storage._conn()`` at import time — so this
module needs no wiring into main.py to be usable.

Observability note: rather than adding a *third* local "runs" table (storage.py already has
``asana_sync_runs``, and Supabase already has its own ``sync_runs``), this module additively
extends the existing local ``asana_sync_runs`` table with a handful of nullable columns
(``entity``, ``degraded``, ``lease_owner``, ``duration_ms``) and writes into it. See
``_ensure_asana_sync_runs_columns`` for exactly what is added and why.

Everything here is deliberately injectable (clocks, sessions, adapters) so it can be exercised
with fakes — this module makes no live Asana or Supabase calls itself; those live in
``asana_sync.py`` / ``supabase_sync.py`` and in the concrete adapter a caller supplies.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import storage
from storage import now_iso

ClockFn = Callable[[], datetime]


def _default_clock() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ---------------------------------------------------------------------------
# Schema (bernie.py idiom: CREATE TABLE IF NOT EXISTS + storage._conn(), run at import time)
# ---------------------------------------------------------------------------
_ASANA_SYNC_RUNS_ADDITIONS = {
    "entity": "TEXT DEFAULT ''",
    "degraded": "INTEGER DEFAULT 0",
    "lease_owner": "TEXT DEFAULT ''",
    "duration_ms": "REAL DEFAULT 0",
}


def _ensure_asana_sync_runs_columns() -> None:
    """Additively extend storage.py's existing ``asana_sync_runs`` table.

    There are already two "runs" logs (local ``asana_sync_runs`` written by
    ``asana_sync.sync_all``, and the live Supabase ``sync_runs`` written by
    ``supabase_sync.sync``) — this module reuses the local one instead of creating a third,
    adding only nullable, additive columns. No-ops quietly if ``asana_sync_runs`` doesn't exist
    yet (i.e. ``storage.init_db()`` hasn't run) since ``asana_sync.py`` imports this module
    lazily, from inside ``sync_all()``, specifically to dodge that ordering hazard — but this
    stays defensive in case something imports this module standalone, earlier.
    """
    conn = storage._conn()
    try:
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(asana_sync_runs)").fetchall()}
    except sqlite3.OperationalError:
        return
    if not existing:
        return
    for col, decl in _ASANA_SYNC_RUNS_ADDITIONS.items():
        if col not in existing:
            try:
                conn.execute(f"ALTER TABLE asana_sync_runs ADD COLUMN {col} {decl}")
            except sqlite3.OperationalError:
                pass
    conn.commit()


def init() -> None:
    conn = storage._conn()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS sync_leases (
            name TEXT PRIMARY KEY,
            owner TEXT NOT NULL,
            acquired_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            heartbeat_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sync_checkpoints (
            entity TEXT PRIMARY KEY,
            cursor TEXT,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sync_outbox (
            idempotency_key TEXT PRIMARY KEY,
            entity TEXT NOT NULL,
            op TEXT NOT NULL,
            payload TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            error TEXT DEFAULT '',
            attempts INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_sync_outbox_status ON sync_outbox(status);
        CREATE INDEX IF NOT EXISTS idx_sync_outbox_entity ON sync_outbox(entity);
        """
    )
    conn.commit()
    _ensure_asana_sync_runs_columns()


init()


# ---------------------------------------------------------------------------
# SyncLease
# ---------------------------------------------------------------------------
class SyncLease:
    """A named mutual-exclusion lease backed by a single row in ``sync_leases``.

    Semantics: a lease is held by exactly one ``owner`` string until ``expires_at``. A live
    (unexpired) lease held by a *different* owner cannot be acquired. An expired lease — or one
    already held by the *same* owner (renewal / idempotent re-entry) — is acquirable/stealable.
    ``now`` is injectable so expiry can be tested deterministically without real sleeps.
    """

    def __init__(self, name: str, *, now: ClockFn | None = None):
        self.name = name
        self._now = now or _default_clock
        self._held = False
        self._owner: str | None = None
        self._ttl_s: float = 0.0

    def acquire(self, owner: str, ttl_s: float) -> bool:
        conn = storage._conn()
        now = self._now()
        row = conn.execute(
            "SELECT owner, expires_at FROM sync_leases WHERE name=?", (self.name,)
        ).fetchone()
        if row is not None:
            existing_owner = row["owner"]
            expires_at = _parse_iso(row["expires_at"])
            still_live = expires_at is not None and expires_at > now
            if still_live and existing_owner != owner:
                return False  # held by someone else, not expired -> not stealable
        expires = now + timedelta(seconds=ttl_s)
        conn.execute(
            "INSERT OR REPLACE INTO sync_leases (name, owner, acquired_at, expires_at, heartbeat_at) "
            "VALUES (?,?,?,?,?)",
            (self.name, owner, now.isoformat(), expires.isoformat(), now.isoformat()),
        )
        conn.commit()
        self._held = True
        self._owner = owner
        self._ttl_s = ttl_s
        return True

    def renew(self) -> bool:
        """Re-acquire under the same owner/ttl, pushing expires_at/heartbeat_at forward."""
        if not self._held or self._owner is None:
            return False
        return self.acquire(self._owner, self._ttl_s)

    def release(self) -> None:
        if not self._held or self._owner is None:
            return
        conn = storage._conn()
        conn.execute(
            "DELETE FROM sync_leases WHERE name=? AND owner=?", (self.name, self._owner)
        )
        conn.commit()
        self._held = False


# ---------------------------------------------------------------------------
# Checkpoint
# ---------------------------------------------------------------------------
class Checkpoint:
    """Persistent incremental cursor, one row per entity in ``sync_checkpoints``."""

    def get(self, entity: str) -> str | None:
        row = storage._conn().execute(
            "SELECT cursor FROM sync_checkpoints WHERE entity=?", (entity,)
        ).fetchone()
        return row["cursor"] if row and row["cursor"] else None

    def advance(self, entity: str, cursor: str) -> None:
        """Persist a new cursor. Callers must only call this after a successful batch commit —
        this class does not itself enforce that; see run_sync()."""
        conn = storage._conn()
        conn.execute(
            "INSERT OR REPLACE INTO sync_checkpoints (entity, cursor, updated_at) VALUES (?,?,?)",
            (entity, cursor, now_iso()),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# Outbox
# ---------------------------------------------------------------------------
class Outbox:
    """Durable local queue used when Supabase is unhealthy, deduped on idempotency_key.

    ``idempotency_key`` is the table's primary key: re-enqueueing the same key (e.g. the same
    Asana task gid changing twice while degraded) collapses to a single row holding the latest
    payload and resets it to 'pending' — it does not pile up duplicate queue entries, and it
    revives a previously synced/failed key if the same logical record needs syncing again.
    """

    def enqueue(self, entity: str, op: str, payload: dict[str, Any], idempotency_key: str) -> str:
        conn = storage._conn()
        now = now_iso()
        existing = conn.execute(
            "SELECT idempotency_key FROM sync_outbox WHERE idempotency_key=?", (idempotency_key,)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE sync_outbox SET entity=?, op=?, payload=?, status='pending', error='', "
                "updated_at=? WHERE idempotency_key=?",
                (entity, op, json.dumps(payload), now, idempotency_key),
            )
        else:
            conn.execute(
                "INSERT INTO sync_outbox (idempotency_key, entity, op, payload, status, error, "
                "attempts, created_at, updated_at) VALUES (?,?,?,?, 'pending', '', 0, ?, ?)",
                (idempotency_key, entity, op, json.dumps(payload), now, now),
            )
        conn.commit()
        return idempotency_key

    def pending(self, limit: int = 1000) -> list[dict[str, Any]]:
        rows = storage._conn().execute(
            "SELECT * FROM sync_outbox WHERE status='pending' ORDER BY created_at ASC LIMIT ?",
            (min(max(limit, 1), 10000),),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["payload"] = json.loads(d.get("payload") or "{}")
            except (TypeError, ValueError):
                d["payload"] = {}
            out.append(d)
        return out

    def mark_synced(self, idempotency_key: str) -> None:
        conn = storage._conn()
        conn.execute(
            "UPDATE sync_outbox SET status='synced', error='', updated_at=? WHERE idempotency_key=?",
            (now_iso(), idempotency_key),
        )
        conn.commit()

    def mark_failed(self, idempotency_key: str, err: str) -> None:
        conn = storage._conn()
        conn.execute(
            "UPDATE sync_outbox SET status='failed', error=?, attempts=attempts+1, updated_at=? "
            "WHERE idempotency_key=?",
            (str(err)[:2000], now_iso(), idempotency_key),
        )
        conn.commit()

    def requeue_failed(self) -> int:
        """Reset every failed row back to pending. Not part of the original spec's minimal
        surface, but an outbox that can only ever dead-end at 'failed' isn't durable in
        practice — this gives an operator/caller a way to retry without re-deriving payloads."""
        conn = storage._conn()
        cur = conn.execute(
            "UPDATE sync_outbox SET status='pending', updated_at=? WHERE status='failed'",
            (now_iso(),),
        )
        conn.commit()
        return cur.rowcount


# ---------------------------------------------------------------------------
# SyncAdapter + run_sync
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SyncAdapter:
    """What run_sync needs from a concrete integration (e.g. Asana -> Supabase).

    fetch_since(cursor) -> (items, next_cursor): pull one batch from the upstream source.
    key_of(item) -> idempotency key (e.g. an Asana task gid).
    apply(item) -> None: write one item to the sync target (raise to signal failure).
    modified_at_of(item) -> upstream-modified timestamp, used for last-writer-wins ordering
        when draining the outbox — reconciliation is keyed on this, never wall-clock receipt
        order.
    """

    entity: str
    fetch_since: Callable[[str | None], tuple[list[dict[str, Any]], str | None]]
    key_of: Callable[[dict[str, Any]], str]
    apply: Callable[[dict[str, Any]], None]
    modified_at_of: Callable[[dict[str, Any]], str | None] = lambda item: None


def _drain_outbox(outbox: Outbox, adapter: SyncAdapter) -> tuple[int, list[str]]:
    """Apply every pending outbox row, oldest upstream-modified first.

    Outbox rows are already deduped one-per-idempotency-key (Outbox.enqueue upserts), so this
    isn't resolving a multi-way conflict so much as guaranteeing a deterministic apply order —
    per spec, that order is Asana's own ``modified_at``, not receipt/wall-clock time.
    """
    pending = outbox.pending(limit=10_000)

    def sort_key(row: dict[str, Any]) -> datetime:
        return _parse_iso(adapter.modified_at_of(row["payload"])) or datetime.min.replace(tzinfo=timezone.utc)

    pending.sort(key=sort_key)
    applied = 0
    errors: list[str] = []
    for row in pending:
        try:
            adapter.apply(row["payload"])
            outbox.mark_synced(row["idempotency_key"])
            applied += 1
        except Exception as exc:  # noqa: BLE001 - recorded, not swallowed
            msg = f"{type(exc).__name__}: {exc}"
            outbox.mark_failed(row["idempotency_key"], msg)
            errors.append(msg)
    return applied, errors


def _record_run(*, entity: str, owner: str, status: str, started_at: str, finished_at: str,
                 duration_ms: float, rows: int, errors: list[str], degraded: bool) -> int:
    _ensure_asana_sync_runs_columns()
    conn = storage._conn()
    mode = "degraded" if degraded else "incremental"
    counts = {"rows": rows, "errors": len(errors)}
    cur = conn.execute(
        "INSERT INTO asana_sync_runs (mode, status, started_at, finished_at, counts, error, "
        "entity, degraded, lease_owner, duration_ms) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (mode, status, started_at, finished_at, json.dumps(counts), "; ".join(errors)[:1000],
         entity, 1 if degraded else 0, owner, duration_ms),
    )
    conn.commit()
    return cur.lastrowid


def list_runs(limit: int = 20, *, entity: str | None = None) -> list[dict[str, Any]]:
    """Structured observability read access over the (reused) asana_sync_runs table."""
    conn = storage._conn()
    try:
        conn.execute("SELECT 1 FROM asana_sync_runs LIMIT 1")
    except sqlite3.OperationalError:
        return []
    sql = "SELECT * FROM asana_sync_runs"
    params: list[Any] = []
    if entity:
        sql += " WHERE entity=?"
        params.append(entity)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(min(max(limit, 1), 200))
    rows = conn.execute(sql, params).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["counts"] = json.loads(d.get("counts") or "{}")
        except (TypeError, ValueError):
            d["counts"] = {}
        d["degraded"] = bool(d.get("degraded") or 0)
        out.append(d)
    return out


def run_sync(*, adapter: SyncAdapter, lease_owner: str, health_check: Callable[[], bool],
             lease_ttl_s: float = 120.0, now: ClockFn | None = None,
             lease: SyncLease | None = None, checkpoint: Checkpoint | None = None,
             outbox: Outbox | None = None) -> dict[str, Any]:
    """One entry point for both the hosted (Edge Function-equivalent) and local-fallback path.

    - Acquires ``adapter.entity``'s lease under ``lease_owner`` first; if another owner holds
      a live lease, returns immediately with status "skipped" and does no work at all (this is
      what makes two concurrent invocations safe — see module docstring).
    - If ``health_check()`` is false: degrades — instead of writing directly, fetched items are
      enqueued into the Outbox, and a visible ``degraded`` flag is set on the recorded run.
    - If healthy: first drains any pending Outbox rows (recovery-from-degraded case) before
      pulling new work, then applies new items directly and advances the Checkpoint.
    - The Checkpoint is only advanced after the batch's items have been durably committed
      somewhere (either applied directly, or queued into the Outbox) — never before.
    """
    _now = now or _default_clock
    started_dt = _now()
    lease = lease or SyncLease(adapter.entity, now=_now)
    checkpoint = checkpoint or Checkpoint()
    outbox = outbox or Outbox()

    if not lease.acquire(lease_owner, lease_ttl_s):
        return {
            "entity": adapter.entity, "status": "skipped", "reason": "lease_held",
            "degraded": False, "rows": 0, "errors": [],
        }

    rows = 0
    errors: list[str] = []
    degraded = False
    try:
        healthy = bool(health_check())
        if healthy:
            drained, drain_errors = _drain_outbox(outbox, adapter)
            rows += drained
            errors.extend(drain_errors)

            cursor = checkpoint.get(adapter.entity)
            items, next_cursor = adapter.fetch_since(cursor)
            applied = 0
            for item in items:
                try:
                    adapter.apply(item)
                    applied += 1
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{type(exc).__name__}: {exc}")
            rows += applied
            if next_cursor is not None and not errors:
                checkpoint.advance(adapter.entity, next_cursor)
        else:
            degraded = True
            cursor = checkpoint.get(adapter.entity)
            items, next_cursor = adapter.fetch_since(cursor)
            for item in items:
                outbox.enqueue(adapter.entity, "upsert", item, adapter.key_of(item))
                rows += 1
            if next_cursor is not None:
                # The upstream (Asana) fetch itself succeeded and its results are durably
                # queued in the Outbox — that is the "successful batch commit" this cursor
                # tracks. Downstream (Supabase) delivery status is tracked separately, per
                # row, by the Outbox's own pending/synced/failed status.
                checkpoint.advance(adapter.entity, next_cursor)
    finally:
        lease.release()

    finished_dt = _now()
    duration_ms = (finished_dt - started_dt).total_seconds() * 1000
    status = "error" if errors else "done"
    run_id = _record_run(
        entity=adapter.entity, owner=lease_owner, status=status,
        started_at=started_dt.isoformat(), finished_at=finished_dt.isoformat(),
        duration_ms=duration_ms, rows=rows, errors=errors, degraded=degraded,
    )
    return {
        "run_id": run_id, "entity": adapter.entity, "status": status, "degraded": degraded,
        "rows": rows, "errors": errors, "duration_ms": duration_ms,
    }


# ---------------------------------------------------------------------------
# Concrete adapter: Asana tasks -> Supabase conductor_records
# ---------------------------------------------------------------------------
def asana_tasks_adapter(*, session: Any = None) -> SyncAdapter:
    """The concrete SyncAdapter both the hosted Edge Function's logic and this local fallback
    are meant to mirror: Asana's task-search API as the source, Supabase's conductor_records
    mirror as the sink.

    Idempotency key: the Asana task ``gid`` — the SAME key already used by
    ``supabase_sync.local_adapters``/``_push_entity`` (``entity_type='asana_tasks'``,
    ``record_key=gid``), matched here deliberately rather than inventing a second convention.
    Reuses ``asana_sync``'s paced/retrying HTTP client (rate limiting, 429/5xx backoff) and
    ``supabase_sync``'s existing upsert shape (``on_conflict=entity_type,record_key``,
    ``Prefer: resolution=merge-duplicates``) unchanged.
    """
    import asana_sync
    import supabase_sync

    http_session = session if session is not None else supabase_sync.requests

    def fetch_since(cursor: str | None) -> tuple[list[dict[str, Any]], str | None]:
        headers = asana_sync._headers()
        cfg = asana_sync._load_config()
        ws_gid = cfg.get("workspace_gid") or asana_sync.DEFAULT_WORKSPACE_GID
        started = now_iso()
        items: list[dict[str, Any]] = []
        if cursor:
            # See asana_sync.py for the modified_at.after vs modified_since note — same field.
            params_base = {"opt_fields": asana_sync.TASK_OPT_FIELDS, "modified_at.after": cursor}
            for completed_flag in ("false", "true"):
                params = dict(params_base, completed=completed_flag)
                items.extend(asana_sync.paginate(headers, f"/workspaces/{ws_gid}/tasks/search", params))
        else:
            # No checkpoint yet: bootstrap with a full per-project scan, same as asana_sync's
            # own mode="all"/mode="incremental" bootstrap, for guaranteed first-run coverage.
            projects = asana_sync.paginate(
                headers, "/projects", {"workspace": ws_gid, "opt_fields": asana_sync.PROJECT_OPT_FIELDS}
            )
            for proj in projects:
                if proj.get("archived"):
                    continue
                params = {"project": proj["gid"], "opt_fields": asana_sync.TASK_OPT_FIELDS}
                items.extend(asana_sync.paginate(headers, "/tasks", params))
        return items, started

    def key_of(item: dict[str, Any]) -> str:
        gid = str(item.get("gid") or "").strip()
        if not gid:
            raise ValueError("Asana task payload missing gid")
        return gid

    def modified_at_of(item: dict[str, Any]) -> str | None:
        return item.get("modified_at")

    def apply(item: dict[str, Any]) -> None:
        gid = key_of(item)
        supabase_sync._request(
            "POST",
            "conductor_records",
            session=http_session,
            params={"on_conflict": "entity_type,record_key"},
            json_body=[{
                "entity_type": "asana_tasks",
                "record_key": gid,
                "payload": item,
                "source_updated_at": item.get("modified_at"),
            }],
            headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
        )

    return SyncAdapter(
        entity="asana_tasks", fetch_since=fetch_since, key_of=key_of,
        apply=apply, modified_at_of=modified_at_of,
    )
