-- Asana sync spine: lease / checkpoint / outbox tables + pg_cron schedule for the hosted
-- asana-sync Edge Function, plus additive observability columns on the existing sync_runs.
--
-- Matches supabase/conductor-schema.sql conventions: lowercase snake_case, `create table if
-- not exists public.*`, timestamptz, RLS enabled with no public policies (service-role only,
-- same as conductor_records/sync_runs already do).
--
-- Confirmed live schema (per this session's Supabase probe; re-verify before applying):
--   public.conductor_records (entity_type text, record_key text, payload jsonb,
--     source_updated_at timestamptz, synced_at timestamptz, primary key(entity_type, record_key))
--   public.sync_runs (id uuid pk, direction text, conflict_policy text, status text,
--     started_at timestamptz, finished_at timestamptz, counts jsonb, error text) -- reported
--     to already have rows; this migration only ADDS nullable columns to it, never drops or
--     retypes anything.
--   A `conductor` schema also reportedly exists in this project but the service_role key on
--   hand reportedly has no USAGE grant on it (permission denied, not undefined_schema) -- this
--   migration does not touch it in any case. See the closing report for the outstanding grant
--   this blocks. (This paragraph reflects an in-session claim this agent could not verify
--   live; treat it as unverified until a human confirms it directly.)
--
-- Safe to run more than once (IF NOT EXISTS / IF EXISTS / ADD COLUMN IF NOT EXISTS throughout).
-- Preserves all existing data; no DROP/TRUNCATE of any pre-existing object.

-- ---------------------------------------------------------------------------
-- 1) Lease: one row per sync entity, guarding hosted (Edge Function) vs. local-fallback
--    writers from ever writing the same records concurrently. Mirrors the shape of
--    backend/sync_runner.py's SyncLease (owner id, acquired_at, expires_at, heartbeat) so the
--    Edge Function and the local fallback can (in principle) coordinate through the same row
--    shape when both can reach Supabase; the local fallback keeps its own SQLite mirror of
--    this table for the case where Supabase itself is the thing that's unreachable.
-- ---------------------------------------------------------------------------
create table if not exists public.sync_leases (
  name          text primary key,
  owner         text not null,
  acquired_at   timestamptz not null default now(),
  expires_at    timestamptz not null,
  heartbeat_at  timestamptz not null default now()
);

comment on table public.sync_leases is
  'Mutual-exclusion lease per sync entity. A row with expires_at in the past is stealable by '
  'a new owner; a live row held by a different owner blocks acquisition. See '
  'backend/sync_runner.py:SyncLease for the matching local-fallback semantics.';

-- Atomic acquire/release RPCs for callers that can have genuinely concurrent invocations
-- against this shared table (the hosted Edge Function; two invocations can race in a way a
-- single local Python process's SyncLease never does). A read-then-write from a caller would
-- itself be a race condition, so the acquire logic is a single INSERT ... ON CONFLICT ...
-- DO UPDATE ... WHERE statement: the WHERE clause only lets the update through when the
-- existing row is expired or already owned by the same caller, and RETURNING is empty (NULL)
-- when it doesn't. See supabase/functions/asana-sync/index.ts for the only current caller.
create or replace function public.try_acquire_sync_lease(p_name text, p_owner text, p_ttl_s integer)
returns boolean
language plpgsql
as $$
declare
  v_acquired boolean;
begin
  insert into public.sync_leases (name, owner, acquired_at, expires_at, heartbeat_at)
  values (p_name, p_owner, now(), now() + make_interval(secs => p_ttl_s), now())
  on conflict (name) do update
    set owner = excluded.owner,
        acquired_at = excluded.acquired_at,
        expires_at = excluded.expires_at,
        heartbeat_at = excluded.heartbeat_at
    where public.sync_leases.expires_at < now() or public.sync_leases.owner = excluded.owner
  returning true into v_acquired;

  return coalesce(v_acquired, false);
end;
$$;

create or replace function public.release_sync_lease(p_name text, p_owner text)
returns void
language sql
as $$
  delete from public.sync_leases where name = p_name and owner = p_owner;
$$;

-- ---------------------------------------------------------------------------
-- 2) Checkpoint: persistent "how far did we get" cursor per entity.
-- ---------------------------------------------------------------------------
create table if not exists public.sync_checkpoints (
  entity      text primary key,
  cursor      text,
  updated_at  timestamptz not null default now()
);

comment on table public.sync_checkpoints is
  'Persistent incremental cursor per entity (e.g. asana_tasks -> last modified_at.after '
  'value). Only ever advanced after a batch has been durably committed somewhere (applied '
  'directly or queued in sync_outbox) -- see backend/sync_runner.py:run_sync.';

-- ---------------------------------------------------------------------------
-- 3) Outbox: durable queue used by either runner while conductor_records writes can't be
--    trusted to land immediately (e.g. a local-fallback run started before Supabase creds
--    were configured). Deduped on idempotency_key -- for Asana tasks this is the task gid,
--    the SAME key already used by conductor_records' own composite primary key
--    (entity_type, record_key) and by backend/supabase_sync.py's existing
--    entity_type='asana_tasks' convention. Not invented separately.
-- ---------------------------------------------------------------------------
create table if not exists public.sync_outbox (
  idempotency_key  text primary key,
  entity           text not null,
  op               text not null,
  payload          jsonb not null,
  status           text not null default 'pending' check (status in ('pending', 'synced', 'failed')),
  error            text not null default '',
  attempts         integer not null default 0,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);

create index if not exists sync_outbox_status_idx on public.sync_outbox (status);
create index if not exists sync_outbox_entity_idx on public.sync_outbox (entity);

comment on table public.sync_outbox is
  'Durable queue for records that could not be written directly (degraded mode). Draining '
  'on recovery applies pending rows oldest-modified_at-first (last-writer-wins keyed on the '
  'upstream Asana modified_at field, never wall-clock receipt order) -- see '
  'backend/sync_runner.py:_drain_outbox.';

-- ---------------------------------------------------------------------------
-- 4) Additive observability columns on the EXISTING public.sync_runs (do not touch its
--    current columns/rows). Mirrors backend/sync_runner.py's reuse of the local
--    asana_sync_runs table for the same reason: avoid a third/fourth overlapping runs log.
-- ---------------------------------------------------------------------------
alter table public.sync_runs add column if not exists entity text;
alter table public.sync_runs add column if not exists degraded boolean not null default false;
alter table public.sync_runs add column if not exists lease_owner text;
alter table public.sync_runs add column if not exists cursor_before text;
alter table public.sync_runs add column if not exists cursor_after text;

comment on column public.sync_runs.entity is 'Sync entity this run covered, e.g. asana_tasks. Nullable for pre-existing rows.';
comment on column public.sync_runs.degraded is 'True if this run wrote to sync_outbox instead of conductor_records because Supabase/the sync target was unhealthy at run time.';
comment on column public.sync_runs.lease_owner is 'Owner string that held sync_leases for this run (edge-function invocation id, or local-fallback host/pid).';
comment on column public.sync_runs.cursor_before is 'sync_checkpoints.cursor value read at the start of this run (null on a bootstrap run).';
comment on column public.sync_runs.cursor_after is 'sync_checkpoints.cursor value written at the end of this run, if any.';

-- ---------------------------------------------------------------------------
-- 5) RLS: enabled, no public policies -- service-role only, matching conductor_records/
--    sync_runs already in supabase/conductor-schema.sql.
-- ---------------------------------------------------------------------------
alter table public.sync_leases enable row level security;
alter table public.sync_checkpoints enable row level security;
alter table public.sync_outbox enable row level security;

-- ---------------------------------------------------------------------------
-- 6) pg_cron schedule invoking the asana-sync Edge Function.
--
-- NOTE (author-time limitation, cannot be verified without a live `supabase db push` /
-- dashboard session, which this migration was explicitly authored WITHOUT running): pg_cron
-- and pg_net must already be enabled as extensions on this project (Database -> Extensions in
-- the Supabase dashboard, or a prior migration) for this block to succeed, and
-- `<PROJECT_REF>`/the service-role key below must be filled in with real values before this
-- migration is applied -- placeholders are used deliberately rather than a real key, since
-- this file may be committed to source control. `net.http_post` requires the pg_net
-- extension; if either extension is unavailable this block will error, so the whole migration
-- should be tried in a scratch/staging project first.
-- ---------------------------------------------------------------------------
create extension if not exists pg_cron with schema extensions;
create extension if not exists pg_net with schema extensions;

do $$
begin
  if exists (select 1 from cron.job where jobname = 'asana-sync-every-15-min') then
    perform cron.unschedule('asana-sync-every-15-min');
  end if;
end;
$$;

select cron.schedule(
  'asana-sync-every-15-min',
  '*/15 * * * *',
  $$
  select net.http_post(
    url := 'https://<PROJECT_REF>.supabase.co/functions/v1/asana-sync',
    headers := jsonb_build_object(
      'Content-Type', 'application/json',
      'Authorization', 'Bearer <REPLACE_WITH_SERVICE_ROLE_OR_SCHEDULED_FUNCTION_KEY>'
    ),
    body := '{}'::jsonb
  );
  $$
);

-- =====================================================================================
-- ROLLBACK
-- =====================================================================================
-- Run these statements, in this order, to fully reverse this migration. They only remove
-- what this migration added -- conductor_records and every pre-existing sync_runs column/row
-- are left untouched.
--
-- select cron.unschedule('asana-sync-every-15-min');
--
-- alter table public.sync_runs drop column if exists cursor_after;
-- alter table public.sync_runs drop column if exists cursor_before;
-- alter table public.sync_runs drop column if exists lease_owner;
-- alter table public.sync_runs drop column if exists degraded;
-- alter table public.sync_runs drop column if exists entity;
--
-- drop table if exists public.sync_outbox;
-- drop table if exists public.sync_checkpoints;
--
-- drop function if exists public.release_sync_lease(text, text);
-- drop function if exists public.try_acquire_sync_lease(text, text, integer);
-- drop table if exists public.sync_leases;
--
-- -- pg_cron/pg_net are left installed (other jobs/projects may depend on them); drop them
-- -- explicitly only if you are certain nothing else on this project uses them:
-- -- drop extension if exists pg_net;
-- -- drop extension if exists pg_cron;
