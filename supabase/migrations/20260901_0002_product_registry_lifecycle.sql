-- 20260901_0002_product_registry_lifecycle.sql
-- ============================================================================
-- Product Registry lifecycle (owner: A3 — Keepa & Product Registry Engineer)
--
-- Introduces the seven-stage Product Registry lifecycle:
--   suggested -> staging -> review -> analysis -> submitted -> live -> archive
--
-- ONE canonical record per product/upload. Stage is a FIELD on that record
-- (`lifecycle_stage`) plus a full append-only history table
-- (product_registry_transitions) — rows are never duplicated per stage.
--
-- `registry_type` (what KIND of data this is — an uploaded ASIN list, a
-- catalog/product-data file, a Keepa export, suggested listing content, a
-- compliance document, ...) and `lifecycle_stage` (WHERE the record is in
-- the seven-stage workflow) are deliberately kept as SEPARATE columns.
--
-- Filename deliberately distinct from A2's 20260901_0001_* migration.
--
-- GREENFIELD, VERIFIED LIVE — this is not a migration of an existing model:
--   - A repo-wide search (`stage`, `lifecycle`, `registry_type`, `file_type`
--     across backend/*.py) found no prior Product Registry, and no
--     stage/lifecycle/registry_type/file_type columns anywhere.
--   - `public.conductor_records` (defined in supabase/conductor-schema.sql)
--     is the ONLY place product-shaped data currently lives in Postgres —
--     it's a schema-flexible entity mirror (entity_type, record_key,
--     payload jsonb, source_updated_at, synced_at), not a typed products
--     table, so there is nothing to ALTER a `products` table for.
--   - Queried live against the real Supabase project (ref
--     dfvylthyfrcarucyqgru) via a read-only REST call on 2026-09-01:
--     `conductor_records` currently holds ZERO rows of any entity_type
--     (`Content-Range: */0`). There is no existing product/upload
--     lifecycle metadata to preserve as of this migration being written.
--
-- Despite that, the backfill below is written generically (SELECT-driven
-- against conductor_records, not a hardcoded no-op) so it does the right,
-- safe thing if this migration is applied against an environment where
-- conductor_records DOES hold `entity_type = 'products'` rows by then —
-- it does not assume today's empty state will still hold at apply time.
--
-- Guardrails observed: additive only. No existing table or column is
-- ever ALTERed or DROPped — public.conductor_records and public.sync_runs
-- are read from (backfill SELECT) but never written to or modified. Fully
-- reversible — see the -- ROLLBACK section at the bottom for exact DOWN
-- statements. No destructive statements anywhere in this file.
-- ============================================================================


-- ----------------------------------------------------------------------------
-- FORWARD
-- ----------------------------------------------------------------------------

-- Stage definitions. Mirrors the (key, label, description, sort_order,
-- terminal, transitions) shape already used by this app's own lifecycle
-- modeling convention (see backend/spine.py's LIFECYCLES list and the
-- mirrored conductor.lifecycle_definitions rows seeded from it) rather
-- than inventing a second lifecycle-modeling idiom. `transitions` holds
-- the legal next stage_keys — this is the single source of truth the
-- application layer (backend/productpipeline.py) checks before writing a
-- transition; illegal transitions are rejected there with a clear error.
create table if not exists public.product_registry_stage_definitions (
  stage_key   text primary key,
  label       text not null,
  description text not null default '',
  sort_order  integer not null default 0,
  terminal    boolean not null default false,
  transitions jsonb not null default '[]'::jsonb,
  updated_at  timestamptz not null default now()
);

insert into public.product_registry_stage_definitions
  (stage_key, label, description, sort_order, terminal, transitions, updated_at)
values
  ('suggested', 'Suggested', 'Recommended candidate — not yet staged for work.',            10, false, '["staging","archive"]'::jsonb,           now()),
  ('staging',   'Staging',   'Selected and being assembled/prepared.',                       20, false, '["review","archive"]'::jsonb,             now()),
  ('review',    'Review',    'Awaiting human review of the prepared data.',                  30, false, '["analysis","staging","archive"]'::jsonb, now()),
  ('analysis',  'Analysis',  'Under compliance/attribute analysis.',                          40, false, '["submitted","staging","archive"]'::jsonb,now()),
  ('submitted', 'Submitted', 'Submitted to the marketplace (SP-API) for publish.',            50, false, '["live","analysis","archive"]'::jsonb,    now()),
  ('live',      'Live',      'Published and active on the marketplace.',                      60, false, '["archive"]'::jsonb,                      now()),
  ('archive',   'Archive',   'Retired; historical record only.',                              70, true,  '[]'::jsonb,                                now())
on conflict (stage_key) do update set
  label = excluded.label, description = excluded.description,
  sort_order = excluded.sort_order, terminal = excluded.terminal,
  transitions = excluded.transitions, updated_at = excluded.updated_at;

-- Canonical registry record — one row per product/upload.
create table if not exists public.product_registry_items (
  id              bigint generated always as identity primary key,
  item_key        text not null,                 -- sku/asin, or an upload_id when the record is file-only
  name            text not null default '',
  registry_type   text not null,                  -- asin_list | catalog_product | keepa_export | suggested_content | compliance_document | other
  lifecycle_stage text not null default 'suggested'
                    references public.product_registry_stage_definitions (stage_key),
  asin_source     text,                           -- connected | uploaded | recommended | manual (see backend/asin_sources.py)
  upload_id       text,
  upload_status   text,                           -- uploading | ready | parsing | done | error — matches the local files.status vocabulary (backend/storage.py)
  product_id      bigint,                         -- linked canonical product id, if any. No FK: the canonical `products` table
                                                   -- lives in local SQLite (backend/storage.py) today, not in this Postgres schema.
  raw             jsonb not null default '{}'::jsonb,   -- raw ingested payload (filename/size/original text, capped)
  parsed          jsonb not null default '{}'::jsonb,   -- normalized rows / extracted ASINs
  validation      jsonb not null default '{}'::jsonb,   -- {"ok": bool, "errors": [...], ...} from the last validation pass
  provenance      jsonb not null default '{}'::jsonb,   -- per-ASIN/per-field provenance (upload id, row number, ingested_at)
  metadata        jsonb not null default '{}'::jsonb,   -- free-form; backfilled rows record their mapping rationale here (see below)
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create index if not exists product_registry_items_stage_idx
  on public.product_registry_items (lifecycle_stage);
create index if not exists product_registry_items_registry_type_idx
  on public.product_registry_items (registry_type);
create index if not exists product_registry_items_item_key_idx
  on public.product_registry_items (item_key);
create index if not exists product_registry_items_upload_id_idx
  on public.product_registry_items (upload_id);

-- Transition history — append-only audit trail of every stage move.
create table if not exists public.product_registry_transitions (
  id         bigint generated always as identity primary key,
  item_id    bigint not null references public.product_registry_items (id) on delete cascade,
  from_stage text,
  to_stage   text not null,
  note       text not null default '',
  created_at timestamptz not null default now()
);

create index if not exists product_registry_transitions_item_idx
  on public.product_registry_transitions (item_id);


-- ----------------------------------------------------------------------------
-- BACKFILL — preserve existing metadata
--
-- Reads REAL current values from public.conductor_records where
-- entity_type = 'products' (that table — see supabase/conductor-schema.sql
-- — is this project's only existing mirror of product data; there is no
-- typed `products` table in Postgres to read from instead). This does NOT
-- assume a shape: it checks every legacy status/stage location plausible
-- for a synced product row, using the vocabularies that actually exist
-- elsewhere in this codebase:
--   - payload->>'status'                 (a literal top-level status field, if any entity ever carries one)
--   - payload->'attributes'->>'status'   (a custom attribute a bulk import may have set on a product)
--   - payload->>'lifecycle_stage'        (in case a row was ever pre-seeded with this migration's own field name)
--
-- Mapping rationale (only reached if one of the above is non-null —
-- verified live against the real project on 2026-09-01 that NONE are,
-- see the header note above, so every backfilled row today would in fact
-- land on the `else` branch — this CASE exists for correctness against a
-- future, non-empty state, not because today's data requires it):
--   draft                    -> staging    (created, not yet reviewed — matches product_pipelines.status
--                                            and the generic spine lifecycle's 'draft')
--   uploading / parsing      -> staging    (files.status values meaning "still being prepared")
--   ready / done             -> review     (files.status values meaning "data is in hand"; needs a human to review it)
--   active                   -> live       (the app's own existing word for "in active use" — spine lifecycle 'active')
--   disabled / deprecated    -> archive    (retired but not urgent — spine lifecycle terms)
--   archived                 -> archive    (already the same word)
--   error                    -> archive    (files.status 'error' — a failed upload is not actionable; parked, not silently advanced)
--   anything else / missing  -> suggested  (see justification below)
--
-- Rows with NO recognizable legacy status default to 'suggested' —
-- deliberately the EARLIEST, least-committed stage, never to 'live' or
-- any advanced stage. Defaulting forward would assert facts with no
-- evidence behind them (e.g. that the item is actually published on
-- Amazon); 'suggested' only asserts "this record exists and needs a
-- human to triage it," which is always a true, safe statement, and it
-- requires an explicit, legal transition (enforced by the application
-- layer against product_registry_stage_definitions.transitions) before
-- the record can move anywhere else.
--
-- Every backfilled row is tagged in `metadata` with what it was
-- backfilled from and which legacy value (if any) drove the mapping, so
-- backfilled rows stay distinguishable from rows created via the new
-- registry flow going forward.
insert into public.product_registry_items
  (item_key, name, registry_type, lifecycle_stage, asin_source, upload_id,
   upload_status, product_id, raw, parsed, validation, provenance, metadata,
   created_at, updated_at)
select
  cr.record_key,
  coalesce(cr.payload ->> 'name', cr.record_key),
  'catalog_product',
  case lower(coalesce(
        cr.payload ->> 'status',
        cr.payload -> 'attributes' ->> 'status',
        cr.payload ->> 'lifecycle_stage',
        ''))
    when 'draft'      then 'staging'
    when 'uploading'  then 'staging'
    when 'parsing'    then 'staging'
    when 'ready'      then 'review'
    when 'done'       then 'review'
    when 'active'     then 'live'
    when 'disabled'   then 'archive'
    when 'deprecated' then 'archive'
    when 'archived'   then 'archive'
    when 'error'      then 'archive'
    else 'suggested'
  end,
  'manual',
  null,
  null,
  null,
  '{}'::jsonb,
  '{}'::jsonb,
  coalesce(cr.payload, '{}'::jsonb),
  jsonb_build_object(
    'backfilled', true,
    'backfilled_from', 'public.conductor_records',
    'backfilled_at', now(),
    'legacy_status_seen', coalesce(cr.payload ->> 'status', cr.payload -> 'attributes' ->> 'status', cr.payload ->> 'lifecycle_stage'),
    'reason', 'No product_registry_items row existed yet for this key. lifecycle_stage was derived from whatever legacy status/stage field (if any) was present in conductor_records.payload, defaulting to ''suggested'' when none was found — see the migration file for the full mapping table and rationale.'
  ),
  coalesce(cr.source_updated_at, cr.synced_at, now()),
  coalesce(cr.synced_at, now())
from public.conductor_records cr
where cr.entity_type = 'products'
  and not exists (
    select 1 from public.product_registry_items pri where pri.item_key = cr.record_key
  );

alter table public.product_registry_stage_definitions enable row level security;
alter table public.product_registry_items enable row level security;
alter table public.product_registry_transitions enable row level security;
-- Conductor uses a service-role key server-side; no public policies are
-- created (matches the existing convention in supabase/conductor-schema.sql).


-- ============================================================================
-- ROLLBACK
-- ----------------------------------------------------------------------------
-- Exact DOWN statements. The forward migration above is purely additive
-- (no existing table/column was ALTERed or DROPped — conductor_records
-- and sync_runs are untouched), so rollback is a clean, safe drop of only
-- what this migration created. Order matters: drop the table that holds
-- the foreign keys (product_registry_transitions) before the table it
-- references (product_registry_items), and drop product_registry_items
-- before product_registry_stage_definitions (which it references).
--
-- To roll back, uncomment and run the three statements below:
--
-- drop table if exists public.product_registry_transitions;
-- drop table if exists public.product_registry_items;
-- drop table if exists public.product_registry_stage_definitions;
-- ============================================================================
