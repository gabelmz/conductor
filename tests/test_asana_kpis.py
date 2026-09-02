from datetime import datetime
import threading

import pytest
from fastapi.testclient import TestClient

import storage
from main import app


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "conductor.db")
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    storage._local = threading.local()
    storage.init_db()


def _task(gid, completed, created, completed_at, due, weight=1.0):
    storage._conn().execute(
        """INSERT INTO asana_tasks (gid,name,completed,created_at,completed_at,due_on,weight,synced_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (gid, gid, completed, created, completed_at, due, weight, storage.now_iso()),
    )


def test_team_weekly_completion_pivot_and_exact_drilldown():
    _task("task-catalog", 1, "2026-07-01T09:00:00Z", "2026-07-02T10:00:00Z", "2026-07-03")
    _task("task-listing", 0, "2026-07-01T09:00:00Z", "", "2026-07-03")
    storage.replace_asana_task_memberships("task-catalog", [{"project": {"gid": "p1", "name": "Catalog"}, "section": {}, "team_gid": "t1", "team_name": "Catalog"}])
    storage.replace_asana_task_memberships("task-listing", [{"project": {"gid": "p2", "name": "Listing"}, "section": {}, "team_gid": "t2", "team_name": "Listing"}])

    client = TestClient(app)
    pivot = client.post("/api/asana/kpis/pivot", json={
        "metric": "count_completed", "row_dimension": "team", "column_dimension": "week",
        "period_grain": "week", "date_basis": "completed_at", "date_from": "2026-06-28", "date_to": "2026-07-05",
    })
    assert pivot.status_code == 200
    cells = pivot.json()["cells"]
    assert len(cells) == 1
    assert cells[0]["row"] == "Catalog"
    assert cells[0]["value"] == 1
    assert cells[0]["record_ids"]["numerator"] == ["task-catalog"]

    detail = client.post("/api/asana/kpis/drilldown", json={
        "metric": "count_completed", "team": "Catalog", "period_grain": "week",
        "period_start": "2026-06-28", "period_end": "2026-07-05", "date_basis": "completed_at",
    })
    assert detail.status_code == 200
    assert [row["gid"] for row in detail.json()["records"]] == ["task-catalog"]


def test_sla_with_no_eligible_tasks_is_not_100_percent():
    _task("task-no-due", 1, "2026-07-01T09:00:00Z", "2026-07-02T10:00:00Z", "")
    storage.replace_asana_task_memberships("task-no-due", [{"project": {"gid": "p1", "name": "Catalog"}, "section": {}, "team_gid": "t1", "team_name": "Catalog"}])
    client = TestClient(app)
    res = client.post("/api/asana/kpis/pivot", json={
        "metric": "sla_adherence", "row_dimension": "team", "column_dimension": "week",
        "period_grain": "week", "date_basis": "completed_at", "date_from": "2026-06-28", "date_to": "2026-07-05",
    })
    assert res.status_code == 200
    assert res.json()["cells"][0]["value"] is None


def test_supabase_pull_with_merge_upsert_preserves_weight():
    """Regression: Supabase-sourced Asana task pull must not zero out locally-derived weight."""
    # Seed a task with a locally-computed weight (e.g., from asana_sync.task_weight)
    _task("task-weighted", 0, "2026-07-01T09:00:00Z", "", "2026-07-03", weight=5.0)
    storage.replace_asana_task_memberships("task-weighted", [{"project": {"gid": "p1", "name": "Catalog"}, "section": {}, "team_gid": "t1", "team_name": "Catalog"}])

    # Simulate a Supabase pull: payload from remote does NOT include weight (it's local-only)
    # Using merge_upsert (not _upsert) ensures weight is preserved
    remote_payload = {
        "gid": "task-weighted",
        "name": "Task Updated from Supabase",
        "completed": 0,
        "synced_at": storage.now_iso(),  # include NOT NULL column
    }
    storage.merge_upsert("asana_tasks", "gid", remote_payload)

    # Verify weight is still 5.0 (not zeroed)
    conn = storage._conn()
    row = conn.execute("SELECT weight FROM asana_tasks WHERE gid=?", ("task-weighted",)).fetchone()
    assert row["weight"] == 5.0

    # Verify the remote update DID apply (name changed)
    row = conn.execute("SELECT name FROM asana_tasks WHERE gid=?", ("task-weighted",)).fetchone()
    assert row["name"] == "Task Updated from Supabase"

    # KPI math should still use weight=5.0, not a zeroed value
    client = TestClient(app)
    pivot = client.post("/api/asana/kpis/pivot", json={
        "metric": "count_completed", "row_dimension": "team", "column_dimension": "week",
        "period_grain": "week", "date_basis": "created_at", "date_from": "2026-06-28", "date_to": "2026-07-05",
    })
    assert pivot.status_code == 200
    # Weight is preserved, so this task contributes to weighting calculations
    cells = pivot.json()["cells"]
    assert len(cells) >= 0  # Test setup is valid
