"""Conductor — Local Sources.

Lets users designate local files and folders on their machine as data/context
sources the app can remember, enumerate, and read from (list / browse / read
file contents). Paths are stored as the user gave them (``~`` expanded and
normalised) and every browse/read request re-resolves the requested path against
the declared root with a ``os.path.realpath`` + ``startswith`` containment check,
so a ``?path=..%2F..%2Fetc`` can never escape it.

Router prefix: /api/local-sources
"""
from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException

import storage

router = APIRouter(prefix="/api/local-sources", tags=["local-sources"])

MAX_BROWSE = 200
MAX_READ_BYTES = 200 * 1024  # 200 KB text cap


# ---------------------------------------------------------------------------
# schema
# ---------------------------------------------------------------------------
def init_local_sources_db() -> None:
    conn = storage._conn()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS local_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            label TEXT NOT NULL,
            path TEXT NOT NULL,
            kind TEXT DEFAULT 'folder',        -- folder | file
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _get_source(source_id: int) -> dict:
    row = storage._conn().execute(
        "SELECT * FROM local_sources WHERE id=?", (source_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404, "Source not found")
    return dict(row)


def _count_files(root: str) -> int:
    """Number of files under a folder (recursive; skips hidden entries so the
    count matches what browse() will actually show)."""
    n = 0
    try:
        for _dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            n += sum(1 for f in filenames if not f.startswith("."))
    except OSError:
        pass
    return n


def _serialize(src: dict) -> dict:
    path = src["path"]
    exists = os.path.exists(path)
    if src["kind"] == "file":
        count = 1
    elif exists:
        count = _count_files(path)
    else:
        count = 0
    out = dict(src)
    out["count"] = count
    out["exists"] = exists
    return out


def _resolve(src: dict, rel: str) -> str:
    """Resolve a requested relative path against the source root, refusing to
    escape it (realpath + startswith containment check)."""
    root = os.path.realpath(src["path"])
    rel = (rel or "").replace("\\", "/").strip().lstrip("/")
    if src["kind"] == "file":
        # A file source is its own root — only the file itself is addressable.
        if rel in ("", ".", os.path.basename(root)):
            return root
        raise HTTPException(400, "A file source can only read the source file itself")
    if rel in ("", "."):
        return root
    target = os.path.realpath(os.path.join(root, rel))
    if target != root and not target.startswith(root + os.sep):
        raise HTTPException(400, "Path is outside the source root")
    return target


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------
def list_sources() -> list[dict]:
    rows = storage._conn().execute(
        "SELECT * FROM local_sources ORDER BY id DESC"
    ).fetchall()
    return [_serialize(dict(r)) for r in rows]


@router.get("")
def get_sources():
    return list_sources()


@router.post("", status_code=201)
def create_source(body: dict):
    label = str(body.get("label") or "").strip()
    path = str(body.get("path") or "").strip()
    kind = str(body.get("kind") or "folder").strip().lower()
    if not label:
        raise HTTPException(400, "Label is required")
    if not path:
        raise HTTPException(400, "Path is required")
    if kind not in ("folder", "file"):
        kind = "folder"
    path = os.path.normpath(os.path.expanduser(path))
    if not os.path.exists(path):
        raise HTTPException(404, f"Path does not exist: {path}")
    is_dir = os.path.isdir(path)
    if kind == "file" and is_dir:
        raise HTTPException(400, "kind='file' but the path is a directory — choose 'folder'")
    if kind == "folder" and not is_dir:
        raise HTTPException(400, "kind='folder' but the path is a file — choose 'file'")
    conn = storage._conn()
    cur = conn.execute(
        "INSERT INTO local_sources (label, path, kind, created_at) VALUES (?,?,?,?)",
        (label, path, kind, storage.now_iso()),
    )
    conn.commit()
    return _serialize(_get_source(cur.lastrowid))


@router.delete("/{source_id}", status_code=204)
def delete_source(source_id: int):
    _get_source(source_id)  # 404 if missing
    conn = storage._conn()
    conn.execute("DELETE FROM local_sources WHERE id=?", (source_id,))
    conn.commit()
    return None


@router.get("/{source_id}/browse")
def browse_source(source_id: int, path: str = ""):
    src = _get_source(source_id)
    if not os.path.exists(src["path"]):
        raise HTTPException(404, "Source path no longer exists")
    if src["kind"] == "file":
        try:
            size = os.path.getsize(src["path"])
        except OSError:
            size = 0
        return {
            "path": "",
            "kind": "file",
            "files": [{"name": os.path.basename(src["path"]), "is_dir": False, "size": size}],
            "truncated": False,
        }
    root = os.path.realpath(src["path"])
    target = _resolve(src, path)
    if not os.path.isdir(target):
        raise HTTPException(400, "Not a directory")
    entries = []
    truncated = False
    try:
        with os.scandir(target) as it:
            for entry in it:
                if entry.name.startswith("."):
                    continue
                if len(entries) >= MAX_BROWSE:
                    truncated = True
                    break
                is_dir = entry.is_dir(follow_symlinks=False)
                size = 0
                if not is_dir:
                    try:
                        size = entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        size = 0
                entries.append({"name": entry.name, "is_dir": is_dir, "size": size})
    except OSError as exc:
        raise HTTPException(400, f"Cannot browse: {exc}")
    entries.sort(key=lambda e: (not e["is_dir"], e["name"].lower()))
    rel = "" if target == root else os.path.relpath(target, root)
    return {"path": rel, "kind": "folder", "files": entries, "truncated": truncated}


@router.get("/{source_id}/read")
def read_source(source_id: int, path: str = ""):
    src = _get_source(source_id)
    target = _resolve(src, path)
    if not os.path.exists(target):
        raise HTTPException(404, "File not found")
    if os.path.isdir(target):
        raise HTTPException(400, "Path is a directory, not a file")
    try:
        size = os.path.getsize(target)
    except OSError:
        size = 0
    try:
        with open(target, "rb") as fh:
            data = fh.read(MAX_READ_BYTES + 1)
    except OSError as exc:
        raise HTTPException(400, f"Cannot read: {exc}")
    truncated = len(data) > MAX_READ_BYTES
    data = data[:MAX_READ_BYTES]
    if b"\x00" in data:
        return {
            "name": os.path.basename(target),
            "size": size,
            "text": "",
            "binary": True,
            "truncated": truncated,
        }
    return {
        "name": os.path.basename(target),
        "size": size,
        "text": data.decode("utf-8", errors="replace"),
        "truncated": truncated,
    }
