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
from concurrent import futures
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

# Ports Conductor itself starts llama-server on. ONLY these are ever swept by
# stop_server() - discovery may look far wider, but we must never shut down a
# server we did not start (a user's own Ollama, for instance).
MANAGED_PORTS = tuple(range(DEFAULT_PORT, DEFAULT_PORT + MAX_TRY_PORTS))

# Well-known local inference ports, probed for DISCOVERY only. Detection used to
# be limited to MANAGED_PORTS, so a model served by Ollama (11434) or LM Studio
# (1234) was never found even though both ship in the provider catalog.
# Override with CONDUCTOR_LLAMA_PORTS="11434,1234,9000" (comma-separated).
WELL_KNOWN_LOCAL_PORTS = (
    11434,  # Ollama
    1234,   # LM Studio
    8000,   # vLLM / unsloth / text-generation-webui
    8080,   # llama.cpp server default
    5000,   # text-generation-webui legacy
    3000,   # atomic-chat
    1337,   # Jan
)


def discovery_ports() -> tuple[int, ...]:
    """Ports to probe when looking for an already-running local server.

    Managed ports come first so the common case short-circuits before any
    wider scan.
    """
    override = (os.environ.get("CONDUCTOR_LLAMA_PORTS") or "").strip()
    if override:
        extra: list[int] = []
        for chunk in override.replace(";", ",").split(","):
            chunk = chunk.strip()
            if chunk.isdigit() and 1 <= int(chunk) <= 65535:
                extra.append(int(chunk))
        if extra:
            return tuple(dict.fromkeys((*MANAGED_PORTS, *extra)))
    return tuple(dict.fromkeys((*MANAGED_PORTS, *WELL_KNOWN_LOCAL_PORTS)))

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


def _probe(port: int, path: str, timeout: float) -> bool:
    """Raw-socket HTTP probe - fails fast (urllib can hang on FW-dropped ports)."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout) as s:
            s.settimeout(timeout)
            req = f"GET {path} HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n"
            s.sendall(req.encode())
            data = s.recv(64)
        return b"200" in data
    except Exception:
        return False


def _health_ok(port: int, timeout: float = 0.25) -> bool:
    """True when something OpenAI-compatible is serving on `port`.

    /health is llama.cpp-specific. Ollama, LM Studio, vLLM and friends do not
    implement it, so a /health-only probe reported them as down - which is why
    local model detection missed every runtime except our own bundled server.
    Falls back to /v1/models, which all OpenAI-compatible servers expose.
    """
    return _probe(port, "/health", timeout) or _probe(port, "/v1/models", timeout)


def _find_running_server() -> int | None:
    """If an existing local server (ours or another runtime) is up, find it.

    Managed ports are checked first and sequentially, so the overwhelmingly
    common case costs one probe. The wider well-known range is only reached
    when nothing of ours is running, and is probed in parallel to keep total
    wall time bounded regardless of how many ports are configured.
    """
    for port in MANAGED_PORTS:
        if _health_ok(port):
            return port

    wider = [p for p in discovery_ports() if p not in MANAGED_PORTS]
    if not wider:
        return None
    with futures.ThreadPoolExecutor(max_workers=min(8, len(wider))) as pool:
        for port, ok in pool.map(lambda pt: (pt, _health_ok(pt)), wider):
            if ok:
                return port
    return None


def detect_local_servers() -> list[dict]:
    """Every reachable local OpenAI-compatible server, with its loaded model.

    Probed in parallel so adding ports does not lengthen the scan.
    """
    ports = discovery_ports()
    with futures.ThreadPoolExecutor(max_workers=min(8, len(ports))) as pool:
        alive = [pt for pt, ok in pool.map(lambda pt: (pt, _health_ok(pt)), ports) if ok]
    return [
        {
            "port": port,
            "base_url": f"http://127.0.0.1:{port}/v1",
            "managed": port in MANAGED_PORTS,
            "model": _proc_model_name(port),
        }
        for port in alive
    ]


def resolve_model(name: str) -> Path:
    """Resolve a model name (filename in models/, an absolute path, or an id/filename
    surfaced by discover_models() from any known local install) to a file.

    The Settings picker (GET /api/llama/discover) already lists GGUFs found in Ollama,
    LM Studio, and Jan/Atomic Chat stores, keyed by their bare `id` — without this
    fallback, picking one of those always 404'd because only MODELS_DIR was ever
    searched, even though the picker itself made them look selectable.
    """
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
    # Not in Conductor's own folder — search every known local install (Ollama, LM
    # Studio, Jan/Atomic Chat) by id or filename before giving up.
    for model in discover_models()["models"]:
        if model["id"] == name or Path(model["path"]).name == name:
            return Path(model["path"])
    raise HTTPException(
        404,
        f"Model '{name}' not found in {MODELS_DIR} or any discovered local install "
        "(Ollama, LM Studio, Jan). Try Settings → AI Chat → Local Llama → Refresh.",
    )


# --------------------------------------------------------------------------
# lazy default-model provisioning — never bundled in the installer, never
# downloaded eagerly at app startup; only fetched the first time something
# actually needs a local model and none is configured yet (chat.py's llama
# routing calls this). Reuses hf.py's existing download pipeline (progress
# visible at GET /api/hf/downloads) instead of a second download mechanism.
# --------------------------------------------------------------------------
DEFAULT_MODEL_REPO = "bartowski/dolphin-2.9-llama3-8b-GGUF"
DEFAULT_MODEL_FILE = "dolphin-2.9-llama3-8b-Q4_K_M.gguf"

# Job kinds written to storage so local-model work shows up in the Activity
# feed. Deliberately distinct from "parse_catalog" — a model download is not a
# catalog import, and labelling it as one is exactly the mislabeling this
# feed is supposed to stop.
INSTALL_JOB_KIND = "model_install"
SERVER_JOB_KIND = "model_start"

# jobs row currently tracking the one-time default-model download, so repeated
# polls update that row instead of spamming the feed with a new one each time.
_install_job_id: int | None = None


def _record_job(kind: str, status: str, message: str,
                progress: int = 0, job_id: int | None = None) -> int | None:
    """Write (or update) one Activity-feed job row for local-model work.

    Returns the job id, or None if the job table isn't available. Every
    failure is swallowed: activity logging is observability, and must never
    be the reason a model download or server start fails.
    """
    try:
        import storage

        if job_id is None:
            job_id = storage.create_job(kind, None)
        storage.update_job(job_id, status=status, progress=int(progress), message=message)
        return job_id
    except Exception:
        return None


def ensure_default_model() -> dict:
    """Kick off (or report progress on) the one-time default-model download.

    Returns {"status": "ready", "path": ..., "model": ...} once the GGUF is
    on disk, or {"status": "downloading", "progress": <0-100>} while it's
    still in flight. Never blocks — callers should tell the user to retry
    shortly rather than wait on this.

    Every state change is mirrored onto a `model_install` job row so the
    install is visible in the Activity feed (it used to happen completely
    silently, which looked like the app had hung).
    """
    global _install_job_id
    import hf

    path = hf._download_target(DEFAULT_MODEL_REPO, DEFAULT_MODEL_FILE)
    if path.exists():
        if _install_job_id is not None:
            _record_job(INSTALL_JOB_KIND, "done", f"Local model ready: {path.name}", 100, _install_job_id)
            _install_job_id = None
        return {"status": "ready", "path": str(path), "model": path.name}

    for d in hf._downloads.values():
        if (d.get("repo_id") == DEFAULT_MODEL_REPO and d.get("filename") == DEFAULT_MODEL_FILE
                and d.get("status") == "downloading"):
            progress = d.get("progress", 0)
            _install_job_id = _record_job(
                INSTALL_JOB_KIND, "running",
                f"Downloading local model {DEFAULT_MODEL_FILE}", progress, _install_job_id,
            )
            return {"status": "downloading", "progress": progress}

    try:
        hf.download({"repo_id": DEFAULT_MODEL_REPO, "filename": DEFAULT_MODEL_FILE})
    except HTTPException:
        pass  # already queued or landed between the checks above and here
    _install_job_id = _record_job(
        INSTALL_JOB_KIND, "running",
        f"Downloading local model {DEFAULT_MODEL_FILE} from {DEFAULT_MODEL_REPO}", 0, _install_job_id,
    )
    return {"status": "downloading", "progress": 0}


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
        # llama.cpp returns {"models":[{"model": ...}]}; every other
        # OpenAI-compatible server (Ollama, LM Studio, vLLM) returns the
        # standard {"data":[{"id": ...}]}. Reading only the former is why
        # third-party runtimes showed up with no model name.
        entries = data.get("models") or data.get("data") or []
        name = None
        if entries:
            first = entries[0]
            if isinstance(first, dict):
                name = first.get("model") or first.get("id")
            elif isinstance(first, str):
                name = first
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


@router.get("/servers")
def list_local_servers():
    """Every local OpenAI-compatible server we can reach, not just our own.

    Detection previously covered only the four ports Conductor starts
    llama-server on, so a user running Ollama or LM Studio saw nothing.
    """
    servers = detect_local_servers()
    return {
        "servers": servers,
        "scanned_ports": list(discovery_ports()),
        "managed_ports": list(MANAGED_PORTS),
    }


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


_DISCOVER_CACHE_TTL_S = 30.0
_discover_cache: dict | None = None
_discover_cache_at: float = 0.0


def discover_models(max_depth: int = 3, *, force: bool = False) -> dict:
    """Scan every known model store for .gguf files (LAW's scanLocalModels).

    A recursive filesystem walk across up to 6 directories on every call — cheap on a small
    store, but on a machine with a large Ollama/LM Studio cache (or a network-backed home
    directory) this was a real, measured contributor to Settings > AI Providers opening
    slowly, since it ran synchronously on every single tab render. Cached for
    _DISCOVER_CACHE_TTL_S: models on disk don't change fast enough to justify re-walking on
    every open, and `force=True` (the route's `?force=true`) bypasses the cache on demand.
    """
    global _discover_cache, _discover_cache_at
    now = time.monotonic()
    if not force and _discover_cache is not None and (now - _discover_cache_at) < _DISCOVER_CACHE_TTL_S:
        return _discover_cache

    found: list[dict] = []
    for d in default_search_dirs():
        _scan_dir(d, d, max_depth, found)
    # collapse duplicates by resolved path (case-insensitive), first wins
    by_path: dict[str, dict] = {}
    for model in found:
        key = model["path"].lower()
        by_path.setdefault(key, model)
    models = sorted(by_path.values(), key=lambda m: m["name"].lower())
    result = {"dirs": [str(d) for d in default_search_dirs()], "models": models}
    _discover_cache = result
    _discover_cache_at = now
    return result


@router.get("/discover")
def discover(force: bool = False):
    return discover_models(force=force)


@router.post("/start")
def start_server(body: dict | None = None):
    """Make sure a local llama-server is running, spawning one if needed.

    Reuses an already-running server when it finds one. Otherwise it resolves
    the requested GGUF, spawns llama-server.exe and waits for it to report
    healthy. The spawn attempt is recorded as a `model_start` job so a slow or
    failed startup is visible in the Activity feed instead of just hanging.
    """
    body = body or {}
    # already up?
    existing = _find_running_server()
    if existing is not None:
        return {"ok": True, "running": True, "port": existing, "reused": True, "model": _proc_model_name()}

    model = resolve_model(body.get("model") or "")
    ctx = int(body.get("ctx") or 4096)
    threads = int(body.get("threads") or 0) or max(1, (os.cpu_count() or 4) - 2)
    port = _free_port(int(body.get("port") or DEFAULT_PORT))

    job_id = _record_job(SERVER_JOB_KIND, "running", f"Starting local model server: {model.name}", 0)
    proc = _spawn_server(model, port, ctx, threads)
    ok = _wait_health(port)
    if not ok:
        status = "exited" if proc.poll() is not None else "timeout"
        tail = ""
        try:
            tail = SERVER_LOG.read_text(encoding="utf-8", errors="replace")[-400:]
        except Exception:
            pass
        _record_job(SERVER_JOB_KIND, "error", f"llama-server failed to start ({status})", 0, job_id)
        raise HTTPException(500, f"llama-server failed to start ({status}). Log tail: {tail}")
    _model_cache[port] = (time.time(), model.name)
    _record_job(SERVER_JOB_KIND, "done", f"Local model server ready on port {port}: {model.name}", 100, job_id)
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
    # Also kill stray llama-servers from prior runs - MANAGED_PORTS only.
    # Never widen this to discovery_ports(): shutting down a port we did not
    # start would kill the user's own Ollama / LM Studio instance.
    for port in MANAGED_PORTS:
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
