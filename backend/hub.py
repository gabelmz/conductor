"""Conductor — Tool Hub (ported from LAW's core-hub).

Hub cards catalog every tool in the workspace: apps, skills, modules,
plugins and themes — with status (live/draft/archived/planning/scaffold),
owner, tags, and a trigger phrase. LAW keeps Supabase Postgres as the future
source of truth with a local SQLite cache; Conductor is SQLite-only, so the
table is the source of truth here (documented deviation).

Schema mirrors LAW's HubCardSchema (hub-types.ts) exactly.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

import storage

router = APIRouter(prefix="/api/hub", tags=["hub"])

CATEGORIES = ("app", "skill", "module", "plugin", "theme")
STATUSES = ("live", "draft", "archived", "planning", "scaffold")


def init_hub_db() -> None:
    conn = storage._conn()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS hub_cards (
            id TEXT PRIMARY KEY,
            cat TEXT NOT NULL,
            name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft',
            desc TEXT,
            owner TEXT,
            tags TEXT NOT NULL DEFAULT '[]',
            trigger TEXT,
            note TEXT,
            source_file TEXT,
            lint_notes TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


def _row_to_card(row) -> dict:
    return {
        "id": row["id"],
        "cat": row["cat"],
        "name": row["name"],
        "status": row["status"],
        "desc": row["desc"],
        "owner": row["owner"],
        "tags": json.loads(row["tags"] or "[]"),
        "trigger": row["trigger"],
        "note": row["note"],
        "sourceFile": row["source_file"],
        "lintNotes": row["lint_notes"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@router.get("/cards")
def list_cards(cat: str | None = None, status: str | None = None, q: str | None = None):
    conn = storage._conn()
    sql = "SELECT * FROM hub_cards WHERE 1=1"
    params: list = []
    if cat:
        sql += " AND cat=?"
        params.append(cat)
    if status:
        sql += " AND status=?"
        params.append(status)
    if q:
        sql += " AND (name LIKE ? OR desc LIKE ? OR owner LIKE ? OR tags LIKE ?)"
        like = f"%{q}%"
        params += [like, like, like, like]
    sql += " ORDER BY updated_at DESC"
    rows = conn.execute(sql, params).fetchall()
    return {"cards": [_row_to_card(r) for r in rows]}


@router.post("/cards")
def create_card(body: dict):
    cat = str(body.get("cat") or "")
    name = str(body.get("name") or "").strip()
    if cat not in CATEGORIES:
        raise HTTPException(400, f"cat must be one of {', '.join(CATEGORIES)}")
    if not name:
        raise HTTPException(400, "name is required")
    status = str(body.get("status") or "draft")
    if status not in STATUSES:
        raise HTTPException(400, f"status must be one of {', '.join(STATUSES)}")
    card_id = str(body.get("id") or uuid.uuid4().hex[:12])
    now = _now()
    conn = storage._conn()
    conn.execute(
        """INSERT INTO hub_cards (id, cat, name, status, desc, owner, tags, trigger, note, source_file, lint_notes, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            card_id, cat, name, status,
            body.get("desc"), body.get("owner"),
            json.dumps(body.get("tags") or []),
            body.get("trigger"), body.get("note"),
            body.get("sourceFile"), body.get("lintNotes"),
            now, now,
        ),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM hub_cards WHERE id=?", (card_id,)).fetchone()
    return _row_to_card(row)


@router.patch("/cards/{card_id}")
def update_card(card_id: str, body: dict):
    conn = storage._conn()
    row = conn.execute("SELECT * FROM hub_cards WHERE id=?", (card_id,)).fetchone()
    if not row:
        raise HTTPException(404, f"Unknown card '{card_id}'")
    allowed = ("cat", "name", "status", "desc", "owner", "tags", "trigger", "note", "sourceFile", "lintNotes")
    updates = []
    params: list = []
    for key in allowed:
        if key in body:
            value = body[key]
            if key == "tags":
                value = json.dumps(value or [])
            updates.append(f"{key}=?")
            params.append(value)
    if not updates:
        return _row_to_card(row)
    updates.append("updated_at=?")
    params.append(_now())
    params.append(card_id)
    conn.execute(f"UPDATE hub_cards SET {', '.join(updates)} WHERE id=?", params)
    conn.commit()
    row = conn.execute("SELECT * FROM hub_cards WHERE id=?", (card_id,)).fetchone()
    return _row_to_card(row)


@router.delete("/cards/{card_id}")
def delete_card(card_id: str):
    conn = storage._conn()
    cur = conn.execute("DELETE FROM hub_cards WHERE id=?", (card_id,))
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(404, f"Unknown card '{card_id}'")
    return {"ok": True}


@router.post("/scan")
def scan_cards():
    """Seed/refresh cards from known sources: installed plugins first, then
    (optionally) the vault's apps + skills dirs. Existing cards are updated
    in place; nothing is deleted."""
    created, updated = 0, 0
    conn = storage._conn()

    from plugins import all_manifests

    for manifest in all_manifests():
        mid = manifest["id"]
        existing = conn.execute("SELECT id FROM hub_cards WHERE id=?", (f"plugin-{mid}",)).fetchone()
        payload = {
            "cat": "plugin",
            "name": manifest.get("name") or mid,
            "status": "live",
            "desc": manifest.get("description"),
            "tags": ["plugin", mid],
            "sourceFile": manifest.get("main"),
        }
        if existing:
            conn.execute(
                "UPDATE hub_cards SET name=?, desc=?, tags=?, updated_at=? WHERE id=?",
                (payload["name"], payload["desc"], json.dumps(payload["tags"]), _now(), f"plugin-{mid}"),
            )
            updated += 1
        else:
            now = _now()
            conn.execute(
                """INSERT INTO hub_cards (id, cat, name, status, desc, owner, tags, trigger, note, source_file, lint_notes, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (f"plugin-{mid}", payload["cat"], payload["name"], payload["status"],
                 payload["desc"], None, json.dumps(payload["tags"]), None, None,
                 payload["sourceFile"], None, now, now),
            )
            created += 1
    conn.commit()
    return {"ok": True, "created": created, "updated": updated}
