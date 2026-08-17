"""Conductor — Bernie canvas engine (ported from the AI Studio app).

Bernie is a node-based workflow canvas (Trigger / JSON / Text / HTTP / AI /
Script / Sheet / Drive / Flush nodes) with Gemini-powered execution and a
CORS proxy. This port keeps the same API surface but:

  - canvases are persisted in SQLite (they were in-memory + Firebase)
  - AI nodes use Conductor's configured provider (DeepSeek or local llama)
    instead of Gemini, so one API key powers chat, AI workflows and canvases
  - HTTP nodes go through the same /api/bernie/proxy CORS bypass

Endpoints:
  - GET/POST        /api/bernie/canvases
  - GET/PATCH/DELETE /api/bernie/canvases/{id}
  - POST /api/bernie/ai/execute    {prompt, input_data}        -> {result}
  - POST /api/bernie/ai/suggest    {nodes, edges}              -> {suggestions:[...]}
  - POST /api/bernie/proxy         {url, method, headers, body}-> {status, data}
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from fastapi import APIRouter, HTTPException

import storage
from storage import now_iso

router = APIRouter(prefix="/api/bernie", tags=["bernie"])

NODE_TYPES = ("trigger", "json", "text", "http", "ai", "script", "sheet", "drive", "flush", "custom")


def init() -> None:
    conn = storage._conn()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS bernie_canvases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
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


def _rows(sql: str, params: tuple = ()) -> list[dict]:
    out = []
    for r in storage._conn().execute(sql, params).fetchall():
        d = dict(r)
        d["node_count"] = _json_len(d.get("nodes"))
        d["edge_count"] = _json_len(d.get("edges"))
        for k in ("nodes", "edges"):
            d.pop(k, None)
        out.append(d)
    return out


def _json_len(raw: str) -> int:
    try:
        v = json.loads(raw or "[]")
        return len(v) if isinstance(v, list) else 0
    except Exception:
        return 0


def _validate_graph(nodes: list, edges: list) -> None:
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise HTTPException(400, "nodes and edges must be arrays")
    ids = set()
    for n in nodes[:200]:
        if not isinstance(n, dict) or not n.get("id"):
            raise HTTPException(400, "every node needs an id")
        if n.get("type", "custom") not in NODE_TYPES:
            raise HTTPException(400, f"unknown node type '{n.get('type')}'")
        ids.add(str(n["id"]))
    for e in edges[:400]:
        if not isinstance(e, dict) or not e.get("source") or not e.get("target"):
            raise HTTPException(400, "every edge needs source and target")
        if e["source"] not in ids or e["target"] not in ids:
            raise HTTPException(400, f"edge {e.get('source')}->{e.get('target')} references an unknown node")


# ---------------------------------------------------------------------------
# Canvases
# ---------------------------------------------------------------------------
@router.get("/canvases")
def list_canvases():
    return _rows("SELECT id, name, nodes, edges, created_at, updated_at FROM bernie_canvases ORDER BY updated_at DESC")


@router.post("/canvases", status_code=201)
def create_canvas(body: dict):
    name = str(body.get("name") or "").strip() or "Untitled canvas"
    nodes = body.get("nodes") or []
    edges = body.get("edges") or []
    _validate_graph(nodes, edges)
    ts = now_iso()
    conn = storage._conn()
    cur = conn.execute(
        "INSERT INTO bernie_canvases (name, nodes, edges, created_at, updated_at) VALUES (?,?,?,?,?)",
        (name, json.dumps(nodes), json.dumps(edges), ts, ts),
    )
    conn.commit()
    return _row("SELECT * FROM bernie_canvases WHERE id=?", (cur.lastrowid,))


@router.get("/canvases/{canvas_id}")
def get_canvas(canvas_id: int):
    c = _row("SELECT * FROM bernie_canvases WHERE id=?", (canvas_id,))
    if not c:
        raise HTTPException(404, "Canvas not found")
    return c


@router.patch("/canvases/{canvas_id}")
def update_canvas(canvas_id: int, body: dict):
    c = _row("SELECT * FROM bernie_canvases WHERE id=?", (canvas_id,))
    if not c:
        raise HTTPException(404, "Canvas not found")
    name = str(body.get("name") or c["name"]).strip() or "Untitled canvas"
    nodes = body.get("nodes", c["nodes"])
    edges = body.get("edges", c["edges"])
    _validate_graph(nodes, edges)
    conn = storage._conn()
    conn.execute(
        "UPDATE bernie_canvases SET name=?, nodes=?, edges=?, updated_at=? WHERE id=?",
        (name, json.dumps(nodes), json.dumps(edges), now_iso(), canvas_id),
    )
    conn.commit()
    return _row("SELECT * FROM bernie_canvases WHERE id=?", (canvas_id,))


@router.delete("/canvases/{canvas_id}", status_code=204)
def delete_canvas(canvas_id: int):
    conn = storage._conn()
    conn.execute("DELETE FROM bernie_canvases WHERE id=?", (canvas_id,))
    conn.commit()
    return None


# ---------------------------------------------------------------------------
# AI execution — reuses Conductor's chat provider config (DeepSeek / llama)
# ---------------------------------------------------------------------------
def _complete(prompt: str, want_json: bool = False) -> str:
    import chat

    cfg = chat._load_config()
    provider = cfg["provider"]
    if provider != "llama" and not cfg["api_key"]:
        raise HTTPException(400, "No AI provider configured — open Settings → AI Chat and add an API key, or switch to a local Llama model.")
    messages = [
        {"role": "system", "content": "You are Salmon, Conductor's canvas engine. Follow instructions exactly; output only the requested format."},
        {"role": "user", "content": prompt},
    ]
    if provider == "llama":
        import llama
        from pathlib import Path
        port = llama._find_running_server()
        if port is None:
            llama.start_server({"model": cfg["llama_model"], "ctx": cfg["llama_ctx"], "port": cfg["llama_port"]})
            port = llama._find_running_server()
            if port is None:
                raise HTTPException(500, "Local llama server failed to start.")
        model = Path(llama.resolve_model(cfg["llama_model"])).name
        chunks = [d for d in llama.stream_chat(messages, model, port=port, max_tokens=1600, temperature=0.4)]
        return "".join(chunks)
    payload = {"model": cfg["model"], "messages": messages, "stream": False,
               "temperature": 0.4, "max_tokens": 1600}
    req = urllib.request.Request(
        f"{cfg['base_url']}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {cfg['api_key']}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=240) as resp:
        obj = json.loads(resp.read().decode("utf-8"))
    return (obj.get("choices") or [{}])[0].get("message", {}).get("content", "")


@router.post("/ai/execute")
def ai_execute(body: dict):
    prompt = str(body.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(400, "prompt is required")
    input_data = body.get("input_data") or body.get("inputData")
    final_prompt = (
        f"Instructions: {prompt}\n\n"
        f"Input Data:\n{json.dumps(input_data, indent=2, default=str) if isinstance(input_data, (dict, list)) else input_data}"
    )
    return {"result": _complete(final_prompt)}


@router.post("/ai/suggest")
def ai_suggest(body: dict):
    nodes = body.get("nodes") or []
    edges = body.get("edges") or []
    if not nodes:
        raise HTTPException(400, "nodes is required")
    prompt = (
        "You are an AI assistant in a visual node-based workflow builder (like Google Labs Stitch). "
        f"The user built this graph:\nNodes: {json.dumps(nodes, default=str)}\nEdges: {json.dumps(edges, default=str)}\n\n"
        'Suggest 1-3 specific areas for automation or improvement as JSON: {"suggestions": [{"title": "...", "description": "..."}]}'
    )
    raw = _complete(prompt, want_json=True)
    try:
        parsed = json.loads(raw)
        suggestions = parsed.get("suggestions") if isinstance(parsed, dict) else None
        if isinstance(suggestions, list):
            return {"suggestions": suggestions[:3]}
    except Exception:
        pass
    return {"suggestions": [{"title": "AI suggestion", "description": raw[:500]}]}


@router.post("/proxy")
def proxy(body: dict):
    url = str(body.get("url") or "").strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "url must be http(s)")
    method = str(body.get("method") or "GET").upper()
    if method not in ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"):
        raise HTTPException(400, "unsupported method")
    headers = body.get("headers") if isinstance(body.get("headers"), dict) else {}
    payload = body.get("body")
    data = None
    if method in ("POST", "PUT", "PATCH") and payload is not None:
        if isinstance(payload, (dict, list)):
            data = json.dumps(payload).encode("utf-8")
            headers = {**headers, "Content-Type": "application/json"}
        else:
            data = str(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            text = resp.read().decode("utf-8", errors="replace")
            status = resp.status
    except urllib.error.HTTPError as exc:
        status = exc.code
        text = exc.read().decode("utf-8", errors="replace")
    except Exception as exc:
        raise HTTPException(502, f"Proxy request failed: {exc}")
    try:
        return {"status": status, "data": json.loads(text)}
    except Exception:
        return {"status": status, "data": text[:100000]}
