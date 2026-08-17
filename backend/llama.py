"""Parker — local llama.cpp backend (turboquant build, OpenAI-compatible).

Spawns and manages `llama-server.exe` (from the Atomic Chat / Jan install)
as a subprocess, then exposes an OpenAI-compatible streaming chat client so
Parker can answer from a fully local GGUF model.

Endpoints:
  - GET  /api/llama/status   is the server running? which model/port?
  - POST /api/llama/start    ensure server up (spawns if needed, waits for health)
  - POST /api/llama/stop     shut the local server down
  - GET  /api/llama/models   list GGUF models available in models/
"""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/llama", tags=["llama"])

# Layout: backend/ is sibling of llama/ and models/
BACKEND_DIR = Path(__file__).resolve().parent
APP_ROOT = BACKEND_DIR.parent
LLAMA_BIN = APP_ROOT / "llama" / "bin"
MODELS_DIR = APP_ROOT / "models"
SERVER_LOG = APP_ROOT / "data" / "llama-server.log"

DEFAULT_PORT = 8098
MAX_TRY_PORTS = 4  # closed localhost ports can be FW-dropped; keep probes tiny
START_TIMEOUT_S = 120

_proc: subprocess.Popen | None = None
_proc_port: int | None = None
# port -> (timestamp, model name) — avoids llama-server's slow /v1/models probe
_model_cache: dict[int, tuple[float, str | None]] = {}
# usage object from the last streamed chat completion (final chunk), consumed
# by chat.py to feed the cumulative token counter
_last_usage: dict | None = None


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _free_port(start: int) -> int:
    """First free TCP port at or after `start`."""
    for port in range(start, start + MAX_TRY_PORTS):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.3)
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return start


def _health_ok(port: int, timeout: float = 0.25) -> bool:
    """Raw-socket /health probe — fails fast (urllib can hang on FW-dropped ports)."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout) as s:
            s.sendall(b"GET /health HTTP/1.0\r\n\r\n")
            data = s.recv(64)
        return b"200" in data
    except Exception:
        return False


def _find_running_server() -> int | None:
    """If an existing llama-server (ours or a prior run's) is up, find it."""
    for port in range(DEFAULT_PORT, DEFAULT_PORT + MAX_TRY_PORTS):
        if _health_ok(port):
            return port
    return None


def resolve_model(name: str) -> Path:
    """Resolve a model name (filename in models/, or absolute path) to a file."""
    name = (name or "").strip()
    if not name:
        raise HTTPException(400, "No model selected — pick a GGUF in Settings → AI Chat → Local Llama.")
    p = Path(name)
    if p.is_absolute():
        if p.exists():
            return p
        raise HTTPException(404, f"Model file not found: {p}")
    candidate = MODELS_DIR / name
    if candidate.exists():
        return candidate
    # allow bare name without .gguf
    candidate = MODELS_DIR / f"{name}.gguf"
    if candidate.exists():
        return candidate
    raise HTTPException(404, f"Model '{name}' not found in {MODELS_DIR}")


# --------------------------------------------------------------------------
# server lifecycle
# --------------------------------------------------------------------------
def _spawn_server(model_path: Path, port: int, ctx: int, threads: int) -> subprocess.Popen:
    global _proc, _proc_port
    exe = LLAMA_BIN / "llama-server.exe"
    if not exe.exists():
        raise HTTPException(500, f"llama-server.exe not found at {exe}")
    SERVER_LOG.parent.mkdir(parents=True, exist_ok=True)
    logf = open(SERVER_LOG, "ab")
    cmd = [
        str(exe),
        "-m", str(model_path),
        "--host", "127.0.0.1",
        "--port", str(port),
        "--ctx-size", str(ctx),
        "--threads", str(threads),
        "--parallel", "1",
    ]
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(LLAMA_BIN),
            stdout=logf,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError as exc:
        raise HTTPException(500, f"Failed to launch llama-server: {exc}")
    _proc = proc
    _proc_port = port
    return proc


def _wait_health(port: int, timeout: float = START_TIMEOUT_S) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _health_ok(port):
            return True
        if _proc is not None and _proc.poll() is not None:
            return False
        time.sleep(0.5)
    return False


def server_status() -> dict:
    global _proc, _proc_port
    running_port = _find_running_server()
    if _proc is not None and _proc.poll() is not None:
        _proc = None
        _proc_port = None
    managed = _proc is not None and _proc.poll() is None and _proc_port == running_port
    return {
        "running": running_port is not None,
        "port": running_port or _proc_port,
        "model": _proc_model_name() if running_port else None,
        "modelPath": server_props(running_port).get("model_path") if running_port else None,
        "bin": str(LLAMA_BIN / "llama-server.exe"),
        "log": str(SERVER_LOG),
        # LAW EngineStatus fields: 'available' = a binary exists for this
        # platform; 'managed' = we spawned it (adopted servers are never
        # killed); 'startedAt'/'pid'/'error' for the panel.
        "available": (LLAMA_BIN / "llama-server.exe").exists(),
        "managed": bool(managed),
        "startedAt": None,
        "pid": _proc.pid if managed else None,
        "error": None,
    }


def _proc_model_name(port: int | None = None) -> str | None:
    """Cached model name for a running server (probe at most once per 30s)."""
    port = port or _find_running_server()
    if port is None:
        return None
    now = time.time()
    if port in _model_cache and now - _model_cache[port][0] < 30:
        return _model_cache[port][1]
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/models", timeout=1.5) as r:
            data = json.loads(r.read().decode("utf-8"))
        models = data.get("models") or []
        name = models[0].get("model") if models else None
        _model_cache[port] = (now, name)
        return name
    except Exception:
        _model_cache[port] = (now, None)
        return None


def server_props(port: int | None = None) -> dict:
    """Read n_ctx + model_path from a running llama-server's /props endpoint.

    Returns {} when the server is down or /props is unavailable (older builds).
    n_ctx lives at the top level in older servers and under
    default_generation_settings in newer ones — both are handled.
    """
    port = port or _find_running_server()
    if port is None:
        return {}
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/props", timeout=1.5) as r:
            props = json.loads(r.read().decode("utf-8"))
        out: dict = {"port": port}
        n_ctx = props.get("n_ctx")
        if n_ctx is None:
            dgs = props.get("default_generation_settings") or {}
            n_ctx = dgs.get("n_ctx")
        if n_ctx:
            out["n_ctx"] = int(n_ctx)
        if props.get("model_path"):
            out["model_path"] = props["model_path"]
        if props.get("total_slots"):
            out["slots"] = props["total_slots"]
        return out
    except Exception:
        return {}


def take_last_usage() -> dict | None:
    """Return and clear the last streamed usage object (for the token counter)."""
    global _last_usage
    u = _last_usage
    _last_usage = None
    return u


@router.get("/status")
def status():
    return server_status()


@router.get("/models")
def list_models():
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    out = []
    for p in sorted(MODELS_DIR.glob("*.gguf")):
        out.append({"name": p.name, "path": str(p), "size": p.stat().st_size})
    return {"dir": str(MODELS_DIR), "models": out}


# --------------------------------------------------------------------------
# model discovery (ported from LAW's engine/models.ts)
# --------------------------------------------------------------------------
EMBEDDING_NAME_PATTERN = re.compile(r"(^|[-_.])(embed|embedding|bge|gte|e5|minilm|nomic-embed)([-_.]|$)", re.I)
MULTIPART_GGUF = re.compile(r"-\d{5}-of-\d{5}\.gguf$", re.I)
FIRST_PART_GGUF = re.compile(r"-00001-of-\d{5}\.gguf$", re.I)


def default_search_dirs() -> list[Path]:
    home = Path.home()
    appdata = os.environ.get("APPDATA") or str(home)
    return [
        MODELS_DIR,                                            # conductor's own folder
        Path(appdata) / "Conductor" / "models",                # packaged appdata models
        home / ".ollama" / "models" / ".studio_links",         # Ollama hardlinks
        home / ".cache" / "lm-studio" / "models",              # LM Studio default store
        home / ".lmstudio" / "models",
        home / "jan" / "models",                               # Jan / Atomic Chat
    ]


def classify_model(file_name: str) -> str:
    """Name-based chat-vs-embedding heuristic (LAW's EMBEDDING_NAME_PATTERN)."""
    return "embedding" if EMBEDDING_NAME_PATTERN.search(file_name) else "chat"


def _scan_dir(dir_path: Path, source_dir: Path, depth: int, out: list[dict]) -> None:
    if depth < 0 or not dir_path.is_dir():
        return
    try:
        entries = sorted(os.listdir(dir_path))
    except OSError:
        return  # unreadable dir — partial list beats none
    for entry in entries:
        full = dir_path / entry
        try:
            is_dir = full.is_dir()
            size = full.stat().st_size
        except OSError:
            continue
        if is_dir:
            _scan_dir(full, source_dir, depth - 1, out)
        elif entry.lower().endswith(".gguf"):
            if MULTIPART_GGUF.search(entry) and not FIRST_PART_GGUF.search(entry):
                continue  # only the first part of a multi-part GGUF can load
            model_id = entry[:-5]
            out.append({
                "id": model_id,
                "name": re.sub(r"[-_]+", " ", model_id).strip(),
                "path": str(full),
                "sizeBytes": size,
                "kind": classify_model(model_id),
                "sourceDir": str(source_dir),
            })


def discover_models(max_depth: int = 3) -> dict:
    """Scan every known model store for .gguf files (LAW's scanLocalModels)."""
    found: list[dict] = []
    for d in default_search_dirs():
        _scan_dir(d, d, max_depth, found)
    # collapse duplicates by resolved path (case-insensitive), first wins
    by_path: dict[str, dict] = {}
    for model in found:
        key = model["path"].lower()
        by_path.setdefault(key, model)
    models = sorted(by_path.values(), key=lambda m: m["name"].lower())
    return {"dirs": [str(d) for d in default_search_dirs()], "models": models}


@router.get("/discover")
def discover():
    return discover_models()


@router.post("/start")
def start_server(body: dict | None = None):
    body = body or {}
    # already up?
    existing = _find_running_server()
    if existing is not None:
        return {"ok": True, "running": True, "port": existing, "reused": True, "model": _proc_model_name()}

    model = resolve_model(body.get("model") or "")
    ctx = int(body.get("ctx") or 4096)
    threads = int(body.get("threads") or 0) or max(1, (os.cpu_count() or 4) - 2)
    port = _free_port(int(body.get("port") or DEFAULT_PORT))

    proc = _spawn_server(model, port, ctx, threads)
    ok = _wait_health(port)
    if not ok:
        status = "exited" if proc.poll() is not None else "timeout"
        tail = ""
        try:
            tail = SERVER_LOG.read_text(encoding="utf-8", errors="replace")[-400:]
        except Exception:
            pass
        raise HTTPException(500, f"llama-server failed to start ({status}). Log tail: {tail}")
    _model_cache[port] = (time.time(), model.name)
    return {"ok": True, "running": True, "port": port, "model": model.name, "reused": False}


@router.post("/stop")
def stop_server():
    global _proc, _proc_port
    stopped = []
    if _proc is not None and _proc.poll() is None:
        try:
            _proc.terminate()
        except OSError:
            pass
        stopped.append(_proc.pid)
    _proc = None
    _proc_port = None
    _model_cache.clear()
    # also kill any stray llama-server on our port range (prior-run orphans)
    for port in range(DEFAULT_PORT, DEFAULT_PORT + MAX_TRY_PORTS):
        if _health_ok(port):
            try:
                import urllib.request as u
                req = u.Request(f"http://127.0.0.1:{port}/shutdown", method="POST")
                u.urlopen(req, timeout=1.5)
                stopped.append(f"port-{port}")
            except Exception:
                pass
    return {"ok": True, "stopped": stopped}


# --------------------------------------------------------------------------
# streaming chat client (OpenAI-compatible)
# --------------------------------------------------------------------------
def stream_chat(messages: list[dict], model: str, port: int | None = None,
                max_tokens: int = 1200, temperature: float = 0.6):
    """Yield text deltas from llama-server's /v1/chat/completions (SSE).

    Usage from the final streamed chunk is stashed in _last_usage (read via
    take_last_usage()) so callers can feed the cumulative token counter.
    """
    global _last_usage
    port = port or _find_running_server() or DEFAULT_PORT
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=600) as resp:
        for raw in resp:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                obj = json.loads(data)
            except json.JSONDecodeError:
                continue
            if obj.get("usage"):
                _last_usage = obj["usage"]
            choices = obj.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            content = delta.get("content")
            if content:
                yield content
