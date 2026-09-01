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
