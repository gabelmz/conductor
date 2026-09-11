"""Spine SQLite schema — table DDL only. No seed data, no seeding logic."""
from __future__ import annotations

import storage


def init_tables() -> None:
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
