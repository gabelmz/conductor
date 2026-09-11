# Changelog

## v2.5.0 - 2026-09-10

### Spine State Layering

- Split the local-first spine into a package with four explicit state layers: default (factory seed), user config (existing non-secret configuration store), preferred (new: chosen chat provider/model plus a fallback target), and active (new: resolved live as user override, then preferred, then default).
- Chat's default provider/model now resolves through the spine instead of a separate hardcoded constant, fixing a real mismatch between the two.
- Chat now retries once against the configured fallback target when a provider fails outright, instead of only surfacing the error.
- Local model search (Ollama, LM Studio, Jan) now uses the existing multi-location discovery scan everywhere, and a model found that way can actually be selected and used, not just listed.

### Supabase `conductor.*` Schema

- Added the migration that creates the `conductor.*` Postgres schema and mirror tables (previously documented but never migrated), verified column-for-column against the live project.
- Added a push-only sync job from the local spine to `conductor.*`, using the existing sync lease/checkpoint contract.
- Retired two orphaned root-level seed SQL files that predated any tracked migration.

### Data Management

- Added two live, read-only external data sources (product catalog, suggested listings) to the existing Data Management table/pivot/wrangler view.

### Reliability

- Asana task creation and comments now get the same retry/backoff as every other Asana API call.
- Fixed test isolation bugs that were writing directly to the real local database on every test run.

## v2.4.5 - 2026-09-10

### Provider and Reporting Foundations

- Scoped model discovery to the selected provider and reject known cross-provider model selections before chat requests.
- Added a versioned report envelope, report filters, rerun and replacement lineage, shared report caching, and gallery/list views for saved CDQ reports.

### Release Reliability

- Added a packaging guard for the bundled Python backend and made the tag-release workflow create that environment before building.
- Corrected the desktop, API, health, update, and About version metadata to `2.4.5`.

## v2.4.0 - 2026-09-10

### Reporting and Automation

- Added provider detection to the automation flow so runs identify their source provider.
- Added new team KPI metrics to the reporting output.
- Updated the dashboard to surface the new KPI metrics.

### Scraping

- Added the ASIN scraping API script.

## v2.3.0 - 2026-09-08

### Release and Runtime Isolation

- Published updater assets through GitHub Releases so in-app update checks have downloadable artifacts.
- Moved packaged application data to the user's writable application-data directory.
- Removed the fake rollback action and clarified supported update behavior.
- Kept the Windows release as one x64 NSIS installer.

## v2.2.2 - 2026-09-08

### Updates and Portability

- Fixed GitHub release publishing so installer assets are available to the in-app updater.
- Store packaged app data in the user's writable application-data directory instead of the install folder.
- Replaced the fake rollback action with accurate release-history and updater behavior.

## v2.2.1 - 2026-09-08

### Integrations and Spine

- Added Supabase and Add New actions directly to the Integrations page.
- Added Integrations and full Spine visibility views to the Settings window.

### Desktop Release

- Reduced Windows release output to one x64 NSIS installer instead of multiple architecture and portable artifacts.

## v2.2.0 - 2026-09-08

### Asana Sync

- Added durable incremental syncing with leases, checkpoints, and an outbox fallback for Supabase outages.
- Fixed workspace task-search pagination so changed-task batches larger than 100 items are not silently truncated.
- Added background refresh and concurrency protection for local and hosted sync paths.

### Performance

- Parallelized provider health checks and settings data loading.
- Cached local model discovery to avoid repeated filesystem scans.

## v2.1.0 — 2026-09-03

### Providers

- Added NVIDIA NIM as a chat/embedding provider, defaulting to `nvidia/nemotron-3-ultra-550b-a55b` for chat and `nvidia/embed-qa-4` for embeddings.

### Desktop / Installer

- The Windows NSIS installer now builds a single universal installer covering both x64 and arm64 (previously x64-only), alongside the existing portable build.
- Corrected `/api/health`, `/api/stats`, and the updater's `current_version` to report `2.0.0` prior to this bump, and marked the update feed `private: false` now that the repo is public.

### Local Assistant

- The bundled local Llama assistant no longer ships multi-GB model weights in the installer or downloads them eagerly on startup. It now lazily fetches its default model (Dolphin 2.9 Llama3 8B, Q4_K_M) the first time it's actually used, reusing the existing Hugging Face download pipeline so progress is visible via `/api/hf/downloads`.
- Added a dedicated system prompt for the local assistant, scoped to edit-logging, quick Q&A, error explanations, and short documentation notes — kept distinct from the main cloud-backed assistant's system prompt.

### Sync, Registry & CLI Tooling

- Added a durable Asana sync runner with checkpoints and leases, with a Supabase fallback path.
- Fixed a race in sync lease acquisition: the previous read-then-write could let two runners both pass the liveness check and both write, so a lease guaranteed nothing under contention. Lease takeover is now a single atomic `INSERT ... ON CONFLICT ... WHERE` statement.
- Added ASIN-source resolution and a product registry lifecycle/UI, including Supabase seed data for file-type and status definitions.
- Added a canonical KPI definition catalog powering the KPI Studio view.
- Added a standalone `gabelmz` CLI package (vault search, AI project scaffolding, npm tooling).
- Added directory-indexing artifacts and expanded test coverage across the sync runner, product registry, ASIN sources, and provider modules.

### Fixes

- Fixed a full-window ("bernie fullscreen") takeover bug where hiding the wrong ancestor element collapsed the main canvas to 0x0 instead of just hiding the sidebar and other panes.

### Internals

- `.githooks/pre-push` rewritten in POSIX `sh` (was bash) so GUI git clients without `bash` on `PATH` (VS Code, the Claude desktop app) can run it without failing every push; `.gitattributes` now forces LF line endings under `.githooks/` so CRLF checkouts can't break the shebang again.
- Release pushes to `main` now require a `v*` tag and a `CHANGELOG.md` entry at HEAD mentioning the released version, authored by a dispatched subagent rather than hand-written in chat.
- `.gitignore` now excludes local AI-tool caches (`.claude/`, `.opencode/`, `.swarm/`, `.eb/`) and a stray `local-tree.md` debug dump.
