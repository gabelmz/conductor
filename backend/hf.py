"""Conductor — HuggingFace model browser + local model manager.

Bridges the Hugging Face Hub (search, full model cards, GGUF file discovery)
with the local llama.cpp engine in `llama.py`, so users can find, evaluate,
download, run, and delete local GGUF models from the Models view.

Endpoints (prefix ``/api/hf``):
  - GET  /api/hf/search  ?q=&sort=&gguf=&limit=&page=   search the HF Hub
  - GET  /api/hf/model/{repo_id}                        full card: metadata + README + GGUF files
  - GET  /api/hf/system                                 RAM / disk / CPU for the "will it run" heuristic
  - POST /api/hf/download   {repo_id, filename}         start a background GGUF download
  - GET  /api/hf/downloads                              live download progress
  - POST /api/hf/downloads/{download_id}/cancel         cancel an in-flight download
  - POST /api/hf/delete     {path}                      delete a downloaded GGUF (under models/ only)
"""
from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/hf", tags=["hf"])

HF_BASE = "https://huggingface.co"

BACKEND_DIR = Path(__file__).resolve().parent
APP_ROOT = BACKEND_DIR.parent
MODELS_DIR = APP_ROOT / "models"
HF_MODELS_DIR = MODELS_DIR / "hf"  # downloads land here: models/hf/<author>__<repo>/<file>.gguf

README_CAP = 24000   # chars of README to ship to the UI
TREE_CAP = 400       # max files to consider from a repo tree


def _urlopen(url: str, timeout: float = 15.0, headers: dict | None = None):
    req = urllib.request.Request(url, headers={"User-Agent": "conductor/1.0", **(headers or {})})
    return urllib.request.urlopen(req, timeout=timeout)


def _get_json(url: str, timeout: float = 15.0) -> object:
    with _urlopen(url, timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _get_text(url: str, timeout: float = 15.0) -> str:
    with _urlopen(url, timeout) as r:
        return r.read().decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# system info — powers the "will it run on this machine" heuristic
# ---------------------------------------------------------------------------
def system_info() -> dict:
    total_ram, avail_ram = _system_memory()
    try:
        du = shutil.disk_usage(MODELS_DIR)
        disk_total, disk_free = du.total, du.free
    except OSError:
        disk_total = disk_free = None
    return {
        "ram_total": total_ram,
        "ram_available": avail_ram,
        "disk_total": disk_total,
        "disk_free": disk_free,
        "cpu_threads": os.cpu_count() or 1,
        "models_dir": str(MODELS_DIR),
    }


def _system_memory() -> tuple[int | None, int | None]:
    """(total, available) physical RAM in bytes via GlobalMemoryStatusEx on Windows."""
    try:
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        m = MEMORYSTATUSEX()
        m.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return int(m.ullTotalPhys), int(m.ullAvailPhys)
    except Exception:
        return None, None


def fit_for(size_bytes: int, total_ram: int | None) -> dict:
    """Rough 'will this GGUF run' verdict. llama.cpp memory-maps weights, so a
    model fits in ~1.2x its file size of RAM (weights + headroom + context)."""
    if total_ram is None:
        return {"level": "unknown", "label": "RAM unknown", "needed": round(size_bytes * 1.2)}
    needed = size_bytes * 1.2
    if needed <= total_ram * 0.8:
        return {"level": "ok", "label": "Fits comfortably", "needed": round(needed)}
    if needed <= total_ram:
        return {"level": "tight", "label": "Tight — close other apps", "needed": round(needed)}
    return {"level": "no", "label": "Exceeds RAM", "needed": round(needed)}


# ---------------------------------------------------------------------------
# HuggingFace API passthrough
# ---------------------------------------------------------------------------
_QUANT_RE = re.compile(r"(?i)(iq\d[\w]*|q\d[\w]*|bf16|f16|f32)")
_GGUF_RE = re.compile(r"\.gguf$", re.I)
_LICENSE_TAG_RE = re.compile(r"^license:(.+)$", re.I)
_PARAM_RE = re.compile(r"(\d+(?:\.\d+)?)x?(\d+(?:\.\d+)?)[Bb]")


def _quant_of(filename: str) -> str | None:
    m = _QUANT_RE.search(Path(filename).name)
    return m.group(1).upper() if m else None


def _license_of(model: dict) -> str | None:
    # tags carry 'license:apache-2.0' most reliably; then cardData, then top-level.
    for tag in model.get("tags") or []:
        m = _LICENSE_TAG_RE.match(str(tag))
        if m:
            return m.group(1)
    card = model.get("cardData") or {}
    if isinstance(card, dict):
        lic = card.get("license")
        if isinstance(lic, str):
            return lic
        if isinstance(lic, list) and lic:
            return str(lic[0])
    return model.get("license") or None


def _param_label(model: dict) -> str | None:
    """Best-effort parameter count: safetensors.parameters → name inference."""
    st = model.get("safetensors") or {}
    params = st.get("parameters") if isinstance(st, dict) else None
    if isinstance(params, dict):
        total = params.get("BF16") or params.get("F32") or params.get("F16")
        if total is None:
            vals = [v for v in params.values() if isinstance(v, (int, float))]
            total = max(vals) if vals else None
        if total is not None:
            total = float(total)
            if total >= 1e9:
                return f"{total / 1e9:.1f}B"
            if total >= 1e6:
                return f"{total / 1e6:.0f}M"
    # fall back to the size encoded in the repo id / name (e.g. "7B", "8x7B")
    name = str(model.get("modelId") or model.get("id") or "")
    moe = re.search(r"(\d+)x(\d+(?:\.\d+)?)[Bb]", name)
    if moe:
        return f"{int(moe.group(1))}×{moe.group(2)}B MoE"
    m = re.search(r"(\d+(?:\.\d+)?)[Bb]", name)
    if m:
        return f"{m.group(1)}B"
    return None


def _has_gguf(model: dict) -> bool:
    for sib in model.get("siblings") or []:
        if _GGUF_RE.search(str(sib.get("rfilename") or "")):
            return True
    return bool(model.get("gguf"))


def _normalize_model(m: dict) -> dict:
    tags = m.get("tags") or []
    return {
        "id": m.get("modelId") or m.get("id") or "",
        "author": m.get("author") or "",
        "downloads": m.get("downloads") or 0,
        "likes": m.get("likes") or 0,
        "tags": tags,
        "pipeline_tag": m.get("pipeline_tag") or "",
        "library_name": m.get("library_name") or "",
        "license": _license_of(m),
        "lastModified": m.get("lastModified") or "",
        "private": bool(m.get("private")),
        "gated": bool(m.get("gated")),
        "disabled": bool(m.get("disabled")),
        "gguf": _has_gguf(m),
        "params": _param_label(m),
        "downloadsAllTime": (m.get("downloadsAllTime") or {}).get("downloads") or 0,
    }


@router.get("/search")
def search(q: str = "", sort: str = "downloads", gguf: bool = False,
           limit: int = 30, page: int = 0):
    query = {
        "search": q.strip(),
        "sort": sort if sort in ("downloads", "likes", "trendingScore", "lastModified", "created") else "downloads",
        "direction": "-1",
        "limit": max(1, min(100, limit)),
        "full": "true",
    }
    if gguf:
        query["filter"] = "gguf"
    if page:
        query["skip"] = page * int(query["limit"])
    url = f"{HF_BASE}/api/models?" + urllib.parse.urlencode(query)
    try:
        data = _get_json(url)
    except urllib.error.HTTPError as exc:
        raise HTTPException(502, f"HuggingFace search failed: HTTP {exc.code}")
    except Exception as exc:
        raise HTTPException(502, f"HuggingFace search failed: {exc}")
    if not isinstance(data, list):
        data = []
    return {"query": q, "results": [_normalize_model(m) for m in data if isinstance(m, dict)]}


@router.get("/model/{repo_id:path}")
def model_card(repo_id: str):
    repo_id = repo_id.strip().strip("/")
    if not repo_id or "/" not in repo_id:
        raise HTTPException(400, "repo_id must be author/model (e.g. TheBloke/Mistral-7B-GGUF)")
    try:
        meta = _get_json(f"{HF_BASE}/api/models/{urllib.parse.quote(repo_id, safe='/')}")
    except urllib.error.HTTPError as exc:
        raise HTTPException(404 if exc.code == 404 else 502, f"Model not found on HuggingFace (HTTP {exc.code})")
    except Exception as exc:
        raise HTTPException(502, f"Could not fetch model card: {exc}")

    readme = ""
    try:
        readme = _get_text(f"{HF_BASE}/{repo_id}/raw/main/README.md")[:README_CAP]
    except Exception:
        readme = ""

    files = _gguf_files(repo_id, meta)

    return {
        "model": _normalize_model(meta),
        "repo_id": repo_id,
        "readme": readme,
        "files": files,
        "tree": meta.get("siblings") or [],
        "cardData": meta.get("cardData") or {},
        "config": meta.get("config") or {},
    }


def _gguf_files(repo_id: str, meta: dict | None = None) -> list[dict]:
    """GGUF files in the repo (recursive tree) with size + quant + fit verdict."""
    files: list[dict] = []
    try:
        tree = _get_json(
            f"{HF_BASE}/api/models/{urllib.parse.quote(repo_id, safe='/')}/tree/main"
            f"?recursive=true&expand=true"
        )
    except Exception:
        tree = []

    sysinfo = system_info()
    total_ram = sysinfo["ram_total"]

    for node in tree[:TREE_CAP]:
        if not isinstance(node, dict):
            continue
        path = node.get("path") or ""
        if not _GGUF_RE.search(path):
            continue
        size = node.get("size") or 0
        lfs = node.get("lfs") or {}
        if isinstance(lfs, dict) and lfs.get("size"):
            size = lfs["size"]
        files.append({
            "path": path,
            "size": int(size),
            "quant": _quant_of(path),
            "fit": fit_for(int(size), total_ram),
        })

    # Fallback: derive from top-level siblings if the tree call failed/empty.
    if not files and meta:
        for sib in meta.get("siblings") or []:
            name = str(sib.get("rfilename") or "")
            if _GGUF_RE.search(name):
                files.append({
                    "path": name,
                    "size": 0,
                    "quant": _quant_of(name),
                    "fit": fit_for(0, total_ram),
                })

    files.sort(key=lambda f: (f["size"] == 0, f["size"]))
    return files


@router.get("/system")
def sysinfo():
    return system_info()


# ---------------------------------------------------------------------------
# downloads — background threads, live progress
# ---------------------------------------------------------------------------
_downloads: dict[str, dict] = {}
_dl_lock = threading.Lock()
_CANCEL: dict[str, bool] = {}


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _download_target(repo_id: str, filename: str) -> Path:
    safe_repo = re.sub(r"[^A-Za-z0-9._-]", "_", repo_id.replace("/", "__"))
    safe_file = re.sub(r"[\\/]", "_", filename)  # flatten any subdir to a flat name
    return HF_MODELS_DIR / safe_repo / Path(safe_file).name


def _download_worker(dl_id: str, repo_id: str, filename: str) -> None:
    dest = _download_target(repo_id, filename)
    tmp = dest.with_suffix(dest.suffix + ".part")
    url = f"{HF_BASE}/{repo_id}/resolve/main/{urllib.parse.quote(filename, safe='/')}"
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(url, headers={"User-Agent": "conductor/1.0"})
        with urllib.request.urlopen(req, timeout=600) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            with open(tmp, "wb") as f:
                while True:
                    if _CANCEL.get(dl_id):
                        with _dl_lock:
                            _downloads[dl_id]["status"] = "cancelled"
                            _downloads[dl_id]["message"] = "Cancelled"
                        break
                    chunk = resp.read(256 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    with _dl_lock:
                        d = _downloads.get(dl_id)
                        if d:
                            d["done"] = done
                            d["total"] = total
                            d["progress"] = round(done / total * 100, 1) if total else 0
                            d["rateBps"] = int(done / max(1, time.time() - d["_t0"]))
            if _CANCEL.get(dl_id):
                tmp.unlink(missing_ok=True)
                _tidy_empty_parent(dest)
                return
        tmp.replace(dest)
        with _dl_lock:
            d = _downloads.get(dl_id)
            if d:
                d["status"] = "done"
                d["progress"] = 100
                d["done"] = dest.stat().st_size
                d["total"] = dest.stat().st_size
                d["dest"] = str(dest)
                d["message"] = f"Downloaded {Path(dest).name}"
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        _tidy_empty_parent(dest)
        with _dl_lock:
            d = _downloads.get(dl_id)
            if d:
                d["status"] = "error"
                d["message"] = f"{type(exc).__name__}: {exc}"


def _tidy_empty_parent(dest: Path) -> None:
    parent = dest.parent
    try:
        if parent != HF_MODELS_DIR and parent.exists() and not any(parent.iterdir()):
            parent.rmdir()
    except OSError:
        pass


@router.post("/download")
def download(body: dict):
    repo_id = str(body.get("repo_id") or "").strip().strip("/")
    filename = str(body.get("filename") or "").strip()
    if not repo_id or not filename:
        raise HTTPException(400, "repo_id and filename are required")
    dest = _download_target(repo_id, filename)
    if dest.exists():
        raise HTTPException(409, f"Already downloaded: {dest.name}")

    sysinfo = system_info()
    dl_id = uuid.uuid4().hex[:12]
    with _dl_lock:
        _CANCEL[dl_id] = False
        _downloads[dl_id] = {
            "id": dl_id,
            "repo_id": repo_id,
            "filename": filename,
            "dest": str(dest),
            "total": 0,
            "done": 0,
            "progress": 0,
            "rateBps": 0,
            "status": "downloading",
            "message": "Queued…",
            "startedAt": _now(),
            "disk_free": sysinfo["disk_free"],
            "_t0": time.time(),
        }
    threading.Thread(target=_download_worker, args=(dl_id, repo_id, filename), daemon=True).start()
    return {"id": dl_id, "status": "downloading"}


@router.get("/downloads")
def downloads():
    with _dl_lock:
        out = []
        for d in _downloads.values():
            c = {k: v for k, v in d.items() if not k.startswith("_")}
            c["_t0"] = d.get("_t0")  # keep for rate math on the next poll; harmless to expose
            out.append(c)
    out.sort(key=lambda x: x["startedAt"], reverse=True)
    return {"downloads": out, "active": sum(1 for d in out if d["status"] == "downloading")}


@router.post("/downloads/{download_id}/cancel")
def cancel_download(download_id: str):
    with _dl_lock:
        if download_id not in _downloads:
            raise HTTPException(404, "Unknown download")
        _CANCEL[download_id] = True
        d = _downloads[download_id]
        d["status"] = "cancelling"
    return {"ok": True, "id": download_id}


# ---------------------------------------------------------------------------
# delete a downloaded model (only under models/, never adopted stores)
# ---------------------------------------------------------------------------
@router.post("/delete")
def delete_model(body: dict):
    target = Path(str(body.get("path") or "")).resolve()
    root = MODELS_DIR.resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise HTTPException(400, "Refusing to delete outside the app's models/ directory")
    if not target.exists():
        raise HTTPException(404, "Model file not found")
    try:
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
    except OSError as exc:
        raise HTTPException(500, f"Delete failed: {exc}")
    # tidy an empty author__repo folder after the last file goes
    parent = target.parent
    try:
        if parent != HF_MODELS_DIR and parent.exists() and not any(parent.iterdir()):
            parent.rmdir()
    except OSError:
        pass
    return {"ok": True, "deleted": str(target)}
