"""Team-first Asana KPI query service.

KPI facts use Team + Metric + Period as the summary key. Owners remain drilldown
attributes only. The implementation follows the Global KPIs workbook contract:
Sunday-Saturday weekly buckets, correct weighted rollups, ratio numerator /
denominator output, snapshot metrics, and cell-exact drilldown records.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException

import storage

router = APIRouter(prefix="/api/asana/kpis", tags=["asana-kpis"])

METRICS = {
    "count_tasks": {"label": "Tasks Created", "unit": "count", "date_basis": "created_at"},
    "count_completed": {"label": "Tasks Completed", "unit": "count", "date_basis": "completed_at"},
    "weighted_completions": {"label": "Weighted Completions", "unit": "points", "date_basis": "completed_at"},
    "completion_rate": {"label": "Task Completion Rate", "unit": "percent", "date_basis": "created_at"},
    "sla_adherence": {"label": "Internal SLA", "unit": "percent", "date_basis": "completed_at"},
    "avg_cycle_time_days": {"label": "Average Time to Close", "unit": "days", "date_basis": "completed_at"},
    "overdue_count": {"label": "Overdue Tasks", "unit": "count_snapshot", "date_basis": "snapshot"},
    "overdue_rate": {"label": "Overdue Tasks % of Total", "unit": "percent_snapshot", "date_basis": "snapshot"},
    "sla_missed_count": {"label": "Initial SLA Missed", "unit": "count", "date_basis": "completed_at"},
}
DIMENSIONS = {"team", "project", "section", "assignee", "week", "month"}
DATE_BASES = {"created_at", "completed_at", "modified_at", "due_on"}


def _parse_dt(value: str | None, end_of_day: bool = False) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if len(text) == 10:
            dt = datetime.fromisoformat(text)
            if end_of_day:
                dt += timedelta(days=1)
            return dt.replace(tzinfo=timezone.utc)
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _day(value: str | None) -> date | None:
    dt = _parse_dt(value)
    return dt.date() if dt else None


def _week_start(day: date) -> date:
    # Workbook definition: Sunday through Saturday.
    return day - timedelta(days=(day.weekday() + 1) % 7)


def _period(day: date, grain: str) -> tuple[str, str]:
    if grain == "week":
        start = _week_start(day)
        return start.isoformat(), (start + timedelta(days=7)).isoformat()
    if grain == "month":
        start = day.replace(day=1)
        nxt = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        return start.isoformat(), nxt.isoformat()
    raise HTTPException(422, "period_grain must be 'week' or 'month'")


def _dimensions(task: dict, memberships: list[dict]) -> list[dict]:
    """Return one contribution per unique team/project membership.

    A global distinct task total is not equal to a sum of all team
    contributions. Responses state membership attribution explicitly.
    """
    out, seen = [], set()
    for m in memberships:
        team = str(m.get("team_name") or "Unassigned")
        project = str(m.get("project_name") or "No Project")
        key = (team, project, str(m.get("section_name") or ""))
        if key in seen:
            continue
        seen.add(key)
        out.append({"team": team, "project": project, "section": str(m.get("section_name") or "No Section")})
    if not out:
        out.append({
            "team": str(task.get("team_name") or "Unassigned"),
            "project": str(task.get("project_name") or "No Project"),
            "section": str(task.get("section") or "No Section"),
        })
    return out


def _all_facts() -> tuple[list[dict], dict[str, list[dict]], dict[str, list[dict]]]:
    conn = storage._conn()
    tasks = [dict(r) for r in conn.execute("SELECT * FROM asana_tasks").fetchall()]
    memberships: dict[str, list[dict]] = defaultdict(list)
    for r in conn.execute("SELECT * FROM asana_task_memberships").fetchall():
        memberships[r["task_gid"]].append(dict(r))
    cf_values: dict[str, list[dict]] = defaultdict(list)
    for r in conn.execute("SELECT * FROM asana_task_custom_field_values").fetchall():
        cf_values[r["task_gid"]].append(dict(r))
    return tasks, memberships, cf_values


def _matches_date(task: dict, basis: str, start: date | None, end: date | None) -> bool:
    dt = _day(task.get(basis))
    if not dt:
        return False
    return (start is None or dt >= start) and (end is None or dt < end)


def _bucket_value(task: dict, dim: str, contribution: dict, basis: str) -> tuple[str, str] | None:
    if dim in ("team", "project", "section"):
        return contribution[dim], contribution[dim]
    if dim == "assignee":
        name = str(task.get("assignee_name") or "Unassigned")
        return name, name
    dt = _day(task.get(basis))
    if not dt:
        return None
    start, end = _period(dt, dim)
    return start, end


def _metric_contribution(metric: str, task: dict, cf_values: list[dict], period_end: date) -> tuple[float | None, float | None, list[str], list[str]]:
    """Return numerator, denominator, numerator record roles, denominator roles."""
    gid = str(task["gid"])
    done = bool(task.get("completed"))
    if metric == "count_tasks":
        return 1.0, None, [gid], []
    if metric == "count_completed":
        return (1.0 if done else 0.0), None, ([gid] if done else []), []
    if metric == "weighted_completions":
        value = float(task.get("weight") or 1.0) if done else 0.0
        return value, None, ([gid] if done else []), []
    if metric == "completion_rate":
        return (1.0 if done else 0.0), 1.0, ([gid] if done else []), [gid]
    if metric in ("sla_adherence", "avg_cycle_time_days"):
        if not done:
            return 0.0, 0.0, [], []
        completed = _parse_dt(task.get("completed_at"))
        if metric == "sla_adherence":
            due = _parse_dt(task.get("due_on"), end_of_day=True)
            if not completed or not due:
                return 0.0, 0.0, [], []
            return (1.0 if completed <= due else 0.0), 1.0, ([gid] if completed <= due else []), [gid]
        created = _parse_dt(task.get("created_at"))
        if not completed or not created or completed < created:
            return 0.0, 0.0, [], []
        return (completed - created).total_seconds() / 86400.0, 1.0, [gid], [gid]
    if metric in ("overdue_count", "overdue_rate"):
        due = _day(task.get("due_on"))
        is_open = not done
        overdue = bool(is_open and due and due < period_end)
        if metric == "overdue_count":
            return (1.0 if overdue else 0.0), None, ([gid] if overdue else []), []
        return (1.0 if overdue else 0.0), (1.0 if is_open else 0.0), ([gid] if overdue else []), ([gid] if is_open else [])
    if metric == "sla_missed_count":
        missed = any("sla" in str(v.get("field_name") or "").lower() and "miss" in str(v.get("field_name") or "").lower() and str(v.get("value_text") or "").lower() in ("yes", "true", "missed", "failed") for v in cf_values)
        return (1.0 if missed else 0.0), None, ([gid] if missed else []), []
    raise HTTPException(422, f"Unsupported metric '{metric}'")


def _value(metric: str, numerator: float, denominator: float | None) -> float | None:
    if metric in ("completion_rate", "sla_adherence", "overdue_rate", "avg_cycle_time_days"):
        return None if not denominator else numerator / denominator
    return numerator


def _persist_fact(team: str, metric: str, grain: str, start: str, end: str, numerator: float, denominator: float | None, value: float | None) -> None:
    conn = storage._conn()
    meta = {"attribution": "membership", "definition_version": "global-kpis-workbook-v1"}
    conn.execute(
        "INSERT INTO asana_kpi_facts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(team,kpi_id,period_grain,period_start,snapshot_at) DO UPDATE SET numerator=excluded.numerator,denominator=excluded.denominator,value=excluded.value,updated_at=excluded.updated_at,metadata=excluded.metadata",
        (team, metric, grain, start, end, "", numerator, denominator, value, METRICS[metric]["unit"], None, "asana", "live_asana_membership", "global-kpis-v1", json.dumps(meta), storage.now_iso()),
    )
    conn.commit()


@router.post("/pivot")
def pivot(body: dict) -> dict:
    metric = str(body.get("metric") or "count_completed")
    row_dim = str(body.get("row_dimension") or "team")
    column_dim = str(body.get("column_dimension") or "week")
    grain = str(body.get("period_grain") or "week")
    date_basis = str(body.get("date_basis") or METRICS.get(metric, {}).get("date_basis") or "completed_at")
    if metric not in METRICS or row_dim not in DIMENSIONS or column_dim not in DIMENSIONS or date_basis not in DATE_BASES or grain not in {"week", "month"}:
        raise HTTPException(422, "Invalid metric, dimension, date basis, or period grain")
    if metric.startswith("overdue"):
        date_basis = "due_on"
    start = _day(body.get("date_from")) if body.get("date_from") else None
    end = _day(body.get("date_to")) if body.get("date_to") else None
    teams = {str(x) for x in (body.get("teams") or []) if str(x)}
    projects = {str(x) for x in (body.get("projects") or []) if str(x)}

    cells: dict[tuple[str, str], dict] = {}
    tasks, memberships, cf_values = _all_facts()
    for task in tasks:
        # Snapshot metrics need task state as of the selected end (or now); date
        # range means the selected period cannot be empty merely because due_on is blank.
        if metric not in ("overdue_count", "overdue_rate") and not _matches_date(task, date_basis, start, end):
            continue
        for contribution in _dimensions(task, memberships.get(task["gid"], [])):
            if teams and contribution["team"] not in teams:
                continue
            if projects and contribution["project"] not in projects:
                continue
            r = _bucket_value(task, row_dim, contribution, date_basis)
            c = _bucket_value(task, column_dim, contribution, date_basis)
            if not r or not c:
                continue
            key = (r[0], c[0])
            cell = cells.setdefault(key, {"row": r[0], "column": c[0], "numerator": 0.0, "denominator": 0.0, "records": {}, "period_end": c[1]})
            period_end = date.fromisoformat(c[1]) if column_dim in {"week", "month"} else (end or date.today() + timedelta(days=1))
            n, d, n_ids, d_ids = _metric_contribution(metric, task, cf_values.get(task["gid"], []), period_end)
            cell["numerator"] += n or 0.0
            if d is not None:
                cell["denominator"] += d
            cell["records"].setdefault("numerator", set()).update(n_ids)
            cell["records"].setdefault("denominator", set()).update(d_ids)

    out_cells = []
    for cell in cells.values():
        denominator = cell["denominator"] if metric in ("completion_rate", "sla_adherence", "overdue_rate", "avg_cycle_time_days") else None
        value = _value(metric, cell["numerator"], denominator)
        out_cells.append({
            "row": cell["row"], "column": cell["column"], "numerator": cell["numerator"], "denominator": denominator,
            "value": value, "record_counts": {k: len(v) for k, v in cell["records"].items()},
            "record_ids": {k: sorted(v) for k, v in cell["records"].items()},
        })
        if row_dim == "team" and column_dim in {"week", "month"}:
            period_start = cell["column"]
            pstart = date.fromisoformat(period_start)
            pend = _period(pstart, column_dim)[1]
            _persist_fact(cell["row"], metric, grain, period_start, pend, cell["numerator"], denominator, value)

    return {
        "metric": {"id": metric, **METRICS[metric]}, "row_dimension": row_dim, "column_dimension": column_dim,
        "date_basis": date_basis, "period_grain": grain, "attribution": "membership",
        "cells": sorted(out_cells, key=lambda x: (x["row"], x["column"])),
        "row_keys": sorted({x["row"] for x in out_cells}), "column_keys": sorted({x["column"] for x in out_cells}),
    }


@router.post("/drilldown")
def drilldown(body: dict) -> dict:
    """Return exact task records contributing to a team/time metric cell."""
    result = pivot({
        "metric": body.get("metric"), "row_dimension": "team", "column_dimension": body.get("period_grain", "week"),
        "period_grain": body.get("period_grain", "week"), "date_basis": body.get("date_basis"),
        "date_from": body.get("period_start"), "date_to": body.get("period_end"), "teams": [body.get("team")],
    })
    target = next((c for c in result["cells"] if c["row"] == body.get("team") and c["column"] == body.get("period_start")), None)
    if not target:
        return {"count": 0, "records": [], "scope": result}
    task_ids = set(target.get("record_ids", {}).get("numerator", []))
    task_ids.update(target.get("record_ids", {}).get("denominator", []))
    tasks, _, _ = _all_facts()
    records = [
        {k: task.get(k) for k in ("gid", "name", "project_name", "section", "team_name", "assignee_name", "created_at", "completed_at", "due_on", "completed", "weight", "permalink")}
        for task in tasks if task["gid"] in task_ids
    ]
    offset = max(0, int(body.get("offset") or 0)); limit = min(200, max(1, int(body.get("limit") or 50)))
    return {"count": len(records), "records": records[offset:offset + limit], "next_offset": offset + limit if offset + limit < len(records) else None, "scope": result}


def seed_definitions(spec: dict) -> int:
    """Persist the reviewed Global KPI workbook definition catalog locally.

    `team_kpi_catalog` is the authoritative team map. Legacy owners are never
    used as a key. Undefined workbook rows are preserved as needs_definition.
    """
    definitions = {item["id"]: item for item in (spec.get("metric_definitions") or []) if item.get("id")}
    catalog = spec.get("team_kpi_catalog") or {}
    conn = storage._conn(); now = storage.now_iso(); saved = 0
    for team, entries in catalog.items():
        for entry in entries:
            detail = {"id": entry} if isinstance(entry, str) else dict(entry)
            base = definitions.get(detail.get("id"), {})
            metric_id = str(detail.get("id") or "").strip()
            if not metric_id: continue
            label = str(detail.get("label") or base.get("label") or metric_id.replace("_", " ").title())
            unit = str(detail.get("unit") or base.get("unit") or "needs_definition")
            filters = detail.get("filters") or base.get("filters") or []
            source = detail.get("source") or base.get("workbook_source") or ""
            status = detail.get("status") or base.get("status") or "active"
            conn.execute(
                "INSERT INTO asana_kpi_definitions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(kpi_id) DO UPDATE SET team=excluded.team,label=excluded.label,unit=excluded.unit,target_value=excluded.target_value,target_direction=excluded.target_direction,numerator_definition=excluded.numerator_definition,denominator_definition=excluded.denominator_definition,filters=excluded.filters,rollup_policy=excluded.rollup_policy,workbook_source=excluded.workbook_source,definition_status=excluded.definition_status,metadata=excluded.metadata,updated_at=excluded.updated_at",
                (f"{team.lower().replace(' ', '_')}:{metric_id}", team, label, unit, detail.get("target_value", base.get("target_value")), detail.get("target_direction", "higher_is_better"), str(detail.get("numerator") or base.get("numerator") or ""), str(detail.get("denominator") or base.get("denominator") or ""), json.dumps(filters), str(detail.get("rollup_policy") or base.get("rollup_policy") or "sum"), source, status, json.dumps({"metric_id": metric_id, "workbook_spec_version": spec.get("spec_version", "")}), now),
            )
            saved += 1
    for item in spec.get("undefined_workbook_rows") or []:
        team = item.get("team", "Unknown")
        for label in item.get("kpis") or []:
            key = f"{team.lower().replace(' ', '_')}:undefined:{label.lower().replace(' ', '_')}"
            conn.execute("INSERT INTO asana_kpi_definitions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(kpi_id) DO UPDATE SET definition_status='needs_definition',updated_at=excluded.updated_at", (key, team, label, "needs_definition", None, "higher_is_better", "", "", "[]", "manual", item.get("source", ""), "needs_definition", json.dumps({"source_note": item.get("status", "")}), now))
            saved += 1
    conn.commit(); return saved


@router.post("/definitions/import")
def import_definitions(body: dict) -> dict:
    spec = body.get("spec") or body
    if not isinstance(spec.get("team_kpi_catalog"), dict):
        raise HTTPException(422, "Expected Global KPI definition spec with team_kpi_catalog")
    return {"ok": True, "definitions_saved": seed_definitions(spec)}


@router.get("/definitions")
def definitions() -> dict:
    return {"definitions": storage.asana_kpi_definition_rows(), "metrics": METRICS, "attribution": "team membership; owner is drilldown-only"}


@router.get("/facts")
def facts(team: str | None = None, grain: str | None = None) -> dict:
    return {"facts": storage.asana_kpi_fact_rows(team, grain)}
