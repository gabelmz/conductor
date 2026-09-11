# Provider And Data Integrations

Status: template for implementation documentation
Owner: TBD
Last reviewed: 2026-09-10

## Configuration Ownership

| Configuration | Current location | Target ownership | Sensitive |
| --- | --- | --- | --- |
| Chat selection | `data/chat.json` | chat settings service | model/provider IDs only |
| Provider metadata | `backend/providers.py` and provider config | provider registry | no |
| Provider keys | provider key storage / environment | secret boundary | yes |
| Asana settings | `data/asana.json` and environment fallback | Asana adapter | yes |
| Supabase settings | `data/supabase.json` when configured | Supabase adapter | yes |
| MCP registry | `data/mcp.json` | MCP adapter registry | possibly |

Never document or commit credential values. Runtime data under `data/` is not a fixture source.

## Provider Resolution

Document the final order for request key, secure stored key, environment key, and local-provider sentinel. Model discovery must not require exposing a key to the frontend. Discovery failures must return source, timestamp, and retryability metadata.

## Local-First Data Flow

SQLite is the operational source of truth. External systems are explicit adapters and sync targets. Each sync operation must report direction, dataset, counts, timestamps, errors, and conflict/provenance state.

## HTTP And Retry Rules

Document per-adapter timeout, retryable status codes, backoff, rate-limit handling, idempotency key, and maximum attempts. Do not duplicate raw HTTP behavior in route handlers.

## Supabase Verification Gate

Until authenticated inspection is completed, treat `public.conductor_records` and `public.sync_runs` as the only checked-in schema truth. The `conductor.*` objects described by other documentation and SQL files remain unverified.

## Known Risks To Resolve

- Provider settings are split across multiple stores.
- Secure storage has an environment-dependent fallback.
- Model discovery and settings dropdowns are not consistently provider-scoped.
- Asana mutation paths need consistent retry ownership.
- Sync upserts can clobber fields omitted from incoming payloads.
- Supabase sync currently lacks complete conflict/provenance semantics.

## Recovery Procedures

Document how to reset local fixtures, invalidate stale model catalogs, retry failed syncs, restore archived `.swarm` evidence, and roll back additive schema changes. Include commands only after they are verified in the repository.

## Test Matrix

| Adapter | Unit fixture | Mock HTTP | Failure cases | Live test allowed |
| --- | --- | --- | --- | --- |
| Provider models | yes | yes | timeout, 401, malformed catalog | no |
| Asana | yes | yes | 429, 5xx, auth, partial page | no by default |
| Supabase | yes | yes | conflict, timeout, schema mismatch | gated |
| MCP | yes | yes | unavailable server, invalid response | no |
