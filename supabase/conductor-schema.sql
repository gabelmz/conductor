-- Conductor's schema-flexible Supabase mirror.
create table if not exists public.conductor_records (
  entity_type text not null,
  record_key text not null,
  payload jsonb not null default '{}'::jsonb,
  source_updated_at timestamptz,
  synced_at timestamptz not null default now(),
  primary key (entity_type, record_key)
);

create index if not exists conductor_records_entity_updated_idx
  on public.conductor_records (entity_type, source_updated_at desc);

create table if not exists public.sync_runs (
  id uuid primary key,
  direction text not null check (direction in ('push', 'pull', 'bidirectional')),
  conflict_policy text not null default 'newest',
  status text not null check (status in ('running', 'done', 'error')),
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  counts jsonb not null default '{}'::jsonb,
  error text not null default ''
);

create index if not exists sync_runs_started_idx on public.sync_runs (started_at desc);

alter table public.conductor_records enable row level security;
alter table public.sync_runs enable row level security;
-- Conductor uses a service-role key server-side; no public policies are created.
