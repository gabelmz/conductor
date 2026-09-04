# Changelog

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
