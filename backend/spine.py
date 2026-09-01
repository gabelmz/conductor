"""Conductor local-first application spine.

The spine is the local source of truth for configuration metadata that should
remain coherent across views: providers/models, presets, node library, feature
registry, file types, statuses, lifecycles, datasets, and global filters.

`conductor.*` in Supabase mirrors this shape when cloud sync is configured;
secrets never enter the spine and stay in the local keychain/config store.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

import storage

router = APIRouter(prefix="/api/spine", tags=["spine"])

STATUS_DEFINITIONS = [
    ("draft", "Draft", "Created but not ready for normal use.", "lifecycle", "muted", 10),
    ("active", "Active", "Available for normal use.", "lifecycle", "success", 20),
    ("disabled", "Disabled", "Retained but unavailable for use.", "lifecycle", "warning", 30),
    ("deprecated", "Deprecated", "Supported temporarily; replace it.", "lifecycle", "warning", 40),
    ("archived", "Archived", "Historical record only.", "lifecycle", "muted", 50),
    ("queued", "Queued", "Awaiting execution.", "job", "muted", 60),
    ("running", "Running", "Currently executing.", "job", "info", 70),
    ("ready", "Ready", "Prepared for the next lifecycle action.", "job", "success", 80),
    ("done", "Done", "Completed successfully.", "job", "success", 90),
    ("error", "Error", "Failed and requires review.", "job", "danger", 100),
]

LIFECYCLES = [
    ("draft", "Draft", "Definition is being designed.", 10, False, ["active", "archived"]),
    ("active", "Active", "Live and available.", 20, False, ["disabled", "deprecated", "archived"]),
    ("stable", "Stable", "Versioned, production-safe definition.", 30, False, ["deprecated", "archived"]),
    ("deprecated", "Deprecated", "No new usage; migration path required.", 40, False, ["archived"]),
    ("archived", "Archived", "Retained as a historical record.", 50, True, []),
]

FILE_TYPES = [
    (".csv", "CSV", "delimited", "parse_catalog"), (".tsv", "TSV", "delimited", "parse_catalog"),
    (".tab", "Tab-delimited", "delimited", "parse_catalog"), (".txt", "Text table", "delimited", "parse_catalog"),
    (".xlsx", "Excel Workbook", "spreadsheet", "parse_catalog"), (".xlsm", "Excel Macro Workbook", "spreadsheet", "parse_catalog"),
    (".xlsb", "Excel Binary Workbook", "spreadsheet", "parse_catalog"),
    (".json", "JSON", "structured", "parse_catalog"), (".ndjson", "NDJSON", "structured", "parse_catalog"),
    (".jsonl", "JSON Lines", "structured", "parse_catalog"), (".md", "Markdown", "document", "parse_catalog"),
    (".docx", "Word", "document", "parse_catalog"), (".pdf", "PDF", "document", "parse_catalog"),
]

NODE_LIBRARY = {
    "trigger": ("Trigger", "Starts a Flow Canvas run from a manual, schedule, webhook, or event source.", "control", "codicon-run"),
    "json": ("JSON", "Transforms structured JSON data.", "data", "codicon-json"),
    "text": ("Text", "Creates or transforms text values.", "data", "codicon-symbol-string"),
    "http": ("HTTP", "Calls an external HTTP API.", "integration", "codicon-globe"),
    "ai": ("AI", "Runs a configured chat, extraction, or embedding model.", "ai", "codicon-sparkle"),
    "script": ("Script", "Executes an approved local script.", "automation", "codicon-terminal"),
    "sheet": ("Sheet", "Reads or writes an approved spreadsheet source.", "integration", "codicon-table"),
    "drive": ("Drive", "Reads or writes an approved file source.", "integration", "codicon-folder-opened"),
    "flush": ("Flush", "Persists the pipeline output.", "control", "codicon-save"),
    "custom": ("Custom", "Extensible user-defined node.", "custom", "codicon-puzzle"),
}

DATASETS = [
    ("catalog_products", "Catalog Products", "Canonical product catalog and normalized attributes.", "product", "sqlite", 0),
    ("keepa_products", "Keepa Products", "Cached market intelligence and product detail from Keepa.", "listing", "keepa", 172800),
    ("asana_tasks", "Asana Tasks", "Mirrored work items and their project/team context.", "task", "asana", 3600),
    ("suggested_content", "Suggested Listing Content", "Uploaded or connected proposed listing attributes.", "listing_content", "upload", 86400),
    ("live_listing_content", "Live Listing Content", "Latest retrieved listing attributes used for comparison.", "listing_content", "sp_api", 172800),
    ("listing_comparisons", "Listing Comparisons", "Field-level suggested-vs-live comparison records and recommendations.", "listing_comparison", "computed", 0),
]

FILTERS = [
    ("marketplace", "Marketplace", "listing", "marketplace", "select", {"dataset": "catalog_products", "field": "market"}, 10),
    ("brand", "Brand", "listing", "attributes.brand", "select", {"dataset": "catalog_products", "field": "attributes.brand"}, 20),
    ("team", "Team", "task", "team_name", "select", {"dataset": "asana_tasks", "field": "team_name"}, 30),
    ("project", "Project", "task", "project_name", "select", {"dataset": "asana_tasks", "field": "project_name"}, 40),
    ("freshness", "Freshness", "listing", "updated_at", "age", {"options": ["fresh", "stale", "missing"]}, 50),
]


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _decode(row: Any, json_columns: tuple[str, ...]) -> dict:
    item = dict(row)
    for key in json_columns:
        try:
            item[key] = json.loads(item.get(key) or ("[]" if key.endswith(("s", "ies")) else "{}"))
        except (TypeError, json.JSONDecodeError):
            item[key] = [] if key.endswith(("s", "ies")) else {}
    return item


def init_spine_db() -> None:
    conn = storage._conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS spine_registry (
          kind TEXT NOT NULL, registry_key TEXT NOT NULL, label TEXT NOT NULL,
          description TEXT NOT NULL DEFAULT '', route TEXT NOT NULL DEFAULT '', icon TEXT NOT NULL DEFAULT '',
          status_key TEXT NOT NULL DEFAULT 'active', lifecycle_key TEXT NOT NULL DEFAULT 'stable',
          capabilities TEXT NOT NULL DEFAULT '[]', metadata TEXT NOT NULL DEFAULT '{}', source_hash TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY(kind, registry_key)
        );
        CREATE TABLE IF NOT EXISTS spine_status_definitions (
          status_key TEXT PRIMARY KEY, label TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', category TEXT NOT NULL,
          color_token TEXT NOT NULL DEFAULT '', sort_order INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1,
          metadata TEXT NOT NULL DEFAULT '{}', updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS spine_lifecycle_definitions (
          lifecycle_key TEXT PRIMARY KEY, label TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', sort_order INTEGER NOT NULL DEFAULT 0,
          terminal INTEGER NOT NULL DEFAULT 0, transitions TEXT NOT NULL DEFAULT '[]', metadata TEXT NOT NULL DEFAULT '{}', updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS spine_file_type_definitions (
          extension TEXT PRIMARY KEY, label TEXT NOT NULL, category TEXT NOT NULL, parse_handler TEXT NOT NULL DEFAULT '',
          mime_types TEXT NOT NULL DEFAULT '[]', max_bytes INTEGER, enabled INTEGER NOT NULL DEFAULT 1,
          metadata TEXT NOT NULL DEFAULT '{}', updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS spine_model_catalog (
          provider_id TEXT NOT NULL, model_id TEXT NOT NULL, label TEXT NOT NULL DEFAULT '', capabilities TEXT NOT NULL DEFAULT '[]',
          context_window INTEGER, input_modalities TEXT NOT NULL DEFAULT '["text"]', output_modalities TEXT NOT NULL DEFAULT '["text"]',
          is_embedding INTEGER NOT NULL DEFAULT 0, is_active INTEGER NOT NULL DEFAULT 1, metadata TEXT NOT NULL DEFAULT '{}', updated_at TEXT NOT NULL,
          PRIMARY KEY(provider_id, model_id)
        );
        CREATE TABLE IF NOT EXISTS spine_model_presets (
          preset_key TEXT PRIMARY KEY, label TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', provider_id TEXT NOT NULL, model_id TEXT NOT NULL,
          system_prompt_key TEXT NOT NULL DEFAULT 'default', parameters TEXT NOT NULL DEFAULT '{}', enabled INTEGER NOT NULL DEFAULT 1,
          metadata TEXT NOT NULL DEFAULT '{}', updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS spine_configurations (
          config_scope TEXT NOT NULL, config_key TEXT NOT NULL, value TEXT NOT NULL DEFAULT '{}', version INTEGER NOT NULL DEFAULT 1,
          secret_refs TEXT NOT NULL DEFAULT '[]', updated_at TEXT NOT NULL, PRIMARY KEY(config_scope, config_key)
        );
        CREATE TABLE IF NOT EXISTS spine_node_library (
          node_type TEXT PRIMARY KEY, label TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', category TEXT NOT NULL, icon TEXT NOT NULL DEFAULT '',
          input_schema TEXT NOT NULL DEFAULT '{}', output_schema TEXT NOT NULL DEFAULT '{}', config_schema TEXT NOT NULL DEFAULT '{}',
          execution_mode TEXT NOT NULL DEFAULT 'local', lifecycle_key TEXT NOT NULL DEFAULT 'stable', enabled INTEGER NOT NULL DEFAULT 1,
          metadata TEXT NOT NULL DEFAULT '{}', updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS spine_node_presets (
          preset_key TEXT PRIMARY KEY, node_type TEXT NOT NULL, label TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', config TEXT NOT NULL DEFAULT '{}',
          enabled INTEGER NOT NULL DEFAULT 1, metadata TEXT NOT NULL DEFAULT '{}', updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS spine_datasets (
          dataset_key TEXT PRIMARY KEY, label TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', entity_type TEXT NOT NULL, source_type TEXT NOT NULL,
          lifecycle_key TEXT NOT NULL DEFAULT 'active', freshness_seconds INTEGER, schema_definition TEXT NOT NULL DEFAULT '{}',
          source_config TEXT NOT NULL DEFAULT '{}', metadata TEXT NOT NULL DEFAULT '{}', updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS spine_global_filter_definitions (
          filter_key TEXT PRIMARY KEY, label TEXT NOT NULL, entity_type TEXT NOT NULL, field_path TEXT NOT NULL, control_type TEXT NOT NULL,
          options_source TEXT NOT NULL DEFAULT '{}', default_value TEXT, enabled INTEGER NOT NULL DEFAULT 1, sort_order INTEGER NOT NULL DEFAULT 0,
          metadata TEXT NOT NULL DEFAULT '{}', updated_at TEXT NOT NULL
        );
    """)
    conn.commit()
    seed_defaults()


def seed_defaults() -> None:
    conn = storage._conn()
    now = storage.now_iso()
    for key, label, desc, cat, color, order in STATUS_DEFINITIONS:
        conn.execute("INSERT INTO spine_status_definitions VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(status_key) DO UPDATE SET label=excluded.label,description=excluded.description,category=excluded.category,color_token=excluded.color_token,sort_order=excluded.sort_order,updated_at=excluded.updated_at", (key, label, desc, cat, color, order, 1, "{}", now))
    for key, label, desc, order, terminal, transitions in LIFECYCLES:
        conn.execute("INSERT INTO spine_lifecycle_definitions VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(lifecycle_key) DO UPDATE SET label=excluded.label,description=excluded.description,sort_order=excluded.sort_order,terminal=excluded.terminal,transitions=excluded.transitions,updated_at=excluded.updated_at", (key, label, desc, order, int(terminal), _json(transitions), "{}", now))
    for ext, label, category, parser in FILE_TYPES:
        conn.execute("INSERT INTO spine_file_type_definitions VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(extension) DO UPDATE SET label=excluded.label,category=excluded.category,parse_handler=excluded.parse_handler,updated_at=excluded.updated_at", (ext, label, category, parser, "[]", 52_428_800, 1, "{}", now))
    for node_type, (label, desc, category, icon) in NODE_LIBRARY.items():
        conn.execute("INSERT INTO spine_node_library VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(node_type) DO UPDATE SET label=excluded.label,description=excluded.description,category=excluded.category,icon=excluded.icon,updated_at=excluded.updated_at", (node_type, label, desc, category, icon, "{}", "{}", "{}", "local", "stable", 1, "{}", now))
    for key, label, desc, entity, source, freshness in DATASETS:
        conn.execute("INSERT INTO spine_datasets VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(dataset_key) DO UPDATE SET label=excluded.label,description=excluded.description,entity_type=excluded.entity_type,source_type=excluded.source_type,freshness_seconds=excluded.freshness_seconds,updated_at=excluded.updated_at", (key, label, desc, entity, source, "active", freshness, "{}", "{}", "{}", now))
    for key, label, entity, path, control, source, order in FILTERS:
        conn.execute("INSERT INTO spine_global_filter_definitions VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(filter_key) DO UPDATE SET label=excluded.label,entity_type=excluded.entity_type,field_path=excluded.field_path,control_type=excluded.control_type,options_source=excluded.options_source,sort_order=excluded.sort_order,updated_at=excluded.updated_at", (key, label, entity, path, control, _json(source), None, 1, order, "{}", now))
    _seed_models(conn, now)
    _seed_registry(conn, now)
    conn.commit()


def _seed_models(conn, now: str) -> None:
    import providers
    for pid, meta in providers.HOSTED_PROVIDERS.items():
        model_id = meta["default_model"]
        capabilities = ["chat", "completions"]
        if meta.get("default_embedding_model"):
            capabilities.append("embeddings")
        conn.execute("INSERT INTO spine_model_catalog VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(provider_id,model_id) DO UPDATE SET label=excluded.label,capabilities=excluded.capabilities,is_active=excluded.is_active,updated_at=excluded.updated_at", (pid, model_id, f"{meta['label']} — {model_id}", _json(capabilities), None, _json(["text"]), _json(["text"]), 0, 1, _json({"base_url": meta["base_url"]}), now))
        if meta.get("default_embedding_model"):
            emb = meta["default_embedding_model"]
            conn.execute("INSERT INTO spine_model_catalog VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(provider_id,model_id) DO UPDATE SET label=excluded.label,capabilities=excluded.capabilities,is_embedding=excluded.is_embedding,updated_at=excluded.updated_at", (pid, emb, f"{meta['label']} — {emb}", _json(["embeddings"]), None, _json(["text"]), _json(["vector"]), 1, 1, "{}", now))
        conn.execute("INSERT INTO spine_model_presets VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(preset_key) DO UPDATE SET label=excluded.label,description=excluded.description,provider_id=excluded.provider_id,model_id=excluded.model_id,updated_at=excluded.updated_at", (f"{pid}-default", f"{meta['label']} Default", "Provider's default Conductor chat target.", pid, model_id, "default", _json({"temperature": 0.6, "max_tokens": 1200}), 1, "{}", now))


def _seed_registry(conn, now: str) -> None:
    """Seed the feature glossary from the actual frontend nav registry.

    Reading the canonical data-driven sidebar keeps the backend registry aligned
    with the live app without maintaining a duplicate Python list.
    """
    nav_path = Path(__file__).resolve().parent.parent / "frontend" / "sidebar.js"
    try:
        source = nav_path.read_text(encoding="utf-8")
    except OSError:
        return
    pattern = re.compile(
        r"^\s*(?P<id>[a-zA-Z0-9_]+):\s*\{\s*label:\s*'(?P<label>[^']+)',\s*"
        r"icon:\s*'(?P<icon>[^']+)',\s*view:\s*'(?P<view>[^']+)'(?:,\s*count:\s*'(?P<count>[^']+)')?",
        re.MULTILINE,
    )
    for m in pattern.finditer(source):
        item = m.groupdict()
        payload = {"view": item["view"], "count": item.get("count")}
        digest = hashlib.sha256(_json(payload).encode()).hexdigest()
        conn.execute(
            "INSERT INTO spine_registry VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(kind,registry_key) DO UPDATE SET label=excluded.label,route=excluded.route,icon=excluded.icon,metadata=excluded.metadata,source_hash=excluded.source_hash,updated_at=excluded.updated_at",
            ("feature", item["id"], item["label"], "Conductor application feature.", item["view"], item["icon"], "active", "stable", "[]", _json(payload), digest, now, now),
        )


@router.get("/snapshot")
def snapshot() -> dict:
    """Single local-first payload for glossary, model picker and global filters."""
    conn = storage._conn()
    return {
        "registry": [_decode(r, ("capabilities", "metadata")) for r in conn.execute("SELECT * FROM spine_registry ORDER BY kind,label")],
        "statuses": [_decode(r, ("metadata",)) for r in conn.execute("SELECT * FROM spine_status_definitions ORDER BY sort_order")],
        "lifecycles": [_decode(r, ("transitions", "metadata")) for r in conn.execute("SELECT * FROM spine_lifecycle_definitions ORDER BY sort_order")],
        "file_types": [_decode(r, ("mime_types", "metadata")) for r in conn.execute("SELECT * FROM spine_file_type_definitions ORDER BY category,label")],
        "models": [_decode(r, ("capabilities", "input_modalities", "output_modalities", "metadata")) for r in conn.execute("SELECT * FROM spine_model_catalog WHERE is_active=1 ORDER BY provider_id,model_id")],
        "model_presets": [_decode(r, ("parameters", "metadata")) for r in conn.execute("SELECT * FROM spine_model_presets WHERE enabled=1 ORDER BY label")],
        "nodes": [_decode(r, ("input_schema", "output_schema", "config_schema", "metadata")) for r in conn.execute("SELECT * FROM spine_node_library WHERE enabled=1 ORDER BY category,label")],
        "datasets": [_decode(r, ("schema_definition", "source_config", "metadata")) for r in conn.execute("SELECT * FROM spine_datasets ORDER BY label")],
        "filters": [_decode(r, ("options_source", "default_value", "metadata")) for r in conn.execute("SELECT * FROM spine_global_filter_definitions WHERE enabled=1 ORDER BY sort_order")],
    }


@router.get("/glossary")
def glossary(q: str = "", kind: str = "") -> dict:
    query = q.strip().lower()
    items = snapshot()["registry"]
    if kind:
        items = [x for x in items if x["kind"] == kind]
    if query:
        items = [x for x in items if query in (x["label"] + " " + x["description"] + " " + x["registry_key"]).lower()]
    return {"count": len(items), "items": items}


@router.get("/models")
def models() -> dict:
    data = snapshot()
    return {"models": data["models"], "presets": data["model_presets"]}


@router.get("/nodes")
def nodes() -> dict:
    return {"nodes": snapshot()["nodes"]}


@router.get("/filters")
def filters() -> dict:
    return {"filters": snapshot()["filters"]}


@router.put("/config/{scope}/{key}")
def put_configuration(scope: str, key: str, body: dict) -> dict:
    if "value" not in body:
        raise HTTPException(400, "value is required")
    # The payload deliberately supports only non-secret configuration.
    value = body["value"]
    secret_refs = body.get("secret_refs") or []
    now = storage.now_iso()
    conn = storage._conn()
    conn.execute("INSERT INTO spine_configurations VALUES (?,?,?,?,?,?) ON CONFLICT(config_scope,config_key) DO UPDATE SET value=excluded.value,version=spine_configurations.version+1,secret_refs=excluded.secret_refs,updated_at=excluded.updated_at", (scope, key, _json(value), 1, _json(secret_refs), now))
    conn.commit()
    return {"ok": True, "scope": scope, "key": key}


@router.get("/config/{scope}/{key}")
def get_configuration(scope: str, key: str) -> dict:
    r = storage._conn().execute("SELECT * FROM spine_configurations WHERE config_scope=? AND config_key=?", (scope, key)).fetchone()
    if not r:
        raise HTTPException(404, "configuration not found")
    return _decode(r, ("value", "secret_refs"))
