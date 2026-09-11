# Conductor Execution Plan

Status: in progress
Reviewed: 2026-09-10

## Scope confirmed from the repository

1. Make `/api/chat/models` provider-scoped by default while keeping the
   `models` response field and an explicit all-providers compatibility mode.
2. Preserve a chat selection only when it belongs to the selected provider;
   reject known cross-provider models before an outbound chat request.
3. Normalize saved CDQ reports into a versioned response envelope without
   migrating the existing SQLite table or breaking legacy fields.
4. Add report filters, rerun/replace actions, a gallery/list toggle, and shared
   frontend report caching.
5. Cover these behaviors with isolated FastAPI tests; no test requires live
   provider, Asana, Supabase, or MCP credentials.

## Explicitly deferred

- Persisting insights, KPI, listing comparison, or other transient analytical
  outputs as reports. Those features do not yet share a storage contract.
- Changing external-adapter retry, Supabase schema, or `.swarm` cleanup logic.
  The committed documentation records their evidence and verification gates,
  but no live-system claim can be made without separate implementation and
  credentials.
- Replacing existing provider key storage. This pass exposes no secret values.

## Delivery order

1. Add provider catalog/validation helpers, then route model discovery and chat
   execution through them.
2. Add a report-envelope boundary and filter/action endpoints over the current
   `reports` table.
3. Move report list fetching and invalidation into `ConductorData`, then make
   gallery and list presentations consume that one source.
4. Add focused tests, run syntax checks and the focused pytest set, then run the
   wider suite if the focused checks are clean.

## Acceptance criteria

- `GET /api/chat/models?provider=<id>` only returns records whose provider is
  `<id>`; the configured provider is used when omitted.
- A model discovered for one provider cannot be sent to another provider.
- Each saved report response carries `schemaVersion`, `type`, `source`,
  `parameters`, `summary`, and legacy fields (`kind`, `meta`, `created_at`).
- List filtering, latest-only selection, rerun, replacement lineage, deletion,
  and malformed request handling are covered without touching `data/`.
- The report view has a useful gallery and a compact table, and mutations
  invalidate the shared cache.
