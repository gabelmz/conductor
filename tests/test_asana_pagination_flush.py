"""Tests that a bulk Asana pull commits in batches of 500 rows instead of once per row.

Before this fix, every ``storage._upsert`` call (and the per-task membership/custom-field
writers) committed unconditionally, so a large workspace pull meant one fsync'd SQLite
commit per row — e.g. ~266k commits for a 266k-task org (see asana_sync.sync_all's
docstring). ``storage.batch_writes()`` batches those commits every N rows instead.
"""
from __future__ import annotations

import sqlite3
import sys
import threading
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))
sys.path.insert(0, str(APP_DIR / "backend"))

import asana_sync
import storage


@pytest.fixture(autouse=True)
def setup_temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_conductor.db"
    monkeypatch.setattr(storage, "DB_PATH", db_file)
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    storage._local = threading.local()
    storage.init_db()
    yield db_file


class _CommitCountingConn:
    """Transparent proxy around the real thread-local connection that counts .commit()
    calls. sqlite3.Connection is a C type — its methods can't be monkeypatched directly
    (setattr raises 'read-only' on both the class and instances), so this wraps it instead."""

    def __init__(self, real: sqlite3.Connection, counts: dict):
        object.__setattr__(self, "_real", real)
        object.__setattr__(self, "_counts", counts)

    def commit(self):
        self._counts["n"] += 1
        return self._real.commit()

    def __getattr__(self, name):
        return getattr(self._real, name)


@pytest.fixture
def commit_counter(monkeypatch):
    """Count commits issued (via storage._conn()) during the test body."""
    counts = {"n": 0}
    real_conn_fn = storage._conn
    proxy = _CommitCountingConn(real_conn_fn(), counts)
    monkeypatch.setattr(storage, "_conn", lambda: proxy)
    return counts


def test_batch_writes_commits_every_flush_every_rows(commit_counter):
    with storage.batch_writes(500):
        for i in range(1200):
            storage.upsert_asana_workspace(gid=str(i), name=f"ws{i}")
    # 1200 rows at flush_every=500 -> commits at row 500, row 1000, and the final
    # commit on context exit for the trailing 200 = 3, not 1200.
    assert commit_counter["n"] == 3
    assert storage._conn().execute("SELECT COUNT(*) c FROM asana_workspaces").fetchone()["c"] == 1200


def test_batch_writes_final_commit_on_partial_batch(commit_counter):
    with storage.batch_writes(500):
        for i in range(1499):
            storage.upsert_asana_workspace(gid=str(i), name=f"ws{i}")
    # Two full flushes (500, 1000) plus the guaranteed final commit for the last 499 —
    # without that final commit, those 499 rows would sit uncommitted forever.
    assert commit_counter["n"] == 3
    assert storage._conn().execute("SELECT COUNT(*) c FROM asana_workspaces").fetchone()["c"] == 1499


def test_batch_writes_flushes_on_exception(commit_counter):
    class Boom(Exception):
        pass

    with pytest.raises(Boom):
        with storage.batch_writes(500):
            for i in range(50):
                storage.upsert_asana_workspace(gid=str(i), name=f"ws{i}")
            raise Boom("network died mid-pull")
    # An interrupted pull must not lose already-fetched rows: the context manager's
    # finally-commit runs even when the body raises.
    assert commit_counter["n"] == 1
    assert storage._conn().execute("SELECT COUNT(*) c FROM asana_workspaces").fetchone()["c"] == 50


def test_outside_batch_writes_still_commits_every_row(commit_counter):
    """Unrelated call sites (not wrapped in batch_writes) keep committing every row —
    batching is opt-in per thread, not a global behavior change."""
    for i in range(5):
        storage.upsert_asana_workspace(gid=str(i), name=f"ws{i}")
    assert commit_counter["n"] == 5


def _fake_paginate(headers, path, params=None):
    params = params or {}
    if path == "/workspaces":
        return [{"gid": "ws1", "name": "Workspace"}]
    if path.endswith("/users"):
        return []
    if path.endswith("/teams"):
        return []
    if path == "/projects":
        return [{"gid": "p1", "name": "Project 1", "archived": False}]
    if path == "/tasks" and params.get("project") == "p1":
        return [
            {"gid": f"t{i}", "name": f"Task {i}", "resource_type": "task",
             "created_at": "2026-01-01T00:00:00Z", "modified_at": "2026-01-01T00:00:00Z"}
            for i in range(1200)
        ]
    return []


def test_sync_all_batches_commits_for_a_large_task_pull(monkeypatch, commit_counter):
    """End-to-end: a 1200-task 'all' sync commits far fewer than 1-per-task."""
    monkeypatch.setattr(asana_sync, "_headers", lambda: {"Authorization": "Bearer fake"})
    monkeypatch.setattr(asana_sync, "paginate", _fake_paginate)

    counts = asana_sync.sync_all(mode="all", deep=False)

    assert counts["tasks"] == 1200
    assert storage._conn().execute("SELECT COUNT(*) c FROM asana_tasks").fetchone()["c"] == 1200
    # Each task writes 3 rows (task, memberships replace, custom-fields replace) plus a
    # handful of setup rows (workspace, project) = ~3603 _maybe_commit calls at
    # flush_every=500 -> ceil(3603/500) = 8 flush commits, plus record_asana_run's own
    # unconditional commit (outside the batch) = 9. The important thing verified here is
    # "far fewer than one per task" (1200+), not the exact constant.
    assert commit_counter["n"] < 20
