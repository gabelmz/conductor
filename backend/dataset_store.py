"""Conductor — Dataset Store, WAL Checkpoint & Background Pipeline Manager.

Manages local database backups, WAL checkpoints, automated dataset pipelines
(raw -> staging -> views), schema detection, state diffing, and dataset states.

Router prefix: /api/dataset-store
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, UploadFile, File, Form

import storage
import report_presets

router = APIRouter(prefix="/api/dataset-store", tags=["dataset-store"])

# Directory paths
DATA_DIR = storage.DATA_DIR
LOCAL_STORE_DIR = DATA_DIR / "local-store"
BACKUPS_DIR = LOCAL_STORE_DIR / "backups"
RAW_DIR = LOCAL_STORE_DIR / "raw"
STAGING_DIR = LOCAL_STORE_DIR / "staging"
INTERMEDIARY_DIR = LOCAL_STORE_DIR / "intermediary"
VIEWS_DIR = LOCAL_STORE_DIR / "views"
STATES_DIR = LOCAL_STORE_DIR / "states"

PAGE_VIEWS_DIR = VIEWS_DIR / "pages"

# Catalog & App Domains
DEFAULT_DOMAINS = [
    "catalog_products",
    "inventory",
    "reports",
    "asana_tasks",
    "compliance_cdq",
    "market_keepa",
]

# Core Application Pages
DEFAULT_PAGES = [
    "chat",
    "dashboard",
    "asana",
    "keepa",
    "compliance",
    "products",
    "workflows",
    "mapping",
    "reports",
    "settings",
]


def load_domains_from_env() -> list[str]:
    raw = os.getenv("DATASET_STORE_DOMAINS") or os.getenv("CONDUCTOR_DATASET_DOMAINS")
    if raw:
        raw = raw.strip()
        if raw.startswith("["):
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    return [str(x).strip() for x in parsed if str(x).strip()]
            except Exception:
                pass
        return [x.strip() for x in raw.split(",") if x.strip()]
    return list(DEFAULT_DOMAINS)


def load_pages_from_env() -> list[str]:
    raw = os.getenv("DATASET_STORE_PAGES") or os.getenv("CONDUCTOR_DATASET_PAGES")
    if raw:
        raw = raw.strip()
        if raw.startswith("["):
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    return [str(x).strip() for x in parsed if str(x).strip()]
            except Exception:
                pass
        return [x.strip() for x in raw.split(",") if x.strip()]
    return list(DEFAULT_PAGES)


DOMAINS: list[str] = load_domains_from_env()
PAGES: list[str] = load_pages_from_env()


def set_domains(domains: list[str]) -> list[str]:
    """Replace current domains list with new list of domains."""
    DOMAINS.clear()
    DOMAINS.extend([str(d).strip() for d in domains if str(d).strip()])
    for state_dir in (RAW_DIR, STAGING_DIR, INTERMEDIARY_DIR, VIEWS_DIR):
        for domain in DOMAINS:
            (state_dir / domain).mkdir(parents=True, exist_ok=True)
    return list(DOMAINS)


def set_pages(pages: list[str]) -> list[str]:
    """Replace current pages list with new list of pages."""
    PAGES.clear()
    PAGES.extend([str(p).strip() for p in pages if str(p).strip()])
    for page in PAGES:
        view_file = PAGE_VIEWS_DIR / f"{page}.json"
        if not view_file.exists():
            default_view = _generate_default_page_view(page)
            view_file.write_text(json.dumps(default_view, indent=2), encoding="utf-8")
            _update_db_page_view(page, default_view)
    return list(PAGES)


def reload_config_from_env(force: bool = False) -> None:
    """Reload DOMAINS and PAGES from environment variables if set."""
    env_doms = load_domains_from_env()
    if force or os.getenv("DATASET_STORE_DOMAINS") or os.getenv("CONDUCTOR_DATASET_DOMAINS"):
        set_domains(env_doms)
    else:
        for d in env_doms:
            if d not in DOMAINS:
                register_domain(d)

    env_pgs = load_pages_from_env()
    if force or os.getenv("DATASET_STORE_PAGES") or os.getenv("CONDUCTOR_DATASET_PAGES"):
        set_pages(env_pgs)
    else:
        for p in env_pgs:
            if p not in PAGES:
                register_page(p)


def register_domain(domain: str | list[str]) -> list[str]:
    """Dynamically register one or more domains."""
    items = [domain] if isinstance(domain, str) else domain
    for d in items:
        d_clean = str(d).strip()
        if d_clean and d_clean not in DOMAINS:
            DOMAINS.append(d_clean)
            for state_dir in (RAW_DIR, STAGING_DIR, INTERMEDIARY_DIR, VIEWS_DIR):
                (state_dir / d_clean).mkdir(parents=True, exist_ok=True)
    return list(DOMAINS)


def register_page(page: str | list[str]) -> list[str]:
    """Dynamically register one or more pages."""
    items = [page] if isinstance(page, str) else page
    for p in items:
        p_clean = str(p).strip()
        if p_clean and p_clean not in PAGES:
            PAGES.append(p_clean)
            view_file = PAGE_VIEWS_DIR / f"{p_clean}.json"
            if not view_file.exists():
                default_view = _generate_default_page_view(p_clean)
                view_file.write_text(json.dumps(default_view, indent=2), encoding="utf-8")
                _update_db_page_view(p_clean, default_view)
    return list(PAGES)


def get_domains() -> list[str]:
    """Return configured list of domains."""
    return list(DOMAINS)


def get_pages() -> list[str]:
    """Return configured list of pages."""
    return list(PAGES)

# Supported Dataset States
STATES = ["raw", "staging", "intermediary", "views"]

_PIPELINE_THREAD = None
_PIPELINE_RUNNING = False


# ---------------------------------------------------------------------------
# Schema & Initialization
# ---------------------------------------------------------------------------
def init_dataset_store() -> None:
    """Ensure dataset directories, SQLite tables, and background tasks exist."""
    reload_config_from_env()
    LOCAL_STORE_DIR.mkdir(parents=True, exist_ok=True)
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    INTERMEDIARY_DIR.mkdir(parents=True, exist_ok=True)
    VIEWS_DIR.mkdir(parents=True, exist_ok=True)
    STATES_DIR.mkdir(parents=True, exist_ok=True)
    PAGE_VIEWS_DIR.mkdir(parents=True, exist_ok=True)

    for state_dir in (RAW_DIR, STAGING_DIR, INTERMEDIARY_DIR, VIEWS_DIR):
        for domain in DOMAINS:
            (state_dir / domain).mkdir(parents=True, exist_ok=True)

    conn = storage._conn()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS dataset_states (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dataset_id TEXT UNIQUE NOT NULL,
            filename TEXT NOT NULL,
            domain TEXT NOT NULL,
            state TEXT NOT NULL,
            file_path TEXT NOT NULL,
            record_count INTEGER DEFAULT 0,
            file_size INTEGER DEFAULT 0,
            checksum TEXT,
            metadata TEXT DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS page_views_cache (
            page_id TEXT PRIMARY KEY,
            view_data TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS local_store_backups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            backup_id TEXT UNIQUE NOT NULL,
            db_path TEXT NOT NULL,
            spine_path TEXT,
            config_path TEXT,
            file_size INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS wal_checkpoint_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mode TEXT NOT NULL,
            busy INTEGER,
            log INTEGER,
            checkpointed INTEGER,
            wal_size_before INTEGER,
            wal_size_after INTEGER,
            created_at TEXT NOT NULL
        );
        """
    )
    conn.commit()

    seed_page_views()
    sync_states_manifest()
    start_background_pipeline()


def seed_page_views() -> None:
    """Seed default page views JSON files if missing."""
    for page_id in PAGES:
        view_file = PAGE_VIEWS_DIR / f"{page_id}.json"
        if not view_file.exists():
            default_view = _generate_default_page_view(page_id)
            view_file.write_text(json.dumps(default_view, indent=2), encoding="utf-8")
            _update_db_page_view(page_id, default_view)


def _generate_default_page_view(page_id: str) -> dict[str, Any]:
    now = storage.now_iso()
    base = {"page_id": page_id, "updated_at": now, "status": "ready", "data": {}}

    if page_id == "dashboard":
        base["data"] = {
            "products_count": storage.count_products(),
            "asana_tasks": storage.asana_counts(),
            "files_count": len(storage.list_files()),
            "latest_activity": "Dataset pipeline active",
        }
    elif page_id == "products":
        base["data"] = {
            "total": storage.count_products(),
            "sample_products": storage.list_products(limit=10),
            "tags": storage.list_tags(),
        }
    elif page_id == "asana":
        base["data"] = {
            "counts": storage.asana_counts(),
            "tasks_sample": storage.list_asana_tasks(limit=10),
        }
    elif page_id == "reports":
        base["data"] = {"files": storage.list_files(limit=20)}
    else:
        base["data"] = {"initialized": True, "page": page_id}

    return base


# ---------------------------------------------------------------------------
# Item 3: SQLite WAL Checkpoint & Delta Manager
# ---------------------------------------------------------------------------
def checkpoint_wal(mode: str = "PASSIVE") -> dict[str, Any]:
    """Perform a WAL checkpoint on conductor.db and log WAL file sizes."""
    mode = mode.upper()
    if mode not in ("PASSIVE", "FULL", "RESTART", "TRUNCATE"):
        mode = "PASSIVE"

    wal_file = storage.DB_PATH.with_suffix(".db-wal")
    wal_before = wal_file.stat().st_size if wal_file.exists() else 0

    conn = storage._conn()
    conn.commit()

    busy, log_frames, checkpointed = 0, 0, 0
    try:
        cur = conn.execute(f"PRAGMA wal_checkpoint({mode})")
        row = cur.fetchone()
        if row:
            busy, log_frames, checkpointed = row[0], row[1], row[2]
    except sqlite3.OperationalError as exc:
        pass

    wal_after = wal_file.stat().st_size if wal_file.exists() else 0
    now = storage.now_iso()

    conn.execute(
        """
        INSERT INTO wal_checkpoint_logs (mode, busy, log, checkpointed, wal_size_before, wal_size_after, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (mode, busy, log_frames, checkpointed, wal_before, wal_after, now),
    )
    conn.commit()

    return {
        "status": "success",
        "mode": mode,
        "busy": busy,
        "log_frames": log_frames,
        "checkpointed_frames": checkpointed,
        "wal_size_before_bytes": wal_before,
        "wal_size_after_bytes": wal_after,
        "created_at": now,
    }


def check_file_delta(filepath: Path) -> dict[str, Any]:
    """Compute checksum and check if file has changed against recorded dataset_states."""
    if not filepath.exists():
        raise HTTPException(404, f"File {filepath} not found")

    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    checksum = h.hexdigest()

    conn = storage._conn()
    row = conn.execute(
        "SELECT * FROM dataset_states WHERE checksum=?", (checksum,)
    ).fetchone()

    has_changed = row is None
    return {
        "filepath": str(filepath),
        "checksum": checksum,
        "is_known": not has_changed,
        "existing_record": dict(row) if row else None,
    }


# ---------------------------------------------------------------------------
# Item 1: Automated Background Pipeline (raw -> staging -> views)
# ---------------------------------------------------------------------------
def process_raw_pipeline() -> dict[str, Any]:
    """Scan raw dataset directories, parse via report_presets, promote to staging, and update views."""
    processed = []
    errors = []

    for domain in DOMAINS:
        raw_domain_dir = RAW_DIR / domain
        if not raw_domain_dir.exists():
            continue

        for filepath in raw_domain_dir.iterdir():
            if not filepath.is_file() or filepath.name.startswith("."):
                continue

            # Delta check
            delta_info = check_file_delta(filepath)
            raw_id = f"raw_{domain}_{filepath.name}"

            if delta_info["is_known"]:
                # Check if staging copy already exists
                staging_path = STAGING_DIR / domain / filepath.name
                if staging_path.exists():
                    continue

            try:
                # Detect format signature via report_presets
                content = filepath.read_bytes()
                preset_info = report_presets.detect_report_format(filename=filepath.name)

                # Save copy into staging
                staging_dir = STAGING_DIR / domain
                staging_dir.mkdir(parents=True, exist_ok=True)
                staging_path = staging_dir / filepath.name
                staging_path.write_bytes(content)

                record_count = 0
                if filepath.suffix.lower() in (".csv", ".tsv", ".txt"):
                    try:
                        parsed_rows = report_presets.parse_delimited(filepath, preset_info.get("preset") or {})
                        record_count = len(parsed_rows)
                    except Exception:
                        record_count = 0

                # Register raw + staging datasets
                register_dataset(
                    filename=filepath.name,
                    content_bytes=content,
                    domain=domain,
                    state="raw",
                    metadata={"auto_detected_preset": preset_info.get("preset_key")},
                    record_count=record_count,
                )

                promote_dataset(
                    dataset_id=raw_id,
                    target_state="staging",
                    target_domain=domain,
                )

                processed.append({
                    "filename": filepath.name,
                    "domain": domain,
                    "preset": preset_info.get("preset_key"),
                    "records": record_count,
                })
            except Exception as exc:
                errors.append({"filename": filepath.name, "error": str(exc)})

    # Refresh cached views after processing
    refresh_all_views_internal()

    # Trigger WAL checkpoint if WAL > 5MB
    wal_file = storage.DB_PATH.with_suffix(".db-wal")
    if wal_file.exists() and wal_file.stat().st_size > 5 * 1024 * 1024:
        checkpoint_wal("PASSIVE")

    return {
        "status": "complete",
        "processed_count": len(processed),
        "processed": processed,
        "errors": errors,
        "timestamp": storage.now_iso(),
    }


def start_background_pipeline() -> None:
    """Start periodic background pipeline thread."""
    global _PIPELINE_THREAD, _PIPELINE_RUNNING
    if _PIPELINE_RUNNING:
        return

    _PIPELINE_RUNNING = True

    def _loop():
        while _PIPELINE_RUNNING:
            try:
                process_raw_pipeline()
            except Exception:
                pass
            time.sleep(30)

    _PIPELINE_THREAD = threading.Thread(target=_loop, daemon=True, name="DatasetPipelineThread")
    _PIPELINE_THREAD.start()


# ---------------------------------------------------------------------------
# Item 6: Visual Dataset State Diffing (Raw vs. Staging vs. DB)
# ---------------------------------------------------------------------------
def diff_dataset_states(
    raw_dataset_id: str | None = None,
    staging_dataset_id: str | None = None,
    db_table: str = "products",
) -> dict[str, Any]:
    """Compute structured diff between raw file, staging file, and live database state."""
    init_dataset_store()
    conn = storage._conn()

    raw_item = None
    staging_item = None

    if raw_dataset_id:
        r = conn.execute("SELECT * FROM dataset_states WHERE dataset_id=?", (raw_dataset_id,)).fetchone()
        raw_item = dict(r) if r else None

    if staging_dataset_id:
        s = conn.execute("SELECT * FROM dataset_states WHERE dataset_id=?", (staging_dataset_id,)).fetchone()
        staging_item = dict(s) if s else None

    raw_records = []
    staging_records = []

    if raw_item:
        raw_p = LOCAL_STORE_DIR / raw_item["file_path"]
        if raw_p.exists() and raw_p.suffix.lower() in (".csv", ".tsv", ".txt"):
            try:
                preset_info = report_presets.detect_report_format(filename=raw_p.name)
                raw_records = report_presets.parse_delimited(raw_p, preset_info.get("preset") or {})
            except Exception:
                pass
            if not raw_records:
                import csv
                delimiter = "\t" if raw_p.suffix.lower() == ".tsv" else ","
                try:
                    with open(raw_p, "r", encoding="utf-8-sig", errors="replace") as f:
                        raw_records = [dict(r) for r in csv.DictReader(f, delimiter=delimiter)]
                except Exception:
                    pass

    if staging_item:
        stag_p = LOCAL_STORE_DIR / staging_item["file_path"]
        if stag_p.exists() and stag_p.suffix.lower() in (".csv", ".tsv", ".txt"):
            try:
                preset_info = report_presets.detect_report_format(filename=stag_p.name)
                staging_records = report_presets.parse_delimited(stag_p, preset_info.get("preset") or {})
            except Exception:
                pass
            if not staging_records:
                import csv
                delimiter = "\t" if stag_p.suffix.lower() == ".tsv" else ","
                try:
                    with open(stag_p, "r", encoding="utf-8-sig", errors="replace") as f:
                        staging_records = [dict(r) for r in csv.DictReader(f, delimiter=delimiter)]
                except Exception:
                    pass

    # DB sample
    db_records = storage.list_products(limit=50) if db_table == "products" else []

    # Column / Header extraction
    raw_headers = list(raw_records[0].keys()) if raw_records else []
    staging_headers = list(staging_records[0].keys()) if staging_records else []
    db_headers = list(db_records[0].keys()) if db_records else []

    header_added = [h for h in staging_headers if h not in raw_headers] if raw_headers else []
    header_removed = [h for h in raw_headers if h not in staging_headers] if raw_headers and staging_headers else []

    return {
        "raw_dataset_id": raw_dataset_id,
        "staging_dataset_id": staging_dataset_id,
        "db_table": db_table,
        "counts": {
            "raw_records": len(raw_records),
            "staging_records": len(staging_records),
            "db_records": len(db_records),
        },
        "headers": {
            "raw": raw_headers,
            "staging": staging_headers,
            "db": db_headers,
            "added_in_staging": header_added,
            "removed_in_staging": header_removed,
        },
        "samples": {
            "raw": raw_records[:3],
            "staging": staging_records[:3],
            "db": db_records[:3],
        },
        "timestamp": storage.now_iso(),
    }


# ---------------------------------------------------------------------------
# Backup & Dataset State Basics
# ---------------------------------------------------------------------------
def backup_local_db(note: str = "manual_backup") -> dict[str, Any]:
    """Create local database backup in data/local-store/backups."""
    init_dataset_store()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    backup_id = f"backup_{stamp}"

    db_backup_filename = f"conductor_{stamp}.db"
    db_backup_path = BACKUPS_DIR / db_backup_filename

    conn = storage._conn()
    conn.commit()
    backup_conn = sqlite3.connect(db_backup_path)
    with backup_conn:
        conn.backup(backup_conn)
    backup_conn.close()

    total_size = db_backup_path.stat().st_size

    spine_backup_filename = None
    spine_source = LOCAL_STORE_DIR / "spine.accdb"
    if not spine_source.exists():
        spine_source = DATA_DIR / "spine.accdb"

    if spine_source.exists():
        spine_backup_filename = f"spine_{stamp}.accdb"
        spine_backup_path = BACKUPS_DIR / spine_backup_filename
        shutil.copy2(spine_source, spine_backup_path)
        total_size += spine_backup_path.stat().st_size

    config_backup_filename = f"config_snapshot_{stamp}.json"
    config_backup_path = BACKUPS_DIR / config_backup_filename
    config_snapshot = {}

    for cfg_name in [
        "asana.json", "chat.json", "model-catalog.json", "provider-keys.json",
        "spapi.json", "supabase.json", "ui.json", "mcp.json", "keepa.json",
    ]:
        cfg_file = DATA_DIR / cfg_name
        if cfg_file.exists():
            try:
                config_snapshot[cfg_name] = json.loads(cfg_file.read_text(encoding="utf-8"))
            except Exception:
                pass

    config_backup_path.write_text(json.dumps(config_snapshot, indent=2), encoding="utf-8")
    total_size += config_backup_path.stat().st_size
    created_at = storage.now_iso()

    conn.execute(
        """
        INSERT INTO local_store_backups (backup_id, db_path, spine_path, config_path, file_size, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (backup_id, str(db_backup_filename), spine_backup_filename, config_backup_filename, total_size, created_at),
    )
    conn.commit()
    prune_old_backups(keep=10)

    return {
        "backup_id": backup_id,
        "status": "success",
        "db_backup": db_backup_filename,
        "spine_backup": spine_backup_filename,
        "config_backup": config_backup_filename,
        "total_size_bytes": total_size,
        "created_at": created_at,
        "note": note,
    }


def _parse_iso_datetime(dt_str: str) -> datetime | None:
    if not dt_str:
        return None
    try:
        if dt_str.endswith("Z"):
            dt_str = dt_str[:-1] + "+00:00"
        dt = datetime.fromisoformat(dt_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def prune_backups(max_backups: int = 10, max_age_days: int = 30) -> dict[str, Any]:
    """Prune local DB backups based on maximum retention count and age in days."""
    init_dataset_store()
    conn = storage._conn()
    rows = conn.execute("SELECT * FROM local_store_backups ORDER BY id DESC").fetchall()

    now_dt = datetime.now(timezone.utc)
    now_ts = time.time()

    deleted_ids = []
    deleted_backups = []
    deleted_files = []

    for index, row in enumerate(rows):
        b_dict = dict(row)
        b_id = b_dict["id"]
        backup_id = b_dict["backup_id"]
        created_at_str = b_dict.get("created_at")

        should_delete = False
        reason = None

        if max_backups is not None and max_backups >= 0 and index >= max_backups:
            should_delete = True
            reason = f"exceeds max_backups count ({max_backups})"

        if not should_delete and max_age_days is not None and max_age_days >= 0:
            age_days = None
            dt = _parse_iso_datetime(created_at_str)
            if dt:
                age_days = (now_dt - dt).total_seconds() / 86400.0
            else:
                db_fname = b_dict.get("db_path")
                if db_fname:
                    fpath = BACKUPS_DIR / db_fname
                    if fpath.exists():
                        age_days = (now_ts - fpath.stat().st_mtime) / 86400.0

            if age_days is not None and age_days > max_age_days:
                should_delete = True
                reason = f"exceeds max_age_days ({max_age_days} days, age is {age_days:.1f} days)"

        if should_delete:
            for field in ("db_path", "spine_path", "config_path"):
                fname = b_dict.get(field)
                if fname:
                    fpath = BACKUPS_DIR / fname
                    if fpath.exists():
                        try:
                            fpath.unlink()
                            deleted_files.append(fname)
                        except OSError:
                            pass
            conn.execute("DELETE FROM local_store_backups WHERE id=?", (b_id,))
            deleted_ids.append(b_id)
            deleted_backups.append({"backup_id": backup_id, "reason": reason})

    conn.commit()

    return {
        "status": "success",
        "pruned_count": len(deleted_ids),
        "pruned_backups": deleted_backups,
        "deleted_files": deleted_files,
        "remaining_backups": len(rows) - len(deleted_ids),
        "max_backups": max_backups,
        "max_age_days": max_age_days,
        "timestamp": storage.now_iso(),
    }


def prune_old_backups(keep: int = 10) -> None:
    prune_backups(max_backups=keep, max_age_days=30)


def list_backups() -> list[dict[str, Any]]:
    conn = storage._conn()
    rows = conn.execute("SELECT * FROM local_store_backups ORDER BY id DESC").fetchall()
    return [dict(r) for r in rows]


def register_dataset(
    filename: str,
    content_bytes: bytes,
    domain: str = "reports",
    state: str = "raw",
    metadata: dict | None = None,
    record_count: int = 0,
) -> dict[str, Any]:
    init_dataset_store()
    if state not in STATES:
        raise HTTPException(400, f"Invalid state '{state}'")
    if domain not in DOMAINS:
        raise HTTPException(400, f"Invalid domain '{domain}'")

    target_dir = LOCAL_STORE_DIR / state / domain
    target_dir.mkdir(parents=True, exist_ok=True)

    target_path = target_dir / filename
    target_path.write_bytes(content_bytes)

    file_size = len(content_bytes)
    checksum = hashlib.sha256(content_bytes).hexdigest()
    dataset_id = f"{state}_{domain}_{filename}"
    now = storage.now_iso()

    conn = storage._conn()
    conn.execute(
        """
        INSERT INTO dataset_states
        (dataset_id, filename, domain, state, file_path, record_count, file_size, checksum, metadata, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(dataset_id) DO UPDATE SET
            file_size=excluded.file_size,
            checksum=excluded.checksum,
            record_count=excluded.record_count,
            metadata=excluded.metadata,
            updated_at=excluded.updated_at
        """,
        (
            dataset_id, filename, domain, state,
            str(target_path.relative_to(LOCAL_STORE_DIR)),
            record_count, file_size, checksum,
            json.dumps(metadata or {}), now, now,
        ),
    )
    conn.commit()
    sync_states_manifest()

    return {
        "dataset_id": dataset_id,
        "filename": filename,
        "domain": domain,
        "state": state,
        "file_path": str(target_path),
        "file_size": file_size,
        "checksum": checksum,
        "updated_at": now,
    }


def promote_dataset(
    dataset_id: str,
    target_state: str,
    target_domain: str | None = None,
) -> dict[str, Any]:
    init_dataset_store()
    if target_state not in STATES:
        raise HTTPException(400, f"Invalid target state '{target_state}'")

    conn = storage._conn()
    row = conn.execute("SELECT * FROM dataset_states WHERE dataset_id=?", (dataset_id,)).fetchone()
    if not row:
        raise HTTPException(404, f"Dataset '{dataset_id}' not found")

    item = dict(row)
    source_path = LOCAL_STORE_DIR / item["file_path"]
    if not source_path.exists():
        raise HTTPException(404, f"Source file no longer exists at {source_path}")

    domain = target_domain or item["domain"]
    filename = item["filename"]
    dest_dir = LOCAL_STORE_DIR / target_state / domain
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / filename

    shutil.copy2(source_path, dest_path)
    new_dataset_id = f"{target_state}_{domain}_{filename}"
    now = storage.now_iso()

    conn.execute(
        """
        INSERT INTO dataset_states
        (dataset_id, filename, domain, state, file_path, record_count, file_size, checksum, metadata, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(dataset_id) DO UPDATE SET
            file_size=excluded.file_size,
            checksum=excluded.checksum,
            record_count=excluded.record_count,
            metadata=excluded.metadata,
            updated_at=excluded.updated_at
        """,
        (
            new_dataset_id, filename, domain, target_state,
            str(dest_path.relative_to(LOCAL_STORE_DIR)),
            item["record_count"], item["file_size"], item["checksum"],
            item["metadata"], item["created_at"], now,
        ),
    )
    conn.commit()
    sync_states_manifest()

    return {
        "previous_dataset_id": dataset_id,
        "new_dataset_id": new_dataset_id,
        "domain": domain,
        "state": target_state,
        "file_path": str(dest_path),
        "updated_at": now,
    }


def list_datasets(domain: str | None = None, state: str | None = None, q: str = "") -> list[dict[str, Any]]:
    conn = storage._conn()
    query = "SELECT * FROM dataset_states WHERE 1=1"
    params: list[Any] = []

    if domain:
        query += " AND domain=?"
        params.append(domain)
    if state:
        query += " AND state=?"
        params.append(state)
    if q:
        query += " AND (filename LIKE ? OR dataset_id LIKE ?)"
        params.append(f"%{q}%")
        params.append(f"%{q}%")

    query += " ORDER BY updated_at DESC"
    rows = conn.execute(query, params).fetchall()

    out = []
    for r in rows:
        d = dict(r)
        d["metadata"] = json.loads(d.get("metadata") or "{}")
        out.append(d)
    return out


def sync_states_manifest() -> None:
    datasets = list_datasets()
    summary = {
        "synced_at": storage.now_iso(),
        "total_datasets": len(datasets),
        "states": {s: sum(1 for d in datasets if d["state"] == s) for s in STATES},
        "domains": {dom: sum(1 for d in datasets if d["domain"] == dom) for dom in DOMAINS},
        "datasets": datasets,
    }
    (STATES_DIR / "dataset_states.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


def get_page_view(page_id: str) -> dict[str, Any]:
    if page_id not in PAGES:
        raise HTTPException(400, f"Unknown page '{page_id}'")

    view_file = PAGE_VIEWS_DIR / f"{page_id}.json"
    if view_file.exists():
        try:
            return json.loads(view_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    conn = storage._conn()
    row = conn.execute("SELECT view_data FROM page_views_cache WHERE page_id=?", (page_id,)).fetchone()
    if row:
        try:
            return json.loads(row["view_data"])
        except Exception:
            pass

    fresh = _generate_default_page_view(page_id)
    update_page_view(page_id, fresh)
    return fresh


def update_page_view(page_id: str, view_data: dict[str, Any]) -> dict[str, Any]:
    if page_id not in PAGES:
        raise HTTPException(400, f"Unknown page '{page_id}'")

    now = storage.now_iso()
    payload = {"page_id": page_id, "updated_at": now, "data": view_data.get("data", view_data)}

    (PAGE_VIEWS_DIR / f"{page_id}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _update_db_page_view(page_id, payload)
    return payload


def _update_db_page_view(page_id: str, payload: dict[str, Any]) -> None:
    now = payload.get("updated_at") or storage.now_iso()
    conn = storage._conn()
    conn.execute(
        """
        INSERT INTO page_views_cache (page_id, view_data, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(page_id) DO UPDATE SET
            view_data=excluded.view_data,
            updated_at=excluded.updated_at
        """,
        (page_id, json.dumps(payload), now),
    )
    conn.commit()


def refresh_all_views_internal() -> dict[str, Any]:
    results = {}
    for page_id in PAGES:
        default_v = _generate_default_page_view(page_id)
        results[page_id] = update_page_view(page_id, default_v)
    return {"status": "success", "refreshed_pages": list(results.keys())}


def get_dataset_summary() -> dict[str, Any]:
    init_dataset_store()
    datasets = list_datasets()
    backups = list_backups()

    tree: dict[str, dict[str, int]] = {s: {} for s in STATES}
    for state in STATES:
        state_path = LOCAL_STORE_DIR / state
        if state_path.exists():
            for domain in DOMAINS:
                dom_path = state_path / domain
                if dom_path.exists():
                    tree[state][domain] = sum(1 for f in dom_path.iterdir() if f.is_file())

    backup_bytes = sum(b.get("file_size", 0) for b in backups)
    return {
        "local_store_path": str(LOCAL_STORE_DIR),
        "domains": DOMAINS,
        "states": STATES,
        "pages": PAGES,
        "dataset_count": len(datasets),
        "backup_count": len(backups),
        "backup_total_bytes": backup_bytes,
        "latest_backup": backups[0] if backups else None,
        "state_tree": tree,
        "updated_at": storage.now_iso(),
    }


# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------
@router.get("/summary")
def api_summary():
    return get_dataset_summary()


@router.get("/datasets")
def api_list_datasets(domain: str | None = None, state: str | None = None, q: str = ""):
    return {"datasets": list_datasets(domain=domain, state=state, q=q)}


@router.post("/datasets/register", status_code=201)
async def api_register_dataset(
    file: UploadFile = File(...),
    domain: str = Form("reports"),
    state: str = Form("raw"),
    metadata: str = Form("{}"),
):
    content = await file.read()
    try:
        meta_dict = json.loads(metadata)
    except Exception:
        meta_dict = {}

    return register_dataset(
        filename=file.filename or "file.bin",
        content_bytes=content,
        domain=domain,
        state=state,
        metadata=meta_dict,
    )


@router.post("/datasets/promote")
def api_promote_dataset(body: dict):
    dataset_id = str(body.get("dataset_id") or "")
    target_state = str(body.get("target_state") or "")
    target_domain = body.get("target_domain")
    if not dataset_id or not target_state:
        raise HTTPException(400, "dataset_id and target_state are required")
    return promote_dataset(dataset_id, target_state, target_domain)


@router.post("/pipeline/run")
def api_run_pipeline():
    """Trigger the raw-to-staging automated pipeline scan manually."""
    return process_raw_pipeline()


@router.post("/wal-checkpoint")
def api_wal_checkpoint(body: dict | None = None):
    """Trigger WAL checkpoint on conductor.db."""
    mode = str((body or {}).get("mode") or "PASSIVE")
    return checkpoint_wal(mode)


@router.post("/diff")
def api_diff_datasets(body: dict):
    """Compute side-by-side diff between raw, staging, and DB records."""
    raw_id = body.get("raw_dataset_id")
    staging_id = body.get("staging_dataset_id")
    db_table = str(body.get("db_table") or "products")
    return diff_dataset_states(raw_dataset_id=raw_id, staging_dataset_id=staging_id, db_table=db_table)


@router.post("/backup", status_code=201)
def api_create_backup(body: dict | None = None):
    note = str((body or {}).get("note") or "manual_backup")
    return backup_local_db(note=note)


@router.get("/domains")
def api_get_domains():
    return {"domains": get_domains()}


@router.post("/domains/register")
def api_register_domain(body: dict):
    domain = body.get("domain") or body.get("domains")
    if not domain:
        raise HTTPException(400, "domain or domains field is required")
    updated = register_domain(domain)
    return {"status": "success", "domains": updated}


@router.get("/pages")
def api_get_pages():
    return {"pages": get_pages()}


@router.post("/pages/register")
def api_register_page(body: dict):
    page = body.get("page") or body.get("pages")
    if not page:
        raise HTTPException(400, "page or pages field is required")
    updated = register_page(page)
    return {"status": "success", "pages": updated}


@router.get("/backups")
def api_list_backups():
    return {"backups": list_backups()}


@router.post("/prune")
def api_prune_backups(
    body: dict | None = None,
    max_backups: int | None = Query(None),
    max_age_days: int | None = Query(None),
):
    body = body or {}
    mb = body.get("max_backups") if "max_backups" in body else max_backups
    mad = body.get("max_age_days") if "max_age_days" in body else max_age_days

    try:
        mb = int(mb) if mb is not None else 10
    except (ValueError, TypeError):
        mb = 10

    try:
        mad = int(mad) if mad is not None else 30
    except (ValueError, TypeError):
        mad = 30

    return prune_backups(max_backups=mb, max_age_days=mad)


@router.post("/views/refresh-all")
def api_refresh_all_views():
    return refresh_all_views_internal()


@router.get("/views/{page_id}")
def api_get_page_view(page_id: str):
    return get_page_view(page_id)


@router.post("/views/{page_id}")
def api_update_page_view(page_id: str, body: dict):
    return update_page_view(page_id, body)
