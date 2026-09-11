-- Actually creates the `conductor` schema that docs/CONDUCTOR-SPINE.md has
-- documented since before this migration existed. Prior audit
-- (docs/sync-architecture.md, section 1) confirmed no CREATE SCHEMA/CREATE
-- TABLE for `conductor.*` exists anywhere in this repo's migrations — only
-- public.conductor_records/sync_runs/sync_leases/sync_checkpoints/sync_outbox
-- are real. This migration is additive only; nothing in `public.*` is touched.
--
-- Table shapes mirror backend/spine/schema.py's spine_* SQLite tables
-- one-for-one (re-verified column-by-column against the live file before
-- writing this migration, per this task's own instructions not to trust the
-- plan's draft blindly), plus a new conductor.preferred_state table for the
-- spine's preferred-state layer (backend/spine/preferred.py). Secrets never
-- enter this schema — spine_configurations.secret_refs only ever names a
-- local secret reference, never a raw value, and that constraint is
-- preserved here unchanged.

create schema if not exists conductor;

create table if not exists conductor.registry (
  kind text not null, registry_key text not null, label text not null,
  description text not null default '', route text not null default '', icon text not null default '',
  status_key text not null default 'active', lifecycle_key text not null default 'stable',
  capabilities jsonb not null default '[]'::jsonb, metadata jsonb not null default '{}'::jsonb,
  source_hash text not null default '', created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(), primary key (kind, registry_key)
);

create table if not exists conductor.status_definitions (
  status_key text primary key, label text not null, description text not null default '',
  category text not null, color_token text not null default '', sort_order integer not null default 0,
  active boolean not null default true, metadata jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

create table if not exists conductor.lifecycle_definitions (
  lifecycle_key text primary key, label text not null, description text not null default '',
  sort_order integer not null default 0, terminal boolean not null default false,
  transitions jsonb not null default '[]'::jsonb, metadata jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

create table if not exists conductor.file_type_definitions (
  extension text primary key, label text not null, category text not null,
  parse_handler text not null default '', mime_types jsonb not null default '[]'::jsonb,
  max_bytes bigint, enabled boolean not null default true, metadata jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

create table if not exists conductor.model_catalog (
  provider_id text not null, model_id text not null, label text not null default '',
  capabilities jsonb not null default '[]'::jsonb, context_window integer,
  input_modalities jsonb not null default '["text"]'::jsonb, output_modalities jsonb not null default '["text"]'::jsonb,
  is_embedding boolean not null default false, is_active boolean not null default true,
  metadata jsonb not null default '{}'::jsonb, updated_at timestamptz not null default now(),
  primary key (provider_id, model_id)
);

create table if not exists conductor.model_presets (
  preset_key text primary key, label text not null, description text not null default '',
  provider_id text not null, model_id text not null, system_prompt_key text not null default 'default',
  parameters jsonb not null default '{}'::jsonb, enabled boolean not null default true,
  metadata jsonb not null default '{}'::jsonb, updated_at timestamptz not null default now()
);

-- Non-secret configuration only — secret_refs names a local reference, never a value.
create table if not exists conductor.configurations (
  config_scope text not null, config_key text not null, value jsonb not null default '{}'::jsonb,
  version integer not null default 1, secret_refs jsonb not null default '[]'::jsonb,
  updated_at timestamptz not null default now(), primary key (config_scope, config_key)
);

create table if not exists conductor.node_library (
  node_type text primary key, label text not null, description text not null default '',
  category text not null, icon text not null default '', input_schema jsonb not null default '{}'::jsonb,
  output_schema jsonb not null default '{}'::jsonb, config_schema jsonb not null default '{}'::jsonb,
  execution_mode text not null default 'local', lifecycle_key text not null default 'stable',
  enabled boolean not null default true, metadata jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

create table if not exists conductor.node_presets (
  preset_key text primary key, node_type text not null, label text not null,
  description text not null default '', config jsonb not null default '{}'::jsonb,
  enabled boolean not null default true, metadata jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

create table if not exists conductor.datasets (
  dataset_key text primary key, label text not null, description text not null default '',
  entity_type text not null, source_type text not null, lifecycle_key text not null default 'active',
  freshness_seconds integer, schema_definition jsonb not null default '{}'::jsonb,
  source_config jsonb not null default '{}'::jsonb, metadata jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

create table if not exists conductor.global_filter_definitions (
  filter_key text primary key, label text not null, entity_type text not null, field_path text not null,
  control_type text not null, options_source jsonb not null default '{}'::jsonb, default_value text,
  enabled boolean not null default true, sort_order integer not null default 0,
  metadata jsonb not null default '{}'::jsonb, updated_at timestamptz not null default now()
);

-- New in this migration: mirrors backend/spine/preferred.py's spine_configurations
-- (scope='chat', key='preferred') row as a typed row for easier hosted-side reads.
create table if not exists conductor.preferred_state (
  scope text primary key, provider text, model text, fallback_provider text, fallback_model text,
  updated_at timestamptz not null default now()
);

alter table conductor.registry enable row level security;
alter table conductor.status_definitions enable row level security;
alter table conductor.lifecycle_definitions enable row level security;
alter table conductor.file_type_definitions enable row level security;
alter table conductor.model_catalog enable row level security;
alter table conductor.model_presets enable row level security;
alter table conductor.configurations enable row level security;
alter table conductor.node_library enable row level security;
alter table conductor.node_presets enable row level security;
alter table conductor.datasets enable row level security;
alter table conductor.global_filter_definitions enable row level security;
alter table conductor.preferred_state enable row level security;
-- Conductor uses a service-role key server-side; no public policies are
-- created (matches supabase/conductor-schema.sql's existing convention).

-- PostgREST only exposes schemas listed in the API's exposed-schemas setting;
-- `conductor` must be added there (Dashboard -> Settings -> API -> Exposed
-- schemas, or via the Management API) before any REST call against it will
-- work. This migration cannot do that from SQL — flagged here so it is not
-- silently missed the way the original conductor.* claim in
-- docs/CONDUCTOR-SPINE.md was. Once exposed, PostgREST is addressed with the
-- SAME /rest/v1/<table> URL used for public tables — the schema is selected
-- via the Accept-Profile (GET/HEAD) / Content-Profile (POST/PATCH/DELETE)
-- request header, never a path segment (see backend/spine_sync.py and
-- backend/supabase_sync.py's `_request` for the header-selection code this
-- mirrors).

-- =====================================================================================
-- ROLLBACK
-- =====================================================================================
-- drop table if exists conductor.preferred_state;
-- drop table if exists conductor.global_filter_definitions;
-- drop table if exists conductor.datasets;
-- drop table if exists conductor.node_presets;
-- drop table if exists conductor.node_library;
-- drop table if exists conductor.configurations;
-- drop table if exists conductor.model_presets;
-- drop table if exists conductor.model_catalog;
-- drop table if exists conductor.file_type_definitions;
-- drop table if exists conductor.lifecycle_definitions;
-- drop table if exists conductor.status_definitions;
-- drop table if exists conductor.registry;
-- drop schema if exists conductor;
