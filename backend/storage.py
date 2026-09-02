"""SQLite storage layer for the compliance agent."""
import json
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "conductor.db"
UPLOAD_DIR = DATA_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

_local = threading.local()


def _conn() -> sqlite3.Connection:
    """Per-thread connection so background jobs don't share connections."""
    if not hasattr(_local, "conn"):
        conn = sqlite3.connect(DB_PATH, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        _local.conn = conn
    return _local.conn


def init_db() -> None:
    conn = _conn()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sku TEXT NOT NULL,
            name TEXT NOT NULL,
            category TEXT DEFAULT 'general',
            market TEXT DEFAULT 'US',
            attributes TEXT DEFAULT '{}',
            source TEXT DEFAULT 'manual',
            tags TEXT DEFAULT '[]',          -- json: list of data-source tags
            file_id INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            regulation TEXT NOT NULL,
            status TEXT NOT NULL,           -- pass | fail | review | not_applicable
            severity TEXT NOT NULL,         -- blocker | warning | info | ok
            score INTEGER DEFAULT 0,        -- 0-100 compliance score
            findings TEXT DEFAULT '[]',     -- json list
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            upload_id TEXT NOT NULL UNIQUE,
            filename TEXT NOT NULL,
            total_size INTEGER NOT NULL,
            chunk_size INTEGER NOT NULL,
            received_chunks TEXT DEFAULT '[]',
            status TEXT DEFAULT 'uploading',  -- uploading | ready | parsing | done | error
            record_count INTEGER DEFAULT 0,
            error TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,
            ref_id INTEGER,
            status TEXT DEFAULT 'queued',    -- queued | running | done | error
            progress REAL DEFAULT 0,
            message TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            method TEXT NOT NULL,
            path TEXT NOT NULL,
            client TEXT DEFAULT '',
            status INTEGER DEFAULT 0,
            latency_ms REAL DEFAULT 0,
            body_preview TEXT DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            priority TEXT DEFAULT 'P2',
            text TEXT NOT NULL,
            status TEXT DEFAULT 'open',      -- open | done | blocked
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS asana_workspaces (
            gid TEXT PRIMARY KEY,
            name TEXT DEFAULT '',
            synced_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS asana_users (
            gid TEXT PRIMARY KEY,
            name TEXT DEFAULT '',
            email TEXT DEFAULT '',
            synced_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS asana_teams (
            gid TEXT PRIMARY KEY,
            name TEXT DEFAULT '',
            description TEXT DEFAULT '',
            synced_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS asana_projects (
            gid TEXT PRIMARY KEY,
            name TEXT DEFAULT '',
            team_gid TEXT DEFAULT '',
            team_name TEXT DEFAULT '',
            archived INTEGER DEFAULT 0,
            color TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            created_at TEXT DEFAULT '',
            modified_at TEXT DEFAULT '',
            permalink TEXT DEFAULT '',
            synced_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS asana_custom_fields (
            gid TEXT PRIMARY KEY,
            name TEXT DEFAULT '',
            type TEXT DEFAULT '',
            description TEXT DEFAULT '',
            enum_options TEXT DEFAULT '[]',
            synced_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS asana_tasks (
            gid TEXT PRIMARY KEY,
            name TEXT DEFAULT '',
            resource_subtype TEXT DEFAULT '',
            project_gid TEXT DEFAULT '',
            project_name TEXT DEFAULT '',
            section TEXT DEFAULT '',
            team_gid TEXT DEFAULT '',
            team_name TEXT DEFAULT '',
            assignee_gid TEXT DEFAULT '',
            assignee_name TEXT DEFAULT '',
            assignee_email TEXT DEFAULT '',
            due_on TEXT DEFAULT '',
            start_on TEXT DEFAULT '',
            completed INTEGER DEFAULT 0,
            completed_at TEXT DEFAULT '',
            created_at TEXT DEFAULT '',
            modified_at TEXT DEFAULT '',
            permalink TEXT DEFAULT '',
            parent_gid TEXT DEFAULT '',
            parent_name TEXT DEFAULT '',
            num_subtasks INTEGER DEFAULT 0,
            tags TEXT DEFAULT '[]',
            followers TEXT DEFAULT '[]',
            dependencies TEXT DEFAULT '[]',
            dependents TEXT DEFAULT '[]',
            notes TEXT DEFAULT '',
            custom_fields TEXT DEFAULT '[]',
            memberships TEXT DEFAULT '[]',
            weight REAL DEFAULT 1.0,
            synced_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_asana_tasks_project ON asana_tasks(project_gid);
        CREATE INDEX IF NOT EXISTS idx_asana_tasks_assignee ON asana_tasks(assignee_gid);
        CREATE INDEX IF NOT EXISTS idx_asana_tasks_completed ON asana_tasks(completed);
        CREATE INDEX IF NOT EXISTS idx_asana_tasks_due ON asana_tasks(due_on);
        CREATE TABLE IF NOT EXISTS asana_stories (
            gid TEXT PRIMARY KEY,
            task_gid TEXT DEFAULT '',
            author TEXT DEFAULT '',
            author_email TEXT DEFAULT '',
            type TEXT DEFAULT 'system',
            text TEXT DEFAULT '',
            created_at TEXT DEFAULT '',
            is_pinned INTEGER DEFAULT 0,
            synced_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_asana_stories_task ON asana_stories(task_gid);
        CREATE TABLE IF NOT EXISTS asana_attachments (
            gid TEXT PRIMARY KEY,
            task_gid TEXT DEFAULT '',
            name TEXT DEFAULT '',
            host TEXT DEFAULT '',
            url TEXT DEFAULT '',
            view_url TEXT DEFAULT '',
            created_at TEXT DEFAULT '',
            synced_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_asana_attachments_task ON asana_attachments(task_gid);
        CREATE TABLE IF NOT EXISTS asana_subtasks (
            gid TEXT PRIMARY KEY,
            parent_task_gid TEXT DEFAULT '',
            name TEXT DEFAULT '',
            assignee_name TEXT DEFAULT '',
            assignee_email TEXT DEFAULT '',
            completed INTEGER DEFAULT 0,
            completed_at TEXT DEFAULT '',
            created_at TEXT DEFAULT '',
            due_on TEXT DEFAULT '',
            permalink TEXT DEFAULT '',
            synced_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_asana_subtasks_parent ON asana_subtasks(parent_task_gid);
        CREATE TABLE IF NOT EXISTS asana_sync_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mode TEXT DEFAULT 'all',
            status TEXT DEFAULT 'running',
            started_at TEXT NOT NULL,
            finished_at TEXT DEFAULT '',
            counts TEXT DEFAULT '{}',
            error TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS ingest_ai (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            kind TEXT NOT NULL,           -- flag | recommendation | enrichment
            title TEXT DEFAULT '',
            detail TEXT DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_ingest_ai_file ON ingest_ai(file_id);
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,
            title TEXT NOT NULL,
            meta TEXT DEFAULT '{}',
            data TEXT DEFAULT '{}',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS attribute_guidelines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            attribute TEXT NOT NULL,
            grouping TEXT DEFAULT 'attribute',   -- attribute | category | product_type | market | brand | all
            group_value TEXT DEFAULT '',
            rule_type TEXT NOT NULL,             -- required | allowed_values | pattern | min_length | max_length | range
            rule_value TEXT DEFAULT '',
            severity TEXT DEFAULT 'warning',     -- blocker | warning | info
            enabled INTEGER DEFAULT 1,
            note TEXT DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS flatfile_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            product_type TEXT DEFAULT '',
            columns TEXT DEFAULT '[]',           -- json: [{key,label,required,values,example}]
            header_note TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS data_views (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            source TEXT DEFAULT 'products',
            config TEXT DEFAULT '{}',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS features (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            spec TEXT DEFAULT '{}',           -- json: {rating_label, factors[], actions[], source_report}
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,               -- json-encoded (or plain string)
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS asana_task_memberships (
            task_gid TEXT NOT NULL,
            project_gid TEXT NOT NULL,
            project_name TEXT DEFAULT '',
            section_gid TEXT DEFAULT '',
            section_name TEXT DEFAULT '',
            team_gid TEXT DEFAULT '',
            team_name TEXT DEFAULT '',
            synced_at TEXT NOT NULL,
            PRIMARY KEY(task_gid, project_gid)
        );
        CREATE INDEX IF NOT EXISTS idx_asana_memberships_team ON asana_task_memberships(team_gid);
        CREATE INDEX IF NOT EXISTS idx_asana_memberships_project ON asana_task_memberships(project_gid);
        CREATE TABLE IF NOT EXISTS asana_task_custom_field_values (
            task_gid TEXT NOT NULL,
            custom_field_gid TEXT NOT NULL,
            field_name TEXT DEFAULT '',
            field_type TEXT DEFAULT '',
            value_text TEXT DEFAULT '',
            value_number REAL,
            value_date TEXT DEFAULT '',
            synced_at TEXT NOT NULL,
            PRIMARY KEY(task_gid, custom_field_gid)
        );
        CREATE INDEX IF NOT EXISTS idx_asana_cf_values_lookup ON asana_task_custom_field_values(custom_field_gid, value_text);
        CREATE TABLE IF NOT EXISTS asana_kpi_definitions (
            kpi_id TEXT PRIMARY KEY,
            team TEXT NOT NULL,
            label TEXT NOT NULL,
            unit TEXT NOT NULL,
            target_value REAL,
            target_direction TEXT NOT NULL DEFAULT 'higher_is_better',
            numerator_definition TEXT DEFAULT '',
            denominator_definition TEXT DEFAULT '',
            filters TEXT NOT NULL DEFAULT '[]',
            rollup_policy TEXT NOT NULL DEFAULT 'sum',
            workbook_source TEXT DEFAULT '',
            definition_status TEXT NOT NULL DEFAULT 'active',
            metadata TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS asana_kpi_facts (
            team TEXT NOT NULL,
            kpi_id TEXT NOT NULL,
            period_grain TEXT NOT NULL,
            period_start TEXT NOT NULL,
            period_end TEXT NOT NULL,
            snapshot_at TEXT NOT NULL DEFAULT '',
            numerator REAL,
            denominator REAL,
            value REAL,
            unit TEXT NOT NULL,
            target_value REAL,
            source_system TEXT NOT NULL,
            source_locator TEXT DEFAULT '',
            calculation_version TEXT NOT NULL DEFAULT 'v1',
            metadata TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL,
            PRIMARY KEY(team, kpi_id, period_grain, period_start, snapshot_at)
        );
        CREATE INDEX IF NOT EXISTS idx_asana_kpi_facts_period ON asana_kpi_facts(team, period_grain, period_start);
        CREATE TABLE IF NOT EXISTS asana_kpi_drilldown_records (
            team TEXT NOT NULL,
            kpi_id TEXT NOT NULL,
            period_grain TEXT NOT NULL,
            period_start TEXT NOT NULL,
            record_role TEXT NOT NULL,
            record_type TEXT NOT NULL,
            record_id TEXT NOT NULL,
            record_name TEXT DEFAULT '',
            payload TEXT NOT NULL DEFAULT '{}',
            source_locator TEXT DEFAULT '',
            PRIMARY KEY(team, kpi_id, period_grain, period_start, record_role, record_id)
        );
        CREATE INDEX IF NOT EXISTS idx_asana_kpi_drilldown_scope ON asana_kpi_drilldown_records(team, kpi_id, period_grain, period_start);
        """
    )
    conn.commit()
    # Migration: products.file_id on databases created before the AI-ingest pass
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(products)").fetchall()]
    if "file_id" not in cols:
        conn.execute("ALTER TABLE products ADD COLUMN file_id INTEGER")
    if "updated_at" not in cols:
        conn.execute("ALTER TABLE products ADD COLUMN updated_at TEXT")
        conn.execute("UPDATE products SET updated_at=created_at WHERE updated_at IS NULL OR updated_at='' ")
    if "tags" not in cols:
        conn.execute("ALTER TABLE products ADD COLUMN tags TEXT DEFAULT '[]'")
    conn.commit()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------
# Products
# --------------------------------------------------------------------------
def create_product(sku: str, name: str, category: str = "general",
                   market: str = "US", attributes: dict | None = None,
                   source: str = "manual", file_id: int | None = None,
                   tags: list | None = None) -> int:
    conn = _conn()
    stamp = now_iso()
    cur = conn.execute(
        "INSERT INTO products (sku, name, category, market, attributes, source, tags, file_id, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (sku, name, category, market, json.dumps(attributes or {}), source,
         json.dumps([str(t).strip() for t in (tags or []) if str(t).strip()]),
         file_id, stamp, stamp),
    )
    conn.commit()
    return cur.lastrowid


def update_product(product_id: int, **fields) -> bool:
    """Update whitelisted product fields. attributes must be a dict (merged by caller)."""
    allowed = {"sku", "name", "category", "market", "attributes", "source", "tags", "file_id"}
    sets, vals = [], []
    for k, v in fields.items():
        if k not in allowed:
            continue
        if k == "attributes":
            v = json.dumps(v if isinstance(v, dict) else {})
        if k == "tags":
            v = json.dumps([str(t).strip() for t in (v or []) if str(t).strip()])
        sets.append(f"{k}=?")
        vals.append(v)
    if not sets:
        return False
    sets.append("updated_at=?")
    vals.append(now_iso())
    vals.append(product_id)
    conn = _conn()
    conn.execute(f"UPDATE products SET {', '.join(sets)} WHERE id=?", vals)
    conn.commit()
    return True


def list_products_by_file(file_id: int) -> list[dict]:
    rows = _conn().execute(
        "SELECT * FROM products WHERE file_id=? ORDER BY id", (file_id,)
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["attributes"] = json.loads(d.get("attributes") or "{}")
        d["tags"] = json.loads(d.get("tags") or "[]")
        out.append(d)
    return out


# --------------------------------------------------------------------------
# AI ingest findings (categorization, cleaning, flags, recommendations)
# --------------------------------------------------------------------------
def save_ai_finding(file_id: int, product_id: int, kind: str,
                    title: str = "", detail: str = "") -> int:
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO ingest_ai (file_id, product_id, kind, title, detail, created_at) "
        "VALUES (?,?,?,?,?,?)",
        (file_id, product_id, kind, title, detail, now_iso()),
    )
    conn.commit()
    return cur.lastrowid


def clear_ai_findings(file_id: int) -> None:
    conn = _conn()
    conn.execute("DELETE FROM ingest_ai WHERE file_id=?", (file_id,))
    conn.commit()


def list_ai_findings(file_id: int | None = None, limit: int = 200) -> list[dict]:
    if file_id is not None:
        rows = _conn().execute(
            "SELECT * FROM ingest_ai WHERE file_id=? ORDER BY id DESC LIMIT ?",
            (file_id, limit),
        ).fetchall()
    else:
        rows = _conn().execute(
            "SELECT * FROM ingest_ai ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_product(product_id: int) -> dict | None:
    row = _conn().execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["attributes"] = json.loads(d.get("attributes") or "{}")
    d["tags"] = json.loads(d.get("tags") or "[]")
    return d


def list_products(limit: int = 200, tag: str | None = None) -> list[dict]:
    rows = _conn().execute("SELECT * FROM products ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["attributes"] = json.loads(d.get("attributes") or "{}")
        d["tags"] = json.loads(d.get("tags") or "[]")
        if tag and tag not in d["tags"]:
            continue
        out.append(d)
    return out


def list_tags() -> list[dict]:
    """Distinct product tags with counts, most frequent first."""
    counts: dict[str, int] = {}
    rows = _conn().execute("SELECT tags FROM products").fetchall()
    for r in rows:
        for t in json.loads(r["tags"] or "[]"):
            t = str(t).strip()
            if t:
                counts[t] = counts.get(t, 0) + 1
    return [{"tag": t, "count": n} for t, n in
            sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]


def count_products() -> int:
    return _conn().execute("SELECT COUNT(*) AS n FROM products").fetchone()["n"]


# --------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------
def save_check(product_id: int, regulation: str, status: str, severity: str,
               score: int, findings: list) -> int:
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO checks (product_id, regulation, status, severity, score, findings, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (product_id, regulation, status, severity, score, json.dumps(findings), now_iso()),
    )
    conn.commit()
    return cur.lastrowid


def clear_checks(product_id: int) -> None:
    conn = _conn()
    conn.execute("DELETE FROM checks WHERE product_id=?", (product_id,))
    conn.commit()


def list_checks(product_id: int | None = None, limit: int = 500) -> list[dict]:
    if product_id is not None:
        rows = _conn().execute(
            "SELECT * FROM checks WHERE product_id=? ORDER BY id DESC LIMIT ?",
            (product_id, limit),
        ).fetchall()
    else:
        rows = _conn().execute("SELECT * FROM checks ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["findings"] = json.loads(d.get("findings") or "[]")
        out.append(d)
    return out


def latest_check_by_product(product_id: int) -> dict | None:
    rows = list_checks(product_id=product_id, limit=1)
    return rows[0] if rows else None


# --------------------------------------------------------------------------
# Files / ingestion
# --------------------------------------------------------------------------
def create_file(upload_id: str, filename: str, total_size: int, chunk_size: int) -> int:
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO files (upload_id, filename, total_size, chunk_size, created_at) VALUES (?,?,?,?,?)",
        (upload_id, filename, total_size, chunk_size, now_iso()),
    )
    conn.commit()
    return cur.lastrowid


def get_file_by_upload(upload_id: str) -> dict | None:
    row = _conn().execute("SELECT * FROM files WHERE upload_id=?", (upload_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["received_chunks"] = json.loads(d.get("received_chunks") or "[]")
    return d


def update_file(upload_id: str, **fields) -> None:
    allowed = {"received_chunks", "status", "error", "record_count"}
    sets, vals = [], []
    for k, v in fields.items():
        if k in allowed:
            sets.append(f"{k}=?")
            vals.append(json.dumps(v) if k == "received_chunks" else v)
    if not sets:
        return
    vals.append(upload_id)
    conn = _conn()
    conn.execute(f"UPDATE files SET {', '.join(sets)} WHERE upload_id=?", vals)
    conn.commit()


def list_files(limit: int = 100) -> list[dict]:
    rows = _conn().execute("SELECT * FROM files ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["received_chunks"] = json.loads(d.get("received_chunks") or "[]")
        out.append(d)
    return out


# --------------------------------------------------------------------------
# Jobs
# --------------------------------------------------------------------------
def create_job(kind: str, ref_id: int | None = None) -> int:
    ts = now_iso()
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO jobs (kind, ref_id, status, created_at, updated_at) VALUES (?,?,?,?,?)",
        (kind, ref_id, "queued", ts, ts),
    )
    conn.commit()
    return cur.lastrowid


def update_job(job_id: int, **fields) -> None:
    allowed = {"status", "progress", "message"}
    sets, vals = [], []
    for k, v in fields.items():
        if k in allowed:
            sets.append(f"{k}=?")
            vals.append(v)
    sets.append("updated_at=?")
    vals.append(now_iso())
    vals.append(job_id)
    conn = _conn()
    conn.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE id=?", vals)
    conn.commit()


def get_job(job_id: int) -> dict | None:
    row = _conn().execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    return dict(row) if row else None


def list_jobs(limit: int = 50) -> list[dict]:
    rows = _conn().execute("SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


# --------------------------------------------------------------------------
# HTTP request log
# --------------------------------------------------------------------------
def log_request(method: str, path: str, client: str, status: int,
                latency_ms: float, body_preview: str = "") -> None:
    try:
        conn = _conn()
        conn.execute(
            "INSERT INTO requests (method, path, client, status, latency_ms, body_preview, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (method, path, client[:64], status, round(latency_ms, 2), body_preview[:2000], now_iso()),
        )
        conn.commit()
    except Exception:
        pass


def list_requests(limit: int = 100) -> list[dict]:
    rows = _conn().execute("SELECT * FROM requests ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


# --------------------------------------------------------------------------
# Action queue (tasks imported from Obsidian triage etc.)
# --------------------------------------------------------------------------
def import_tasks(items: list[dict]) -> int:
    """Upsert tasks by (source, text). Returns number inserted."""
    conn = _conn()
    inserted = 0
    for item in items:
        source = str(item.get("source") or "manual")[:300]
        text = str(item.get("text") or item.get("task") or "").strip()[:500]
        priority = str(item.get("priority") or "P2")[:8]
        if not text:
            continue
        existing = conn.execute(
            "SELECT id FROM tasks WHERE source=? AND text=? AND status='open'",
            (source, text),
        ).fetchone()
        if existing:
            continue
        ts = now_iso()
        conn.execute(
            "INSERT INTO tasks (source, priority, text, status, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?)",
            (source, priority, text, "open", ts, ts),
        )
        inserted += 1
    conn.commit()
    return inserted


def list_tasks(limit: int = 500, status: str | None = None) -> list[dict]:
    if status:
        rows = _conn().execute(
            "SELECT * FROM tasks WHERE status=? ORDER BY "
            "CASE priority WHEN 'P0' THEN 0 WHEN 'P1' THEN 1 ELSE 2 END, id DESC LIMIT ?",
            (status, limit),
        ).fetchall()
    else:
        rows = _conn().execute(
            "SELECT * FROM tasks ORDER BY CASE priority WHEN 'P0' THEN 0 WHEN 'P1' THEN 1 ELSE 2 END, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def update_task(task_id: int, status: str) -> bool:
    conn = _conn()
    cur = conn.execute(
        "UPDATE tasks SET status=?, updated_at=? WHERE id=?",
        (status, now_iso(), task_id),
    )
    conn.commit()
    return cur.rowcount > 0


def clear_done_tasks() -> int:
    conn = _conn()
    cur = conn.execute("DELETE FROM tasks WHERE status='done'")
    conn.commit()
    return cur.rowcount


# --------------------------------------------------------------------------
# Asana sync store
# --------------------------------------------------------------------------
def _upsert(table: str, fields: dict, exclude: set[str] | None = None) -> None:
    """INSERT OR REPLACE a row built from a field dict (JSON-encodes lists/dicts)."""
    cols = []
    vals = []
    for k, v in fields.items():
        if exclude and k in exclude:
            continue
        if v is None:
            v = ""
        if isinstance(v, (list, dict)):
            v = json.dumps(v)
        cols.append(k)
        vals.append(v)
    conn = _conn()
    placeholders = ",".join("?" * len(cols))
    conn.execute(
        f"INSERT OR REPLACE INTO {table} ({','.join(cols)}) VALUES ({placeholders})",
        vals,
    )
    conn.commit()


def merge_upsert(table: str, key_field: str, fields: dict, exclude: set[str] | None = None) -> None:
    """Merge-upsert a row, preserving any existing column not present in ``fields``.

    ``_upsert`` above is ``INSERT OR REPLACE``, which in SQLite deletes the conflicting row
    and inserts a new one built ONLY from the supplied columns — every column left out reverts
    to its schema default, it is not merged. That is correct for callers that always supply
    every column for a table (e.g. every ``upsert_asana_task`` call from a full Asana task
    fetch), but it silently destroys data for callers whose payload can be a strict subset of
    the schema — e.g. a Supabase-sourced Asana task record, which never carries locally-only
    derived fields such as ``asana_tasks.weight`` (computed by asana_sync.task_weight(), never
    returned by Asana's own API). Pulling such a record through ``_upsert`` would zero out
    ``weight`` (and any other locally-only column) on every pull, silently corrupting the KPI
    weighting that column drives. This function uses ``INSERT ... ON CONFLICT DO UPDATE`` so
    only the supplied columns are written; every other existing column is left untouched.

    Added for the Supabase pull path (see backend/supabase_sync.py:_asana_task_upsert). Every
    other existing caller of ``_upsert`` keeps using it unchanged.
    """
    cols = []
    vals = []
    for k, v in fields.items():
        if exclude and k in exclude:
            continue
        if v is None:
            v = ""
        if isinstance(v, (list, dict)):
            v = json.dumps(v)
        cols.append(k)
        vals.append(v)
    if key_field not in cols:
        raise ValueError(f"merge_upsert requires {key_field!r} in fields")
    conn = _conn()
    placeholders = ",".join("?" * len(cols))
    update_cols = [c for c in cols if c != key_field]
    if update_cols:
        update_clause = ", ".join(f"{c}=excluded.{c}" for c in update_cols)
        sql = (
            f"INSERT INTO {table} ({','.join(cols)}) VALUES ({placeholders}) "
            f"ON CONFLICT({key_field}) DO UPDATE SET {update_clause}"
        )
    else:
        sql = (
            f"INSERT INTO {table} ({','.join(cols)}) VALUES ({placeholders}) "
            f"ON CONFLICT({key_field}) DO NOTHING"
        )
    conn.execute(sql, vals)
    conn.commit()


def _decode_row(row: sqlite3.Row) -> dict:
    d = dict(row)
    for k in ("tags", "followers", "dependencies", "dependents",
              "custom_fields", "memberships", "enum_options", "counts"):
        if k in d and isinstance(d[k], str):
            try:
                d[k] = json.loads(d[k])
            except Exception:
                d[k] = []
    return d


def upsert_asana_workspace(gid: str, name: str) -> None:
    _upsert("asana_workspaces", {"gid": gid, "name": name, "synced_at": now_iso()})


def upsert_asana_user(gid: str, name: str, email: str) -> None:
    _upsert("asana_users", {"gid": gid, "name": name, "email": email, "synced_at": now_iso()})


def upsert_asana_team(gid: str, name: str, description: str) -> None:
    _upsert("asana_teams", {"gid": gid, "name": name, "description": description, "synced_at": now_iso()})


def upsert_asana_project(gid: str, name: str, team_gid: str, team_name: str,
                         archived: int, color: str, notes: str, created_at: str,
                         modified_at: str, permalink: str) -> None:
    _upsert("asana_projects", {
        "gid": gid, "name": name, "team_gid": team_gid, "team_name": team_name,
        "archived": archived, "color": color, "notes": notes,
        "created_at": created_at, "modified_at": modified_at,
        "permalink": permalink, "synced_at": now_iso(),
    })


def upsert_asana_custom_field(gid: str, name: str, type: str, description: str,
                              enum_options: list) -> None:
    _upsert("asana_custom_fields", {
        "gid": gid, "name": name, "type": type, "description": description,
        "enum_options": enum_options, "synced_at": now_iso(),
    })


def upsert_asana_task(gid: str, name: str, resource_subtype: str, project_gid: str,
                      project_name: str, section: str, team_gid: str, team_name: str,
                      assignee_gid: str, assignee_name: str, assignee_email: str,
                      due_on: str, start_on: str, completed: int, completed_at: str,
                      created_at: str, modified_at: str, permalink: str,
                      parent_gid: str, parent_name: str, num_subtasks: int,
                      tags: list, followers: list, dependencies: list,
                      dependents: list, notes: str, custom_fields: list,
                      memberships: list, weight: float) -> None:
    _upsert("asana_tasks", {
        "gid": gid, "name": name, "resource_subtype": resource_subtype,
        "project_gid": project_gid, "project_name": project_name, "section": section,
        "team_gid": team_gid, "team_name": team_name,
        "assignee_gid": assignee_gid, "assignee_name": assignee_name,
        "assignee_email": assignee_email, "due_on": due_on, "start_on": start_on,
        "completed": completed, "completed_at": completed_at,
        "created_at": created_at, "modified_at": modified_at, "permalink": permalink,
        "parent_gid": parent_gid, "parent_name": parent_name,
        "num_subtasks": num_subtasks, "tags": tags, "followers": followers,
        "dependencies": dependencies, "dependents": dependents, "notes": notes,
        "custom_fields": custom_fields, "memberships": memberships, "weight": weight,
        "synced_at": now_iso(),
    })


def upsert_asana_story(gid: str, task_gid: str, author: str, author_email: str,
                       type: str, text: str, created_at: str, is_pinned: int) -> None:
    _upsert("asana_stories", {
        "gid": gid, "task_gid": task_gid, "author": author, "author_email": author_email,
        "type": type, "text": text, "created_at": created_at,
        "is_pinned": is_pinned, "synced_at": now_iso(),
    })


def upsert_asana_attachment(gid: str, task_gid: str, name: str, host: str,
                            url: str, view_url: str, created_at: str) -> None:
    _upsert("asana_attachments", {
        "gid": gid, "task_gid": task_gid, "name": name, "host": host,
        "url": url, "view_url": view_url, "created_at": created_at,
        "synced_at": now_iso(),
    })


def upsert_asana_subtask(gid: str, parent_task_gid: str, name: str,
                         assignee_name: str, assignee_email: str, completed: int,
                         completed_at: str, created_at: str, due_on: str,
                         permalink: str) -> None:
    _upsert("asana_subtasks", {
        "gid": gid, "parent_task_gid": parent_task_gid, "name": name,
        "assignee_name": assignee_name, "assignee_email": assignee_email,
        "completed": completed, "completed_at": completed_at,
        "created_at": created_at, "due_on": due_on, "permalink": permalink,
        "synced_at": now_iso(),
    })


def record_asana_run(mode: str, status: str, started_at: str, finished_at: str,
                     counts: dict, error: str = "") -> int:
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO asana_sync_runs (mode, status, started_at, finished_at, counts, error) "
        "VALUES (?,?,?,?,?,?)",
        (mode, status, started_at, finished_at, json.dumps(counts), error),
    )
    conn.commit()
    return cur.lastrowid


def last_asana_run() -> dict | None:
    row = _conn().execute(
        "SELECT * FROM asana_sync_runs ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return _decode_row(row) if row else None


def list_asana_runs(limit: int = 10) -> list[dict]:
    rows = _conn().execute(
        "SELECT * FROM asana_sync_runs ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    return [_decode_row(r) for r in rows]


def list_asana_projects(include_archived: bool = False) -> list[dict]:
    q = "SELECT * FROM asana_projects"
    if not include_archived:
        q += " WHERE archived=0"
    q += " ORDER BY name COLLATE NOCASE"
    return [_decode_row(r) for r in _conn().execute(q).fetchall()]


def get_asana_task(gid: str) -> dict | None:
    row = _conn().execute("SELECT * FROM asana_tasks WHERE gid=?", (gid,)).fetchone()
    return _decode_row(row) if row else None


def list_asana_tasks(project_gid: str | None = None, assignee_gid: str | None = None,
                     status: str | None = None, section: str | None = None,
                     q: str | None = None, limit: int = 500) -> list[dict]:
    """Query the synced task store. status: 'open' | 'completed' | None."""
    where, vals = [], []
    if project_gid:
        where.append("project_gid=?")
        vals.append(project_gid)
    if assignee_gid:
        where.append("assignee_gid=?")
        vals.append(assignee_gid)
    if status == "open":
        where.append("completed=0")
    elif status == "completed":
        where.append("completed=1")
    if section:
        where.append("section=?")
        vals.append(section)
    if q:
        where.append("(name LIKE ? OR notes LIKE ?)")
        vals.extend([f"%{q}%", f"%{q}%"])
    sql = "SELECT * FROM asana_tasks"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY completed, due_on IS NULL, due_on ASC, name COLLATE NOCASE LIMIT ?"
    vals.append(limit)
    return [_decode_row(r) for r in _conn().execute(sql, vals).fetchall()]


def list_asana_stories(task_gid: str, limit: int = 100) -> list[dict]:
    rows = _conn().execute(
        "SELECT * FROM asana_stories WHERE task_gid=? ORDER BY created_at ASC LIMIT ?",
        (task_gid, limit),
    ).fetchall()
    return [_decode_row(r) for r in rows]


def list_asana_attachments(task_gid: str, limit: int = 50) -> list[dict]:
    rows = _conn().execute(
        "SELECT * FROM asana_attachments WHERE task_gid=? ORDER BY created_at DESC LIMIT ?",
        (task_gid, limit),
    ).fetchall()
    return [_decode_row(r) for r in rows]


def list_asana_subtasks(parent_task_gid: str, limit: int = 100) -> list[dict]:
    rows = _conn().execute(
        "SELECT * FROM asana_subtasks WHERE parent_task_gid=? ORDER BY created_at ASC LIMIT ?",
        (parent_task_gid, limit),
    ).fetchall()
    return [_decode_row(r) for r in rows]


def list_asana_users() -> list[dict]:
    rows = _conn().execute(
        "SELECT * FROM asana_users ORDER BY name COLLATE NOCASE"
    ).fetchall()
    return [_decode_row(r) for r in rows]


def list_asana_teams() -> list[dict]:
    rows = _conn().execute(
        "SELECT * FROM asana_teams ORDER BY name COLLATE NOCASE"
    ).fetchall()
    return [_decode_row(r) for r in rows]


def asana_counts() -> dict:
    conn = _conn()

    def n(table: str) -> int:
        try:
            return conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
        except Exception:
            return 0

    open_tasks = conn.execute("SELECT COUNT(*) AS n FROM asana_tasks WHERE completed=0").fetchone()["n"]
    overdue = conn.execute(
        "SELECT COUNT(*) AS n FROM asana_tasks WHERE completed=0 AND due_on != '' "
        "AND due_on < date('now')"
    ).fetchone()["n"]
    return {
        "tasks": n("asana_tasks"),
        "open": open_tasks,
        "overdue": overdue,
        "projects": n("asana_projects"),
        "stories": n("asana_stories"),
        "attachments": n("asana_attachments"),
        "subtasks": n("asana_subtasks"),
        "users": n("asana_users"),
        "teams": n("asana_teams"),
        "custom_fields": n("asana_custom_fields"),
    }


def replace_asana_task_memberships(task_gid: str, memberships: list[dict]) -> None:
    """Replace membership facts for one task; KPI pivots use these instead of a lossy primary project."""
    conn = _conn()
    conn.execute("DELETE FROM asana_task_memberships WHERE task_gid=?", (task_gid,))
    for m in memberships:
        project = m.get("project") or {}
        section = m.get("section") or {}
        gid = str(project.get("gid") or "")
        if not gid:
            continue
        conn.execute(
            "INSERT INTO asana_task_memberships VALUES (?,?,?,?,?,?,?,?)",
            (task_gid, gid, project.get("name") or "", section.get("gid") or "", section.get("name") or "", m.get("team_gid") or "", m.get("team_name") or "", now_iso()),
        )
    conn.commit()


def replace_asana_task_custom_fields(task_gid: str, values: list[dict]) -> None:
    conn = _conn()
    conn.execute("DELETE FROM asana_task_custom_field_values WHERE task_gid=?", (task_gid,))
    for value in values:
        gid = str(value.get("gid") or "")
        if not gid:
            continue
        raw = value.get("raw") or {}
        number = raw.get("number_value")
        try:
            number = float(number) if number is not None else None
        except (TypeError, ValueError):
            number = None
        date_value = (raw.get("date_value") or {}).get("date") or ""
        conn.execute(
            "INSERT INTO asana_task_custom_field_values VALUES (?,?,?,?,?,?,?,?)",
            (task_gid, gid, value.get("name") or "", value.get("type") or "", value.get("value") or "", number, date_value, now_iso()),
        )
    conn.commit()


def asana_kpi_definition_rows() -> list[dict]:
    return [_decode_row(r) for r in _conn().execute("SELECT * FROM asana_kpi_definitions ORDER BY team, label").fetchall()]


def asana_kpi_fact_rows(team: str | None = None, grain: str | None = None) -> list[dict]:
    sql, params = "SELECT * FROM asana_kpi_facts WHERE 1=1", []
    if team:
        sql += " AND team=?"; params.append(team)
    if grain:
        sql += " AND period_grain=?"; params.append(grain)
    sql += " ORDER BY period_start DESC, team, kpi_id"
    return [_decode_row(r) for r in _conn().execute(sql, params).fetchall()]


def asana_summary() -> dict:
    """Rich KPI rollups matching Luminize kpiReport.gs & Presets.gs definitions:
    Completions, SLA Adherence Rate, Cycle Time Velocity, Weighted Velocity, Overdue, Custom Fields."""
    conn = _conn()
    out = {
        "metrics": {
            "total_tasks": 0,
            "completed_tasks": 0,
            "open_tasks": 0,
            "overdue_tasks": 0,
            "completion_rate_pct": 0.0,
            "sla_adherence_pct": 0.0,
            "avg_cycle_time_days": 0.0,
            "weighted_velocity": 0.0,
            "sla_missed_count": 0,
        },
        "by_assignee": [],
        "by_project": [],
        "by_month": [],
        "by_priority": [],
        "by_status": {"open": 0, "completed": 0},
    }
    try:
        rows = conn.execute("SELECT * FROM asana_tasks").fetchall()
        if not rows:
            return out

        now_dt = datetime.now(timezone.utc)
        total = len(rows)
        completed = 0
        open_t = 0
        overdue = 0
        sla_on_time = 0
        sla_eligible = 0
        cycle_times = []
        weighted_vel = 0.0
        sla_missed = 0

        assignee_map = {}
        project_map = {}
        month_map = {}
        priority_map = {}

        for r in rows:
            t = _decode_row(dict(r))
            is_done = bool(t.get("completed"))
            if is_done:
                completed += 1
            else:
                open_t += 1

            # Weight rule: Keepa tasks 0.3, others 1.0
            name = str(t.get("name") or "")
            weight = 0.3 if re.search(r"keepa", name, re.I) else 1.0
            if is_done:
                weighted_vel += weight

            due_str = str(t.get("due_on") or "").strip()
            due_dt = None
            if due_str:
                try:
                    due_dt = datetime.fromisoformat(due_str.replace("Z", "+00:00"))
                    if not due_dt.tzinfo:
                        due_dt = due_dt.replace(tzinfo=timezone.utc)
                except Exception:
                    pass

            if not is_done and due_dt and due_dt < now_dt:
                overdue += 1

            created_str = str(t.get("created_at") or "").strip()
            completed_str = str(t.get("completed_at") or "").strip()

            if is_done and completed_str:
                try:
                    comp_dt = datetime.fromisoformat(completed_str.replace("Z", "+00:00"))
                    if not comp_dt.tzinfo:
                        comp_dt = comp_dt.replace(tzinfo=timezone.utc)

                    if due_dt:
                        sla_eligible += 1
                        if comp_dt <= due_dt:
                            sla_on_time += 1

                    if created_str:
                        creat_dt = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
                        if not creat_dt.tzinfo:
                            creat_dt = creat_dt.replace(tzinfo=timezone.utc)
                        days = (comp_dt - creat_dt).total_seconds() / 86400.0
                        if days >= 0:
                            cycle_times.append(days)

                    m_key = comp_dt.strftime("%Y-%m")
                    month_map[m_key] = month_map.get(m_key, 0) + 1
                except Exception:
                    pass

            assignee = str(t.get("assignee_name") or "Unassigned").strip()
            if assignee:
                if assignee not in assignee_map:
                    assignee_map[assignee] = {"total": 0, "completed": 0, "open": 0}
                assignee_map[assignee]["total"] += 1
                if is_done:
                    assignee_map[assignee]["completed"] += 1
                else:
                    assignee_map[assignee]["open"] += 1

            proj = str(t.get("project_name") or "No Project").strip()
            if proj:
                project_map[proj] = project_map.get(proj, 0) + 1

            cfs = t.get("custom_fields") or []
            if isinstance(cfs, list):
                for cf in cfs:
                    if not isinstance(cf, dict):
                        continue
                    cf_name = str(cf.get("name") or "").strip().lower()
                    cf_val = str(cf.get("display_value") or (cf.get("enum_value") or {}).get("name") or cf.get("text_value") or "").strip()
                    if not cf_val:
                        continue
                    if cf_name == "priority":
                        priority_map[cf_val] = priority_map.get(cf_val, 0) + 1
                    if "sla" in cf_name and ("missed" in cf_name or "status" in cf_name):
                        if cf_val.lower() in ("yes", "missed", "failed", "true"):
                            sla_missed += 1

        out["metrics"]["total_tasks"] = total
        out["metrics"]["completed_tasks"] = completed
        out["metrics"]["open_tasks"] = open_t
        out["metrics"]["overdue_tasks"] = overdue
        out["metrics"]["completion_rate_pct"] = round((completed / total) * 100.0, 1) if total else 0.0
        out["metrics"]["sla_adherence_pct"] = round((sla_on_time / sla_eligible) * 100.0, 1) if sla_eligible else 100.0
        out["metrics"]["avg_cycle_time_days"] = round(sum(cycle_times) / len(cycle_times), 1) if cycle_times else 0.0
        out["metrics"]["weighted_velocity"] = round(weighted_vel, 1)
        out["metrics"]["sla_missed_count"] = sla_missed

        out["by_status"]["open"] = open_t
        out["by_status"]["completed"] = completed

        out["by_assignee"] = [
            {"assignee": k, "total": v["total"], "completed": v["completed"], "open": v["open"],
             "completion_rate_pct": round((v["completed"] / v["total"]) * 100.0, 1) if v["total"] else 0.0}
            for k, v in sorted(assignee_map.items(), key=lambda x: x[1]["total"], reverse=True)[:20]
        ]
        out["by_project"] = [
            {"project": k, "count": v}
            for k, v in sorted(project_map.items(), key=lambda x: x[1], reverse=True)[:20]
        ]
        out["by_month"] = [
            {"month": k, "completed_count": v}
            for k, v in sorted(month_map.items(), reverse=True)[:12]
        ]
        out["by_priority"] = [
            {"priority": k, "count": v}
            for k, v in sorted(priority_map.items(), key=lambda x: x[1], reverse=True)
        ]
    except Exception:
        pass
    return out

