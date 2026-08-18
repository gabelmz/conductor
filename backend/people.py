"""Conductor — People data type.

A lightweight directory of people / roles / teams. The `people` table keeps the
well-known fields (name/role/email/team/notes) as real columns and merges any
unknown or extra keys into an `attributes` JSON column, so arbitrary CSV/JSON
imports never lose data (schema-flexible by design).

Router prefix: /api/people
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Make sibling backend modules importable whether this file is loaded as
# `backend.people` (repo root) or `people` (backend dir on sys.path, uvicorn).
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import APIRouter, HTTPException

import storage

router = APIRouter(prefix="/api/people", tags=["people"])

# Columns with their own table slot; everything else merges into attributes.
KNOWN_FIELDS = ("name", "role", "email", "team", "notes")


def init_people_db() -> None:
    conn = storage._conn()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS people (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            role TEXT DEFAULT '',
            email TEXT DEFAULT '',
            team TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            attributes TEXT DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


def _decode(row) -> dict:
    d = dict(row)
    try:
        d["attributes"] = json.loads(d.get("attributes") or "{}")
    except Exception:
        d["attributes"] = {}
    return d


def _split_attrs(body: dict) -> dict:
    """Collect every key that isn't a known column into an attributes dict.

    An explicit `attributes` dict in the body is merged in (unknown top-level
    keys win over it), which keeps both import shapes working.
    """
    attrs = {}
    for k, v in body.items():
        if k in KNOWN_FIELDS or k in ("id", "attributes", "created_at", "updated_at"):
            continue
        attrs[k] = v
    extra = body.get("attributes") or {}
    if isinstance(extra, dict):
        attrs = {**extra, **attrs}
    return attrs


def create_person(body: dict) -> dict:
    """Insert a person; unknown keys merge into `attributes`. Returns the row."""
    name = str(body.get("name") or "").strip()
    if not name:
        raise ValueError("name is required")
    attrs = _split_attrs(body)
    ts = storage.now_iso()
    conn = storage._conn()
    cur = conn.execute(
        "INSERT INTO people (name, role, email, team, notes, attributes, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (
            name,
            str(body.get("role") or ""),
            str(body.get("email") or ""),
            str(body.get("team") or ""),
            str(body.get("notes") or ""),
            json.dumps(attrs),
            ts,
            ts,
        ),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM people WHERE id=?", (cur.lastrowid,)).fetchone()
    return _decode(row)


def list_people() -> list[dict]:
    rows = storage._conn().execute(
        "SELECT * FROM people ORDER BY name COLLATE NOCASE, id"
    ).fetchall()
    return [_decode(r) for r in rows]


def get_person(person_id: int) -> dict | None:
    row = storage._conn().execute("SELECT * FROM people WHERE id=?", (person_id,)).fetchone()
    return _decode(row) if row else None


def update_person(person_id: int, body: dict) -> dict | None:
    conn = storage._conn()
    row = conn.execute("SELECT * FROM people WHERE id=?", (person_id,)).fetchone()
    if not row:
        return None
    current = _decode(row)
    merged = {**current, **body}
    name = str(merged.get("name") or "").strip()
    if not name:
        raise ValueError("name is required")
    attrs = _split_attrs(body)
    merged_attrs = {**(current.get("attributes") or {}), **attrs}
    ts = storage.now_iso()
    conn.execute(
        "UPDATE people SET name=?, role=?, email=?, team=?, notes=?, attributes=?, updated_at=? "
        "WHERE id=?",
        (
            name,
            str(merged.get("role") or ""),
            str(merged.get("email") or ""),
            str(merged.get("team") or ""),
            str(merged.get("notes") or ""),
            json.dumps(merged_attrs),
            ts,
            person_id,
        ),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM people WHERE id=?", (person_id,)).fetchone()
    return _decode(row)


def delete_person(person_id: int) -> bool:
    conn = storage._conn()
    cur = conn.execute("DELETE FROM people WHERE id=?", (person_id,))
    conn.commit()
    return cur.rowcount > 0


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------
@router.get("")
def list_endpoint():
    return list_people()


@router.post("", status_code=201)
def create_endpoint(body: dict):
    try:
        return {"person": create_person(body)}
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.patch("/{person_id}")
def patch_endpoint(person_id: int, body: dict):
    if not get_person(person_id):
        raise HTTPException(404, "Person not found")
    try:
        return {"person": update_person(person_id, body)}
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.delete("/{person_id}", status_code=204)
def delete_endpoint(person_id: int):
    if not delete_person(person_id):
        raise HTTPException(404, "Person not found")
    return None
