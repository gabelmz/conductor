---
tags:
  - meeting
  - reference
  - coding
  - knowledge
---

# Conductor — Business Process Automation Hub

Desktop app cloned from the `parker` skeleton (Electron + FastAPI + SQLite + llama.cpp)
and rebuilt for the Business Process Automation Specialist role at Luminize.

## What it does — the four pillars

1. **Process Discovery & Design** — log manual workflows with hours/week, error rate and
   delays; Conductor computes annual cost of the status quo, a 0–100 automation score, and
   a *redesign-first vs automate-now* recommendation.
2. **Automation Infrastructure** — trigger → condition → action chains across Asana, Slack,
   Google Workspace, HubSpot, Looker Studio, Zapier and Make.com. A webhook receiver
   (`POST /webhooks/automation/{source}`) turns inbound events into handoffs.
   The canonical Luminize example ships pre-seeded:
   *Supply Chain task completed → Catalog task created with inputs pre-populated*.
   Steps run **live** when credentials exist, otherwise they execute and log as **simulated**.
3. **AI Integration** — LLM workflows (DeepSeek API or local llama.cpp): client-feedback
   categorization, meeting-transcript summarization, document parsing, action-item
   extraction, SOP drafting, email classification. Every run is recorded with provider,
   tokens and duration.
4. **Adoption, Docs & Governance** — SOPs / runbooks / training / governance docs in
   markdown, versioned on every edit, full-text searchable.

## Layout

```
conductor/
  desktop/        Electron main + preload (spawns the venv backend on a free port)
  backend/        FastAPI: main.py (routes), automation.py (BPA engine), storage.py (SQLite),
                  chat.py / llama.py (DeepSeek + local llama), asana_sync.py (Asana mirror),
                  ui.py (themes), compliance/ingestion/parsers/agents (inherited from parker)
  frontend/       vanilla JS UI (Hermes-style shell, design-token theming)
  data/           conductor.db + config JSONs (created on first run)
  models/         drop a .gguf here for local AI (optional)
  .venv/          python env (created below)
```

## Run it (desktop)

```bash
cd apps/conductor
python -m venv .venv                      # once
./.venv/Scripts/python.exe -m pip install fastapi uvicorn python-multipart requests   # once
cd desktop && npm install                 # once — electron + electron-builder
npm start                                 # launches the app window
```

First run creates `data/conductor.db` and seeds the demo automations + SOPs.

## Single-file launchers (NSIS / portable)

```bash
cd desktop
npm run dist        # → ../dist/Conductor-Setup-1.0.0.exe + Conductor-Portable-1.0.0.exe
```

- **Setup exe** — NSIS installer: pick a directory, creates desktop + start-menu shortcuts.
- **Portable exe** — true single-file launcher, extracts to a temp dir and runs, no install.
- The build bundles the whole stack: `resources/` carries the Python venv, `backend/`, `frontend/`, and `models/` next to `app.asar`.
- UI smoke test: `npm run smoke` (drives every view + settings tab in a hidden window).

## What's merged in (parker + Conductor)

The app is the full parker feature set running inside Conductor's floating-pill nav:

- **Customization suite** — full design-token editor (colors, gradients, sliders, JSON), 6 builtin themes + custom, named skins (saved to data/ui.json), live UI preview, theme JSON import/export, light/dark modes, layout persistence (panels, widths, visibility).
- **Operations** — Compliance (regulation verdicts + findings with evidence), Products (add via modal or paste `{"sku":…}` into the composer), Catalog (chunked resumable file ingestion for CSV/Keepa/CDQ/XLSX), Agents (quick actions), Action Queue (Obsidian triage import), Policy (regulation catalog).
- **Automation layer** — Process Discovery, Automations (trigger→action chains, live vs simulated execution), AI Workflows, SOPs & Runbooks, Integrations, Inbound Events.
- **Flow Canvas (Bernie merge)** — node-based workflow canvas: Trigger / Text / JSON / HTTP / AI / Script / Sheet / Drive / Flush nodes, drag-to-connect edges, end-to-end runs with per-node status, AI graph suggestions, CORS proxy for HTTP nodes, canvases persisted in SQLite. AI nodes run on Conductor's provider (no separate Gemini key needed).
- **AI** — DeepSeek API or local llama.cpp for chat and AI workflows; Asana workspace sync.

## Run the backend alone (browser)

```bash
./.venv/Scripts/python.exe -m uvicorn backend.main:app --port 8799
# open http://127.0.0.1:8799
```

## Connect real systems

- **Asana** — Settings → Asana Sync: paste a PAT. Enables live task creation in automations
  and the full workspace sync.
- **Slack / Zapier / Make** — Integrations view: paste an incoming-webhook / catch-hook URL.
  "Test" sends a real ping.
- **AI** — Settings → AI Chat: DeepSeek API key, or drop a GGUF in `models/` and pick
  Local Llama (copy `parker/llama/` + a model from parker's dist if you have them).
- **Webhooks** — `POST /webhooks/automation/{source}` with `{"event": "...", "payload": {...}}`
  triggers every enabled automation matching that source + event.

## API surface (subset)

| Area | Endpoints |
|---|---|
| Processes | `GET/POST /api/processes`, `PATCH/DELETE /api/processes/{id}` |
| Automations | `GET/POST /api/automations`, `PATCH/DELETE /api/automations/{id}`, `POST /api/automations/{id}/run` |
| Integrations | `GET /api/integrations`, `POST /api/integrations/{key}`, `POST /api/integrations/{key}/test` |
| AI | `GET /api/ai/workflows`, `POST /api/ai/run`, `GET /api/ai/runs` |
| SOPs | `GET/POST /api/sops`, `GET/PATCH/DELETE /api/sops/{id}`, `GET /api/sops/search?q=` |
| Events | `POST /webhooks/automation/{source}`, `GET /api/events` |
| Stats | `GET /api/automation/stats` |
