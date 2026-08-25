---
tags:
  - coding
  - meeting
  - reference
  - knowledge
---

# LAW & Parker → Conductor port — conflict log & recommendations

Date: 2026-08-17 · Scope: adopt every feature from LAW (Luminize Agent Workbench) and
parker not already in Conductor. Research performed by two delegated subagents reading
both codebases; recommendations below were applied in this port.

## Parker → Conductor: no real conflicts
Parker is the skeleton Conductor was cloned from; Conductor was already a strict superset
of its routes and views. The only gap — the standalone multi-format **Ingest view** — was
ported as `Catalog Ingest` (`frontend/app.js` `renderIngest()`, nav button, files+jobs
tables) using the existing `/api/files` + `/api/jobs` endpoints.

## LAW → Conductor: three architectural conflicts, researched, resolved

### Conflict 1 — Canvas engine: LAW's @xyflow/react vs Conductor's Bernie
**Research finding:** Bernie is strictly feature-superior — 10 node types with config
modals, a real execution engine with per-node status lights + Flush output, AI
execute/suggest wired to the configured provider, SQLite named-canvas library
(load/duplicate/delete), 16 theme presets + full customizer, grid/minimap/pan/select/
context-menus/Tidy. LAW's core-canvas has 2 node types, no execution, no AI, no library —
just file-path save/load. Bernie also embodies the user's hard constraints (full-window
takeover via `body.bernie-fullscreen`, own theme environment, own flat/floating panels),
while LAW's canvas renders as "just another pane" — exactly the "shrunk into a nav
section" model the user calls a regression. Conductor is zero-build vanilla JS; React
Flow would force a bundler into the pipeline and break the smoke-test DOM contract.

**Recommendation (applied):** keep Bernie as the engine. Port LAW's canvas *features*:
`canvasNodeTypeRegistry` → `window.BernieNodeTypes` (plugins register node types via
`PluginAPI.registerCanvasNodeType`, they appear in the Bernie palette); JSON Canvas wire
format + inline editing are the remaining follow-ups (not applied — see open items).
Skip React Flow entirely.

### Conflict 2 — Split-pane workspace vs the floating-pill nav + full-window takeover
**Research finding:** LAW's PaneManager is a React tree with excellent semantics —
collapse-on-close (a closing pane that leaves one child collapses the split), 8% divider
clamp (`MIN_FRACTION = 0.08`), pointer-event resize of the adjacent pair only — but it
drops sizes on persist (`toPaneNode` re-evens splits on load), and it would make every
view a pane, breaking Conductor's full-window view takeover and the user's floating-pill
three-state sidebar.

**Recommendation (applied):** opt-in, OFF by default, max-2-pane split (chat + one other
view) layered on the existing view system — `frontend/split.js` + palette commands
("Split view with chat", "End split", "Swap orientation"). CSS-grid overlay, no DOM
moves; `showView()` routes navigation into the right pane only while split mode is
active; Bernie excluded (owns the window); per-view persisted with **sizes** in
`localStorage['conductor.split']` (fixing LAW's own gap); 8% clamp + adjacent-pair
resize + collapse-on-close ported verbatim. Divider styled in the app's flat/angular
language with nous-blue hover.

### Conflict 3 — Plugin trust model
**Research finding:** LAW's no-enforcement Obsidian model (declarative permissions,
author-by-policy) is only justified by its load path — TypeScript modules imported at
build time — plus `contextIsolation` + `sandbox` + `nodeIntegration:false`. Conductor's
main.cjs had contextIsolation + nodeIntegration:false but **no** `sandbox:true`, and its
backend holds Asana PATs and an unrestricted SSRF (`/api/bernie/proxy` accepts any
http(s) URL server-side).

**Recommendation (applied):** Obsidian trust for bundled plugins + a hard default-deny
boundary: `sandbox:true` added to webPreferences; **no generic IPC bridge** (the preload
whitelist stays fixed; LAW's `PluginAPI.ipc.invoke` is NOT ported — plugins talk to the
backend via same-origin fetch against the normal `/api/*` surface, which is the
enforcement point); `/api/bernie/proxy` remains out of any plugin allowlist; provider
keys never leave the keychain/request path.

## Open items (documented, not blocking)
- JSON Canvas wire format export/import in Bernie (LAW canvas feature — next pass).
- Inline node editing parity (Bernie config modals already cover most).
- Hub scanner currently seeds plugin cards only; extending it to apps/skills/modules/
  themes (LAW scans the workspace) is a follow-up.
- Legacy `chat.json` api_key is no longer read by the provider registry (use Settings →
  AI Chat → provider cards, which store via safeStorage).

## Verification
- Backend: `/api/chat/providers`, `/api/chat/keys`, `/api/plugins`, `/api/hub/cards`,
  `/api/hub/scan`, `/api/llama/discover` all respond; hub scan seeds/updates cards.
- Frontend: all JS `node --check` clean; full headless UI sweep (`npx electron
  ui-smoke.cjs`) passes with zero console errors (plugin runtime + core-hub load).
- CLI: `node scripts/conductor-cli.mjs doctor|health|checksums` verified.
