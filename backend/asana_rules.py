"""Conductor — Asana Rules & Routing canvas (ported from Process Visualizer).

A workflow/rules design canvas (trigger → condition → action/approval graphs)
that exports every trigger→path as an ``asana-rules/v1`` rule set. This module
persists canvases in SQLite; rule computation lives client-side
(frontend/asana-rules.js) so designs stay instant and offline-friendly.

Endpoints:
  - GET/POST         /api/asana-rules/canvases
  - GET/PATCH/DELETE /api/asana-rules/canvases/{id}
  - POST             /api/asana-rules/canvases/{id}/rules   -> asana-rules/v1 JSON

Canvases are engine-agnostic ({nodes:[{id,label,note,x,y,kind|style}], edges})
so a design can also round-trip through the standalone Process Visualizer's
``process-visualizer/v1`` format via import/export in the UI.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

import storage
from storage import now_iso

router = APIRouter(prefix="/api/asana-rules", tags=["asana-rules"])

NODE_KINDS = ("trigger", "condition", "action", "approval")
GENERIC_STYLES = ("entry", "task", "process", "decision", "wait", "end")


def init() -> None:
    conn = storage._conn()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS asana_rule_canvases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            mode TEXT NOT NULL DEFAULT 'asana',
            skin TEXT NOT NULL DEFAULT 'flat',
            nodes TEXT DEFAULT '[]',
            edges TEXT DEFAULT '[]',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    conn.commit()


init()


def _row(sql: str, params: tuple = ()) -> dict | None:
    r = storage._conn().execute(sql, params).fetchone()
    if not r:
        return None
    d = dict(r)
    for k in ("nodes", "edges"):
        try:
            d[k] = json.loads(d[k])
        except Exception:
            d[k] = []
    return d


def _json_len(raw: str | None) -> int:
    try:
        v = json.loads(raw or "[]")
        return len(v) if isinstance(v, list) else 0
    except Exception:
        return 0


def _rows(sql: str, params: tuple = ()) -> list[dict]:
    out = []
    for r in storage._conn().execute(sql, params).fetchall():
        d = dict(r)
        d["node_count"] = _json_len(d.get("nodes"))
        d["edge_count"] = _json_len(d.get("edges"))
        d.pop("nodes", None)
        d.pop("edges", None)
        out.append(d)
    return out


def _validate(nodes: list, edges: list) -> None:
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise HTTPException(400, "nodes and edges must be arrays")
    ids = set()
    for n in nodes[:300]:
        if not isinstance(n, dict) or not n.get("id"):
            raise HTTPException(400, "every node needs an id")
        kind = n.get("kind")
        style = n.get("style")
        if kind is not None and str(kind) not in NODE_KINDS:
            raise HTTPException(400, f"unknown node kind '{kind}'")
        if style is not None and str(style).replace("st-", "") not in GENERIC_STYLES:
            raise HTTPException(400, f"unknown node style '{style}'")
        ids.add(str(n["id"]))
    for e in edges[:500]:
        if not isinstance(e, dict) or not e.get("from") or not e.get("to"):
            raise HTTPException(400, "every edge needs from/to")
        if str(e["from"]) not in ids or str(e["to"]) not in ids:
            raise HTTPException(400, f"edge {e.get('from')}->{e.get('to')} references an unknown node")


# ------------------------------------------------------------------ canvases
@router.get("/canvases")
def list_canvases():
    return _rows(
        "SELECT id, name, mode, skin, nodes, edges, created_at, updated_at "
        "FROM asana_rule_canvases ORDER BY updated_at DESC"
    )


@router.post("/canvases", status_code=201)
def create_canvas(body: dict):
    name = str(body.get("name") or "").strip() or "Untitled ruleset"
    mode = body.get("mode") if body.get("mode") in ("asana", "generic") else "asana"
    skin = str(body.get("skin") or "flat")
    nodes = body.get("nodes") or []
    edges = body.get("edges") or []
    _validate(nodes, edges)
    ts = now_iso()
    conn = storage._conn()
    cur = conn.execute(
        "INSERT INTO asana_rule_canvases (name, mode, skin, nodes, edges, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (name, mode, skin, json.dumps(nodes), json.dumps(edges), ts, ts),
    )
    conn.commit()
    return _row("SELECT * FROM asana_rule_canvases WHERE id=?", (cur.lastrowid,))


@router.get("/canvases/{canvas_id}")
def get_canvas(canvas_id: int):
    c = _row("SELECT * FROM asana_rule_canvases WHERE id=?", (canvas_id,))
    if not c:
        raise HTTPException(404, "Canvas not found")
    return c


@router.patch("/canvases/{canvas_id}")
def update_canvas(canvas_id: int, body: dict):
    c = _row("SELECT * FROM asana_rule_canvases WHERE id=?", (canvas_id,))
    if not c:
        raise HTTPException(404, "Canvas not found")
    name = str(body.get("name") or c["name"]).strip() or "Untitled ruleset"
    mode = body.get("mode") if body.get("mode") in ("asana", "generic") else c["mode"]
    skin = str(body.get("skin") or c["skin"])
    nodes = body.get("nodes", c["nodes"])
    edges = body.get("edges", c["edges"])
    _validate(nodes, edges)
    conn = storage._conn()
    conn.execute(
        "UPDATE asana_rule_canvases SET name=?, mode=?, skin=?, nodes=?, edges=?, updated_at=? WHERE id=?",
        (name, mode, skin, json.dumps(nodes), json.dumps(edges), now_iso(), canvas_id),
    )
    conn.commit()
    return _row("SELECT * FROM asana_rule_canvases WHERE id=?", (canvas_id,))


@router.delete("/canvases/{canvas_id}", status_code=204)
def delete_canvas(canvas_id: int):
    conn = storage._conn()
    conn.execute("DELETE FROM asana_rule_canvases WHERE id=?", (canvas_id,))
    conn.commit()
    return None


# ------------------------------------------------------- rule computation
def _compute_rules(nodes: list, edges: list) -> list[dict]:
    """Port of Process Visualizer's toAsanaRules(): each trigger-rooted
    path becomes one named rule with conditions[] + actions[]."""
    incoming = {str(e.get("to")) for e in edges}
    triggers = [n for n in nodes if str(n.get("id")) not in incoming and n.get("kind") != "action"]
    adj: dict[str, list[str]] = {}
    for e in edges:
        adj.setdefault(str(e.get("from")), []).append(str(e.get("to")))
    by_id = {str(n.get("id")): n for n in nodes}

    rules: list[dict] = []
    for t in triggers:
        paths: list[list[str]] = []

        def dfs(nid: str, path: list[str], visited: set[str]) -> None:
            visited = visited | {nid}
            path = path + [nid]
            outs = adj.get(nid, [])
            if not outs:
                paths.append(path)
                return
            for o in outs:
                if o in visited:
                    paths.append(path)
                    return
                dfs(o, path, visited)

        dfs(str(t.get("id")), [], set())
        for pi, p in enumerate(paths):
            steps = []
            for nid in p:
                n = by_id.get(nid, {})
                steps.append({
                    "step": str(n.get("label") or nid),
                    "kind": str(n.get("kind") or "action"),
                    "config": str(n.get("note") or ""),
                })
            rules.append({
                "name": f"{steps[0]['step']} — path {pi + 1}".lower(),
                "trigger": steps[0]["config"] or steps[0]["step"],
                "conditions": [
                    s["step"] + (f" ({s['config']})" if s["config"] else "")
                    for s in steps if s["kind"] == "condition"
                ],
                "actions": [
                    s["step"] + (f" → {s['config']}" if s["config"] else "")
                    for s in steps if s["kind"] in ("action", "approval")
                ],
            })
    return rules


@router.post("/canvases/{canvas_id}/rules")
def export_rules(canvas_id: int):
    c = _row("SELECT * FROM asana_rule_canvases WHERE id=?", (canvas_id,))
    if not c:
        raise HTTPException(404, "Canvas not found")
    if c["mode"] != "asana":
        raise HTTPException(400, "Canvas is not in asana rules mode")
    return {
        "format": "asana-rules/v1",
        "workflow": c["name"],
        "generated": now_iso(),
        "rules": _compute_rules(c["nodes"], c["edges"]),
    }
