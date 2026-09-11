# Conductor Implementation Plan

Status: active
Date: 2026-09-10
Scope: provider/model configuration, structured reports, integration foundations, `.swarm` memory utilization, and documentation.

## Outcome

Conductor should have one understandable runtime/data architecture, provider-scoped model selection, a shared structured-report contract, gallery/list report views with parameterized actions, deterministic local-first integrations, and tests that run against isolated fixtures rather than live credentials.

## Six Steps

### Step 1 - Establish the documented architecture

Create the architecture and operations templates under `docs/architecture/` and `docs/operations/`. Record current runtime paths, ownership, data stores, API boundaries, verified facts, inferred facts, and unresolved questions. Use Mermaid diagrams and never include secrets or live runtime data.

Verification: every documented path points to an existing module or is explicitly marked target state; diagrams render in Markdown preview.

### Step 2 - Define canonical contracts

Document and then implement canonical provider, model, chat-selection, structured-report, report-filter, report-action, integration-status, and sync-provenance contracts. Preserve existing provider IDs and `/api/reports` compatibility during migration.

Verification: contract fixtures serialize and validate; API responses contain stable version/type/source metadata.

### Step 3 - Fix provider-scoped model selection

Make the selected provider authoritative for model discovery and dropdown options. Support remote provider discovery, curated fallback catalogs, and local Ollama/LM Studio/llama discovery. Revalidate or clear a model when the provider changes, and reject cross-provider models before execution.

Verification: mocked tests prove that each provider returns only its own models and invalid model/provider pairs fail before an outbound request.

### Step 4 - Build the structured report system

Unify CDQ, insights, KPI, listing comparison, and similar analytical JSON outputs behind a versioned report envelope. Add typed date/date-range, latest-only, data type, source, and report-kind filters. Define explicit parse/generate, refresh, delete, replace, view/export, and rerun behavior.

Verification: isolated API tests cover filtering, latest semantics, provenance, malformed input, deletion, replacement, and rerun parameters.

### Step 5 - Deliver the report gallery and harden integrations

Add gallery/list toggling, clickable report cards, parameter editing, loading/empty/error/stale states, and mutation invalidation through the shared frontend store. In parallel, normalize integration adapter contracts and address verified API/sync defects such as retry ownership, field mapping, upsert clobbering, and missing provenance.

Verification: desktop smoke tests cover provider changes and report interactions; mocked integration tests cover retries, failures, idempotency, and conflict reporting.

### Step 6 - Operationalize `.swarm` memory and close the loop

Use `.swarm` artifacts as generated evidence, not runtime storage. Add documented deduplication, provenance, sensitive-data exclusion, retention, archive, and restore behavior. Reconcile Supabase documentation with migrations and run the full suite after focused checks pass.

Verification: `.swarm` dry-run output excludes credentials, databases, uploads, telemetry, and build artifacts; full pytest and desktop smoke suites pass or have documented pre-existing failures.

## Current Evidence And Constraints

- Backend modules live under `backend/`; frontend modules live under `frontend/`; Electron startup lives under `desktop/`.
- Provider configuration is split across `backend/chat.py`, `backend/providers.py`, `data/chat.json`, provider config/key files, environment variables, and local spine tables.
- Reports currently live in `backend/reports.py` as stored JSON blobs and the frontend report renderer in `frontend/app.js`.
- `ConductorStore` does not yet cover most report and analytical views.
- `.swarm/` contains generated graph, knowledge, evidence, run, summary, and telemetry artifacts and must not become a runtime dependency.
- The focused provider test command failed at collection from the repository root because `backend` is not on `PYTHONPATH`; use the repository's supported test invocation or set `PYTHONPATH=backend` before treating provider tests as a product failure.
- Existing worktree changes were present before this plan: `.eb-frontmatter.yaml`, `desktop/package.json`, and `desktop/afterpack-verify-python.cjs`. They are outside this plan's scope.

## Acceptance Gates

- Architecture diagrams and contracts are reviewed and linked from the project documentation.
- Provider/model selection is deterministic, provider-scoped, and covered by mocked tests.
- Reports support both gallery and list views with parameterized actions and stable provenance.
- Integrations have consistent status/error/retry semantics and isolated fixtures.
- Secrets and runtime data are excluded from documentation, diagrams, fixtures, and `.swarm` indexes.
- Focused checks pass before the full test and desktop smoke suites are run.

## Assumptions

- Python backend tests are intended to run with `backend` on the import path.
- SQLite remains the operational source of truth while external systems remain explicit adapters or sync targets.
- Plugin cards and Hugging Face/model cards remain separate from analytical reports unless the contract review changes that decision.
- No live Asana, Supabase, or model-provider credentials are required for unit and contract tests.
