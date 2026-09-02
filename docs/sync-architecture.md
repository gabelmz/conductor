# Conductor Sync Architecture — A1 Findings

Author: A1 (Architecture & Integration Lead). Read-only audit of the sync stack. Every claim below cites `file:line`; anything I could not verify by reading code is marked `UNVERIFIED:`. No Supabase/Asana MCP calls were made — both are unauthenticated in this session (confirmed by the harness, not by me probing them). No test run is claimed here beyond the baseline the brief already established (8 passed, `test_asana_kpis.py` + `test_supabase_sync.py`).

---

## 1. Source map

### `backend/asana_sync.py` (568 lines)
Direct Asana REST → local SQLite sync engine. No Supabase awareness at all — it only imports `storage` (`backend/asana_sync.py:33`).

- Config: `data/asana.json`, loaded/saved by `_load_config`/`_save_config` (`backend/asana_sync.py:69-92`). **Currently contains a live PAT in plaintext** — I read it (`data/asana.json`) and confirmed a real token is stored on disk; I am not reproducing it here. Env var `ASANA_PAT` is a fallback (`backend/asana_sync.py:76`).
- `get_config()` (`:94-106`) returns a redacted view; `has_credentials()` (`:125-126`) gates every sync entry point.
- `api_get()` (`:158-182`) is the only HTTP verb implemented — GET with 429/5xx retry (`MAX_RETRIES=5`, backoff `2*attempt`, `Retry-After` honored). **There is no `api_post` in this file.** `backend/main.py:742` calls `asana_sync.api_post(...)` guarded by `hasattr(asana_sync, "api_post")`, which is always `False` — dead branch, always falls through to the urllib fallback a few lines below (`backend/main.py:743-750`). Flagged in risk register.
- `paginate()` (`:185-199`) walks Asana's offset pagination.
- `TASK_OPT_FIELDS` (`:48-61`) is the exact field set pulled per task. Confirmed field names: `gid` (stable identity) and `modified_at` (Asana's own last-write timestamp) both appear verbatim in the opt_fields string (`backend/asana_sync.py:49`).
- `sync_all(mode, deep, progress)` (`:231-379`) orchestrates: workspaces → users → teams → projects → (deep-only) custom field defs → tasks. `mode='all'` walks every active project's `/tasks`; `mode='delta'`/`'recent'` uses `/workspaces/{ws}/tasks/search` with `modified_since` (`:341-350`) — this is the only incremental primitive Asana exposes here, and it is driven by `cfg["last_sync"]`, a value stored **locally** in `data/asana.json` (`:373-374`), not in any shared/cloud location.
- `_store_task()` (`:382-499`) upserts one task via `storage.upsert_asana_task(...)` into SQLite `asana_tasks` (schema at `backend/storage.py:135-166`), plus `replace_asana_task_memberships`/`replace_asana_task_custom_fields`.
- `fetch_task_details(gid)` (`:501-568`) lazy-hydrates stories/attachments/subtasks on demand (deep sync is too slow for large orgs, per the docstring at `:1-20`).
- Rate limiting: single `MIN_INTERVAL_S=0.45` pacer shared across a PAT round-robin (`:130-155`), multi-PAT rotation via `cfg["pats"]` (`:77-78`, `:141-155`).

### `backend/supabase_sync.py` (423 lines)
Generic, schema-flexible JSONB mirror. Deliberately does not import `storage` at module scope (`backend/supabase_sync.py:3-5`) — callers inject a `LocalAdapter`.

- Config: `data/supabase.json` (`:19`). **This file does not exist in the working tree** — I confirmed by reading the `data/` directory listing; Supabase sync is unconfigured today, consistent with the stated environment blocker.
- `SUPPORTED_ENTITIES = {"products", "asana_tasks"}` (`:20`).
- `router = APIRouter(prefix="/api/supabase", ...)` (`:21`).
- Every entity type is mirrored into **one single Postgres table**, `conductor_records` (entity_type, record_key, payload jsonb, source_updated_at, synced_at) — not per-entity typed tables. `_push_entity()` (`:134-162`) POSTs rows keyed by `(entity_type, record_key)` with `on_conflict=entity_type,record_key` and `Prefer: resolution=merge-duplicates`. `_pull_entity()` (`:174-220`) pages `conductor_records` filtered by `entity_type=eq.<x>` and applies a conflict policy.
- Conflict policy `"newest"` (default, `:227`) compares `local.get(adapter.updated_field)` vs. `row.get("source_updated_at") or payload.get(adapter.updated_field)` (`:212-217`) — **local wins ties and any unparsable timestamp**; there is no surfaced-conflict state, it is silent last-writer-wins.
- `sync(direction, adapters, conflict, session)` (`:223-299`) writes a `sync_runs` row up front (`status="running"`) and patches it to `"done"`/`"error"` at the end (`:242-292`) — this is the only run-provenance table that exists today.
- `_product_upsert()` (`:302-324`) and `_asana_task_upsert()` (`:327-343`) are the two concrete local adapters. `_asana_task_upsert` whitelists an `allowed` field set (`:333-339`) that **includes `weight`** but only sets it in the outgoing SQLite row if the remote payload happens to contain that key — see risk register, this interacts badly with `storage._upsert`'s `INSERT OR REPLACE` semantics.
- `local_adapters(entity)` (`:346-353`) maps `"products"` → `storage.list_products`/`_product_upsert` (key `sku`, updated field `updated_at`) and `"asana"|"asana_tasks"` → `storage.list_asana_tasks`/`_asana_task_upsert` (key `gid`, updated field `modified_at`).
- Routes: `GET /status` (`:366-368`), `POST /config` (`:371-385`), `POST /test` (`:388-401`), `GET /runs` (`:404-409`), `POST /sync/{dataset}/{direction}` (`:412-423`).

### `backend/spine.py` (288 lines)
Purely local. **It writes nothing to Supabase.** Every table it touches is a `spine_*` SQLite table created in `init_spine_db()` (`backend/spine.py:100-159`) and seeded in `seed_defaults()` (`:164-181`). The module docstring says `conductor.*` in Supabase "mirrors this shape when cloud sync is configured" (`:7-8`), but there is no code anywhere in this file (or, per the searches below, anywhere in `backend/`) that pushes a `spine_*` row to Postgres. `router = APIRouter(prefix="/api/spine", ...)` (`:22`) exposes `GET /snapshot`, `/glossary`, `/models`, `/nodes`, `/filters`, `GET|PUT /config/{scope}/{key}` — all SQLite-backed reads/writes (`:225-288`).

### `spine_sync_supabase.sql` (154 lines) and `spine_sync_models_registry.sql` (665 lines)
**Not generated by any code currently in the repo.** I grepped `backend/`, `scripts/`, `desktop/`, `supabase/`, every `*.py` and `*.md` for `spine_sync_supabase`, and for the four Postgres table names it inserts into (`conductor.status_definitions`, `conductor.lifecycle_definitions`, `conductor.node_library`, `conductor.datasets`) — the only hits are the SQL file itself and `docs/CONDUCTOR-SPINE.md`. There is no Python/JS emitter, no scheduled job, nothing under `scripts/`. `git log --diff-filter=A -- spine_sync_supabase.sql` shows both files were added together, from nothing, in one commit: `0a96433 "bgiug;igiy"` (an unclear/garbled message, authored `gbe <gabe@luminize.com>`, 2026-09-01 00:47 -0700) — confirmed via `git show --stat 0a96433`. **The prior assumption that `backend/spine.py` is the generator is wrong** — I read the whole file; it contains zero Supabase-writing code. These two `.sql` files are hand- or externally-produced seed dumps, not a reproducible build artifact.
- They target a Postgres schema `conductor` (i.e. `conductor.status_definitions`, `.lifecycle_definitions`, `.node_library`, `.datasets`, plus `.file_type_definitions`, `.model_catalog`, `.model_presets`, `.registry`, `.global_filter_definitions` in the models-registry file) that **has no corresponding `CREATE SCHEMA`/`CREATE TABLE` anywhere in this repo.** `supabase/conductor-schema.sql` — the only committed DDL — never mentions a `conductor` schema (see below). Running either `.sql` file against a fresh Supabase project as it exists in this repo today would fail with `relation "conductor.status_definitions" does not exist`.
- `docs/CONDUCTOR-SPINE.md:59-63` asserts "Supabase project `dfvylthyfrcarucyqgru` now contains the `conductor.*` mirror tables with RLS enabled" — this is an unverifiable claim from inside the repo's own docs (no MCP access to confirm/deny), and it is **not corroborated by any migration file in this repo**. Treat it as aspirational documentation, not a source of truth about live Supabase state.

### `supabase/conductor-schema.sql` (29 lines) — the actual, real schema
Defines exactly two tables, both `public.*`, both matching `supabase_sync.py` byte-for-byte:
- `public.conductor_records(entity_type text, record_key text, payload jsonb, source_updated_at timestamptz, synced_at timestamptz, primary key(entity_type, record_key))` (`supabase/conductor-schema.sql:2-9`), plus an index on `(entity_type, source_updated_at desc)` (`:11-12`).
- `public.sync_runs(id uuid primary key, direction text, conflict_policy text, status text, started_at, finished_at, counts jsonb, error text)` (`:14-23`), index on `started_at desc` (`:25`).
- RLS is enabled on both, **no policies defined** — comment states "Conductor uses a service-role key server-side; no public policies are created" (`:27-29`). This means: only a service-role key can read/write these tables; there is no anon-key path, and therefore no browser-side Supabase access is possible against this schema as written.
- **`sync_runs` has no `entity_type` column.** A run's `counts` jsonb records aggregate push/pull/skip totals, but nothing on this row says *which* entity/dataset it was for when multiple adapters run in one `sync()` call — this matters for the cursor design below.

---

## 2. Callers

### `asana_sync` imports (all in `backend/`; frontend never imports Python modules, it calls REST)
| File:line | Call |
|---|---|
| `backend/main.py:38` | `import asana_sync` (module scope) |
| `backend/main.py:549` | `asana_sync.get_config()` in `GET /api/asana/status` |
| `backend/main.py:564` | `asana_sync.save_config(**payload)` in `POST /api/asana/config` |
| `backend/main.py:574,592` | `asana_sync.has_credentials()`, `asana_sync.sync_all(...)` in `POST /api/asana/sync` |
| `backend/main.py:612,632` | `asana_sync.has_credentials()`; re-enters `asana_sync_start` in `POST /api/asana/hook/pull` |
| `backend/main.py:681` | `asana_sync.fetch_task_details(gid)` in `GET /api/asana/tasks/{gid}` |
| `backend/main.py:736-750` | `asana_sync.has_credentials()`, `asana_sync._headers()`, dead `api_post` hasattr check, urllib fallback, in `POST /api/asana/tasks/create` |
| `backend/main.py:759-768` | same pattern in `POST /api/asana/tasks/{gid}/comments` |
| `backend/main.py:841` | `asana_sync.get_config()` for dashboard/status rollup |
| `backend/automation.py:307-311` | `_asana_client()` builds headers from `asana_sync.get_config()`/`asana_sync.BASE_URL` for rule-engine live actions |
| `backend/automation.py:879-880` | integration-status check via `asana_sync.has_credentials()` |
| `backend/automation.py:903-904` | `asana_sync.save_config(pat=...)` — Settings→Integrations "asana" card writes into the *same* `data/asana.json` asana_sync owns |
| `backend/data.py:255-256` | `asana_sync.get_config()` for a data-page status widget |

### `supabase_sync` imports
| File:line | Call |
|---|---|
| `backend/main.py:992` | `from supabase_sync import router as supabase_sync_router` |
| `backend/main.py:1013` | `app.include_router(supabase_sync_router)` — mounts `/api/supabase/*` |
| `backend/main.py:641-645` | `supabase_sync.sync(direction=..., adapters=supabase_sync.local_adapters("asana_tasks"))` inside the `POST /api/asana/push-supabase` handler |
| `backend/main.py:733-745` (route `POST /api/asana/push-supabase`) | `supabase_sync.sync(direction="push", adapters=supabase_sync.local_adapters("asana_tasks"))` |
| `backend/brand_onboarding.py:190-194` | same push pattern, from `POST /onboarding/push-onboarding-tasks` |
| `backend/automation.py` | **no** `supabase_sync` import found |

### Router mounting (`backend/main.py`)
Imports at `:38` (`asana_sync`), `:50` (`from reporting.team_kpis import router as asana_kpis_router`), `:52` (`from spine import init_spine_db, router as spine_router`), `:992` (`supabase_sync_router`). `app.include_router(...)` calls for every router are grouped at `:993-1013`, ending with `supabase_sync_router`, `spine_router`, `asana_kpis_router`, `listing_compare_router`, `kpi_router`, `wrangler_router`, `onboarding_router` — no path-prefix collisions observed (`/api/asana/*` routes are declared as bare `@app.*` handlers in `main.py` itself, not a mounted router — there is no `asana_sync.router`, all Asana HTTP endpoints live directly in `main.py`).

### `backend/asana_kpis.py` (163 bytes)
A pure re-export shim: `from reporting.team_kpis import *` (`backend/asana_kpis.py:5`). It does not import `asana_sync` or `supabase_sync` itself; `reporting/team_kpis.py` was grepped for both and returned no matches — it reads Asana data only through `storage`'s already-synced `asana_tasks` table, not live.

### Build artifact check
`dist/win-unpacked/resources/backend/asana_sync.py` exists (build copy). Diffed the first 50 lines against `backend/asana_sync.py` — identical. Grepped the whole repo for any import path containing `dist/win-unpacked` — the only hits are `.eb/manifest.json` and `.eb/manifest-all.json` (release-manifest bookkeeping, not Python imports). **Nothing in application code imports from `dist/`.** Confirmed safe to ignore for this design, but it will go stale silently on the next `backend/asana_sync.py` edit until the next build — not this doc's problem, flagging for A2/A6 awareness only.

---

## 3. Target contract — Cron → Supabase Edge Function → Asana sync → Supabase tables → Conductor

Ground rule: today, exactly two Supabase tables are real (`public.conductor_records`, `public.sync_runs`, both in `supabase/conductor-schema.sql`). The contract below **extends that schema minimally** rather than inventing the `conductor.*` typed-table world implied by `docs/CONDUCTOR-SPINE.md` and the two orphaned seed `.sql` files — those are unverified against any live migration and I am not treating them as ground truth.

### 3.1 Table set and column contract
- **`public.conductor_records`** (unchanged) is what the Edge Function writes to and what desktop Conductor already reads from via `_pull_entity` (`backend/supabase_sync.py:174-220`). For `entity_type='asana_tasks'`, `payload` must be a JSON object using the **exact same key set** `_asana_task_upsert`'s `allowed` frozenset already expects (`backend/supabase_sync.py:333-339`): `gid, name, resource_subtype, project_gid, project_name, section, team_gid, team_name, assignee_gid, assignee_name, assignee_email, due_on, start_on, completed, completed_at, created_at, modified_at, permalink, parent_gid, parent_name, num_subtasks, tags, followers, dependencies, dependents, notes, custom_fields, memberships, weight`. If the Edge Function omits `weight`, do not rely on `_asana_task_upsert` to backfill it — see risk register §6.4, this is a real clobber bug that must be fixed in `supabase_sync.py` (code change, not this doc) before the Edge Function ships, or the Edge Function must always compute and include `weight` itself using the identical rule at `backend/asana_sync.py:203-207` (`0.3` if `/keepa/i` matches the name, else `1.0`).
- `record_key` = Asana task `gid` (already how `local_adapters()` wires the `asana_tasks` adapter — `backend/supabase_sync.py:352`, `key_field="gid"`).
- `source_updated_at` = Asana's `modified_at` (already how the adapter is wired — `updated_field="modified_at"`, same line). This is the field Asana itself stamps on every write; do not substitute a sync-time timestamp.
- **`public.sync_runs`** (unchanged) is where the Edge Function must log its own run the same way `sync()` does (`backend/supabase_sync.py:242-292`): a `status="running"` row on start, `"done"`/`"error"` patch on completion, `counts={"pushed":N,"pulled":0,"skipped":M}` in the same shape existing runs already use — this keeps `GET /api/supabase/runs` (`backend/supabase_sync.py:404-409`) meaningful for both hosted and local runs in one timeline.
- **New: `public.sync_cursors`** — required because `sync_runs` has no `entity_type` column (§1) and `data/asana.json`'s `last_sync` (`backend/asana_sync.py:373-374`) is local-only and invisible to a hosted Edge Function. Minimal shape:
  ```sql
  create table public.sync_cursors (
    entity_type text primary key,
    cursor_value text not null,      -- ISO8601 modified_at watermark
    updated_at timestamptz not null default now()
  );
  ```
  One row, `entity_type='asana_tasks'`.
- **New: `public.sync_leases`** — concurrency guard, see §3.4.

### 3.2 Idempotency key
Per Asana-task record: **`gid`** as the identity, **`modified_at`** as the write-comparator — not invented, this is what Asana's API returns (`TASK_OPT_FIELDS` at `backend/asana_sync.py:49` includes both verbatim) and what the existing adapter already keys on (`backend/supabase_sync.py:352`). `(entity_type, record_key)` is already the Postgres primary key on `conductor_records` (`supabase/conductor-schema.sql:8`), so upserts are naturally idempotent at the row level; `modified_at` inside `payload` (mirrored to `source_updated_at`) is what conflict resolution compares (`backend/supabase_sync.py:212-217`).

### 3.3 Incremental cursor design
- **Field**: `modified_at`, fed to Asana's `/workspaces/{ws}/tasks/search?modified_since=...` (`backend/asana_sync.py:341-350`) — the only incremental-pull primitive Asana's API exposes here.
- **Where stored**: `public.sync_cursors.cursor_value` (new table, §3.1) — a **hosted, shared** watermark, replacing (for the Edge Function path only) the local-only `data/asana.json.last_sync`. Desktop Conductor's own `asana_sync.sync_all(mode="delta")` keeps using its local `cfg["last_sync"]` for *its own* pulls — the two cursors are intentionally separate because the two writers (Edge Function, desktop app) can run independently and must not stomp each other's watermark, only their own.
- **How advanced**: the Edge Function reads `sync_cursors` first, calls Asana with `modified_since=cursor_value`, and only after a **successful** full page-through and successful `conductor_records` write does it `PATCH` the cursor forward to the run's own `started_at` (not to Asana's response time — mirrors `asana_sync.py:373-374`'s "stamp our own clock, not the API's" pattern, which avoids clock-skew gaps between Asana and the sync host).

### 3.4 Concurrency guard
Both the hosted Edge Function (on a cron) and the desktop app (`POST /api/asana/sync`, `backend/main.py:568-598`, and the auto-pull hook at `:610-634`) can independently decide to sync Asana. Without a guard, both could run `sync_all`/push at once, doubling Asana API load and racing on `conductor_records` writes.
- **Mechanism**: a lease row in **`public.sync_leases`**:
  ```sql
  create table public.sync_leases (
    lease_key text primary key,       -- e.g. 'asana_tasks'
    holder text not null,             -- e.g. 'edge:cron' or 'desktop:<device_id>'
    acquired_at timestamptz not null,
    expires_at timestamptz not null
  );
  ```
  Acquire = `POST /rest/v1/sync_leases` (plain insert, no `on_conflict`). If Postgres rejects on the primary-key conflict, retry as `PATCH /rest/v1/sync_leases?lease_key=eq.asana_tasks&expires_at=lt.<now>` with the new holder/expiry — this is a conditional update (only rows matching the filter change), so it is a compare-and-swap purely through PostgREST semantics already used elsewhere in this codebase (the same filter-as-condition pattern `_pull_entity` uses for `entity_type=eq.<x>`, `backend/supabase_sync.py:186`). If the `PATCH` response body is empty, the lease is currently held by someone else and still live — back off. Release = `PATCH ...&lease_key=eq.asana_tasks` setting `expires_at=now()` immediately after the run finishes (or just let it expire — expiry should be short, e.g. 10 minutes, comfortably longer than one delta sync but short enough that a crashed holder self-clears).
  This needs **no new dependency and no raw-SQL/RPC connection** from either the Edge Function or the desktop app — both already speak PostgREST-over-HTTP (`backend/supabase_sync.py:87-112`), so the same `_request()` helper (or its Edge Function equivalent) can implement lease acquire/release with the exact HTTP verbs it already knows how to issue.

### 3.5 Degraded/outbox contract and reconciliation
- **Today's actual degraded mode**: Conductor never blocks on Supabase at all. `asana_sync.sync_all()` writes straight to local SQLite (`backend/storage.py`'s `asana_tasks`) regardless of whether `data/supabase.json` exists — confirmed it does not exist in this checkout. Supabase push is a separate, optional, explicitly-triggered action (`POST /api/asana/push-supabase`, `backend/main.py:733-745`). This is already a reasonable local-first fallback for **reads**; the gap is **writes made locally while offline that need to reach Asana/Supabase later** (e.g. `POST /api/asana/tasks/create`, `backend/main.py:733-750`, or `.../comments`, `:759-775`) — these call Asana directly and simply fail with no queued retry if Asana/network is unreachable; there is no outbox today.
- **Proposed outbox** (local SQLite, new table, additive — not in scope for this doc to implement, flagged for A2): `outbox_events(id, entity_type, record_key, op, payload_json, created_at, attempts, last_error, status)`. Every locally-initiated mutation destined for Asana/Supabase writes a row here first; a drain loop (same shape as the existing `jobs` queue pattern already used for `asana_sync` — `backend/main.py:583-597`) replays rows in order, marking `status='sent'` only after the remote call 2xx's, keyed so a retried drain never double-sends (natural key: `(entity_type, record_key, op)` plus a monotonic `id` tiebreak for multiple edits to the same record).
- **Reconciliation on recovery**: the existing `conflict="newest"` comparator (`backend/supabase_sync.py:212-217`) is the only conflict logic that exists, and it is **silent last-writer-wins by timestamp, with local winning ties/unparsable dates**. It does not detect or surface a true conflict (both sides changed since last sync) — it just picks one and discards the other. For the outbox path this is not safe enough: a task edited locally while offline *and* edited in Asana by someone else in the same window will silently lose one side's edit with zero record that it happened. Recommend (A2 scope): add a `sync_conflicts` table that `_pull_entity`-equivalent logic writes to instead of silently skipping whenever `local_time` and `remote_time` are both present and different from what was last successfully synced — i.e. detect the conflict case explicitly rather than only comparing "which is newer."

---

## 4. Dependency graph

```
                         +----------------------------+
                         | A2: asana_sync / supabase_  |
                         | sync / edge fn / migrations |
                         |  (owns: conductor_records,  |
                         |   sync_runs, sync_cursors,  |
                         |   sync_leases DDL + code)   |
                         +-------------+----------------+
                                       | blocks -- everyone downstream needs
                                       | the real schema + idempotency/cursor
                                       | contract locked before building on it
                 +---------------------+----------------------------+
                 v                     v                            v
      +-----------------+   +-------------------+       +----------------------+
      | A3: keepa ASIN  |   | A4: Bernie Canvas  |       | A5: tests            |
      | sources +       |   | (needs stable      |       | (needs the final     |
      | product registry|   | node_library /     |       | table/column         |
      | lifecycle       |   | dataset shape --   |       | contract to write    |
      | (needs the same |   | spine.py's SQLite  |       | fixtures against --  |
      | conductor_      |   | shape is already   |       | cannot test the      |
      | records pattern |   | stable per S1, but |       | Edge Function or     |
      | IF it mirrors   |   | if A2 adds a real  |       | lease/cursor tables  |
      | product rows to |   | conductor.* schema,|       | until A2 ships DDL)  |
      | Supabase)       |   | Bernie's node      |       +----------+-----------+
      +--------+--------+   | picker must not    |                  |
               |            | silently start     |                  |
               |            | reading it --      |                  |
               |            | flag to A4 now)    |                  |
               |            +---------+----------+                  |
               +----------------------+---------------------------- +
                                       v
                              +-------------------+
                              | A6: acceptance    |
                              | (blocked on A2+   |
                              |  A3+A4+A5 all     |
                              |  landing; also    |
                              |  blocked on live   |
                              |  Supabase/Asana    |
                              |  auth -- cannot    |
                              |  acceptance-test   |
                              |  against mocks)    |
                              +-------------------+
```
A2 is the hard gate: nobody can build against `conductor_records`/`sync_runs`/`sync_cursors`/`sync_leases` until that contract (§3) is actually implemented and migrated, because none of it exists in Supabase today in a verified state (see §6.1). A3 only blocks on A2 if it reuses the same generic mirror table — if A3's product-registry sync instead wants typed `conductor.*` tables, that is a **second, independent schema decision** A2 and A3 need to make together, not assume. A4 (Bernie Canvas) depends on `spine.py`'s **local** shape (§1), which is stable and already tested (`tests/test_spine.py`) — A4 does not need to wait on A2 unless someone wires Bernie's node picker to a live `conductor.*` Supabase table, which nothing today does. A5 needs A2's DDL to exist before it can write real fixtures (mock-based tests can be written against the *documented* contract now, but cannot be validated end-to-end without A2's tables). A6 is blocked transitively on A2–A5 and, independently, on Supabase/Asana MCP auth being restored — flagged as an environment blocker, not a code dependency.

---

## 5. Rollback plan

### 5.1 `public.sync_cursors` (new table)
- Forward: `CREATE TABLE public.sync_cursors (...)` per §3.1, one seed row `('asana_tasks', '', now())`.
- Reverse: `DROP TABLE public.sync_cursors;`
- Data lost on reverse: only the watermark itself. No task data is stored here — losing it just forces the next Edge Function run to fall back to a full `mode='all'`-equivalent pull (bounded by whatever `modified_since` default the Edge Function chooses, e.g. re-derive from `max(source_updated_at)` already sitting in `conductor_records` for `entity_type='asana_tasks'` — recoverable, not destructive).

### 5.2 `public.sync_leases` (new table)
- Forward: `CREATE TABLE public.sync_leases (...)` per §3.4, no seed data required.
- Reverse: `DROP TABLE public.sync_leases;`
- Data lost on reverse: nothing durable — a lease is by design transient/expiring. Reversing this while a sync is mid-flight just removes the guard; worst case is a double-run (extra Asana API load, not data loss, since `conductor_records` writes are idempotent on `(entity_type, record_key)`).

### 5.3 `weight` clobber fix in `_asana_task_upsert` (code change, flagged for A2, not a schema migration)
- Forward: change `_asana_task_upsert` (`backend/supabase_sync.py:327-343`) to always compute `weight` from the task name (reusing `asana_sync.task_weight`, `backend/asana_sync.py:206-207`) rather than passing through whatever the remote payload happened to include, before calling `storage._upsert("asana_tasks", payload)`.
- Reverse: revert the one function to today's behavior.
- Data lost on reverse: none — this only affects a derived scalar (`weight`) recomputed on every upsert; nothing upstream depends on a stored history of past `weight` values.

### 5.4 Any future move from `conductor_records` (generic JSONB) to typed `conductor.asana_tasks` (should A2/A3 choose this path)
- Forward: `CREATE TABLE conductor.asana_tasks (...)` with the same column list as SQLite's `asana_tasks` (`backend/storage.py:135-165`); backfill via `INSERT INTO conductor.asana_tasks SELECT (payload->>'gid'), payload->>'name', ... FROM public.conductor_records WHERE entity_type='asana_tasks'`.
- Reverse: `DROP TABLE conductor.asana_tasks;` — `conductor_records` is untouched by this migration either direction (it is a superset source, not replaced), so **nothing is destructively lost** in either direction as long as `conductor_records` keeps being written until the typed table is proven out. Do not decommission `conductor_records` writes until this new table has run in production for at least one full sync cycle with counts cross-checked against `conductor_records`.

I found no evidence any of these four migrations are drafted anywhere in the repo yet — this section is a plan, not a description of existing code.

---

## 6. Risk register

1. **`docs/CONDUCTOR-SPINE.md` and two committed `.sql` seed files describe a `conductor.*` Supabase schema that does not exist in this repo's own migration file (`supabase/conductor-schema.sql`).** If anyone treats that doc or those `.sql` files as "the schema is already built," they will design against tables that — per everything checked in this repo — were never migrated anywhere real. The commit that added both `.sql` files (`0a96433`) has a garbled, non-descriptive message ("bgiug;igiy"), which itself suggests they were not part of a reviewed, intentional change. **Treat `conductor.*` as unbuilt until someone with live Supabase access confirms otherwise — I could not, MCP is unauthenticated.**
2. **Environment blockers are real and total for this pass**: Supabase MCP and Asana MCP are both configured but unauthenticated in this session; Playwright/chrome-devtools MCP failed to connect. Nothing in this document reflects a live API call, a live schema introspection, or a live Asana field check beyond what is hardcoded in `asana_sync.py`'s `TASK_OPT_FIELDS`. Any claim about live Supabase table state (including everything in item 1) is unverifiable right now — A2 must re-verify against a real connection before writing migrations, not trust this doc's inferences from static files alone.
3. **`data/asana.json` holds a live, unredacted PAT on disk** (`data/asana.json`, confirmed by reading it). This is orthogonal to the sync-architecture design but is a real, present secret-hygiene issue in this checkout; whoever touches config next should not commit or screenshot that file.
4. **`_asana_task_upsert`'s `weight` clobber** (§5.3): pulling from Supabase through the existing adapter can silently reset a task's `weight` from the keepa-derived `0.3` back to the schema default `1.0` if the remote payload omits the key, because `storage._upsert` performs `INSERT OR REPLACE` (`backend/storage.py:716-735`) — a full-row replace, not a merge. Any column present in the SQLite table but absent from the incoming `payload` dict silently reverts to its column default on every pull. This is a general hazard of the current `_upsert` helper, not just a `weight` problem — any future column added to `asana_tasks` that isn't also added to `_asana_task_upsert`'s `allowed` set (`backend/supabase_sync.py:333-339`) will be silently zeroed on the next Supabase pull.
5. **Dead code path**: `backend/main.py:742` guards on `hasattr(asana_sync, "api_post")`, which does not exist in `asana_sync.py` — confirmed by reading the full 568-line file. The condition is always `False`; the branch is unreachable and should either be removed or `api_post` should be implemented if the intent was to route task-creation through the same retry/pacing logic as `api_get`. Today, task creation (`POST /api/asana/tasks/create`) bypasses `asana_sync`'s rate limiter and retry logic entirely, using a bare `urllib.request` call (`backend/main.py:743-750`) — under load this can trip Asana's 429s with no backoff.
6. **`sync_runs` has no `entity_type` column** (`supabase/conductor-schema.sql:14-23`) — a real gap for the cursor design (§3.3, §4): a hosted Edge Function needs to know "what was the cursor for *this* entity's last successful run," and today's `sync_runs` table cannot answer that when multiple adapters share a call to `sync()`. This is why §3.1 proposes a dedicated `sync_cursors` table rather than reading `sync_runs`.
7. **Silent last-writer-wins, no conflict surfacing** (§3.5): the only conflict policy implemented (`"newest"`, `backend/supabase_sync.py:212-217`) discards the losing side with no trace. Building a hosted Edge Function that writes independently of the desktop app on the same records (exactly what the target architecture proposes) makes genuine two-sided conflicts more likely than today's single-writer-usually pattern, and today's code cannot detect, let alone surface, that case.
8. **No advisory-lock or lease mechanism exists today** — the Edge Function and desktop app, wired naively per the target architecture, would both be free to run `sync_all`/push at the same time with zero coordination. §3.4 proposes a fix; nothing in the current codebase provides it.
9. **`dist/win-unpacked/resources/backend/*.py` build copies will drift silently** — they are not wired into any build step I could find beyond `.eb/manifest*.json` bookkeeping, so any code change made by A2 to `backend/asana_sync.py`/`backend/supabase_sync.py` will not be reflected there until whatever packages the Electron app runs again. Not a design blocker, but a "don't test against `dist/` and think you tested the real thing" trap for A5/A6.
10. **Multi-PAT rotation pacing is shared across ALL PATs via one `MIN_INTERVAL_S=0.45` gate** (`backend/asana_sync.py:130-155`) — reads like it's meant to pace *per-token*, and the comment says "~2.2 req/s per token" (`:135`), but the lock/sleep is global (`_req_lock`, single `_last_use` list indexed by rotating `idx`), so with N pats the effective aggregate rate is still bounded near 1/0.45s per *request*, not N×that. If A2's Edge Function is meant to run concurrently with the desktop app's own sync using a *different* PAT, there is no code-level guarantee they won't collectively still trip Asana's 150/min workspace-wide limit — that limit is per-workspace, not strictly per-token, per Asana's own docs (**UNVERIFIED: I have not fetched Asana's current rate-limit documentation in this session; this is inferred from the existing code comment's own math, not confirmed against a live API response**).

---

## HANDOFF TO A2/A3/A4

**A2 (asana/supabase/edge fn/migrations)** — the three things you must not skip:
1. `conductor.*` (the schema referenced by `docs/CONDUCTOR-SPINE.md` and both orphaned `.sql` seed files) is **not real** in this repo — only `public.conductor_records` and `public.sync_runs` are (`supabase/conductor-schema.sql`). Verify live Supabase state yourself once MCP auth is restored before writing any migration that assumes `conductor.*` exists.
2. Your idempotency key is `gid` + `modified_at` — already wired into `local_adapters()`'s `asana_tasks` adapter (`backend/supabase_sync.py:352`). Don't reinvent it; extend it. Add `sync_cursors` and `sync_leases` per §3.1/§3.4 rather than overloading `sync_runs`, which has no `entity_type` column.
3. Fix the `weight` clobber (§5.3/§6.4) in `_asana_task_upsert` before the Edge Function goes live — otherwise every hosted pull risks quietly corrupting keepa-task weighting used downstream by KPI reporting.

**A3 (keepa ASIN sources + product registry lifecycle)** — if your product-registry sync reuses `conductor_records` (the `"products"` entity type already exists in `SUPPORTED_ENTITIES`, `backend/supabase_sync.py:20`), you inherit the exact same `_upsert`/`INSERT OR REPLACE` clobber risk (§6.4) for any product column not in `_product_upsert`'s field list (`backend/supabase_sync.py:312-320`) — check that list against your full product schema before shipping, don't assume parity.

**A4 (Bernie Canvas)** — `spine.py`'s node/dataset/status/lifecycle tables are 100% local SQLite today (§1) and already covered by `tests/test_spine.py`; nothing reads from a live `conductor.*` Supabase table. If your Canvas work introduces any code path that reads node/dataset definitions from Supabase instead of `/api/spine/*`, you are the first to actually build the `conductor.*` mirror described in `docs/CONDUCTOR-SPINE.md` — coordinate with A2 first, since per item 1 above that schema does not exist yet, and don't let the two orphaned seed `.sql` files stand in for a real migration.
