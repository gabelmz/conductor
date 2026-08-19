"""Conductor — Business Process Automation backend.

Covers the four pillars of the BPA Specialist role:

  1. Process Discovery & Design  — /api/processes            manual workflow intake,
     ROI quantification (annual cost, automation score), and
     redesign-vs-automate recommendations.
  2. Automation Infrastructure   — /api/automations           trigger → condition →
     action chains across Asana / Google Workspace / HubSpot /
     Looker Studio / Zapier / Make.com; /api/integrations connector
     registry; /webhooks/automation/{source} inbound event receiver.
  3. AI Integration              — /api/ai/*                  LLM workflows:
     feedback categorization, transcript summarization, document parsing,
     action-item extraction, SOP drafting, email classification.
  4. Adoption, Docs, Governance  — /api/sops                  SOPs / runbooks /
     training / governance markdown docs with versioning.

Execution is honest about what is real: actions run live when the required
credentials exist (Asana PAT, AI provider), otherwise they
are executed as *simulated* steps and logged as such.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

from fastapi import APIRouter, HTTPException, Request

import storage
from storage import DATA_DIR, now_iso

router = APIRouter(tags=["automation"])

HOURLY_RATE = 45.0  # blended fully-loaded cost per manual hour (USD)
WEEKS_PER_YEAR = 52

# ---------------------------------------------------------------------------
# Tables (created idempotently; independent from storage.init_db())
# ---------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS processes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    department TEXT DEFAULT '',
    owner TEXT DEFAULT '',
    trigger_desc TEXT DEFAULT '',
    current_process TEXT DEFAULT '',
    manual_hours_week REAL DEFAULT 0,
    error_rate REAL DEFAULT 0,
    delay_hours REAL DEFAULT 0,
    pain_points TEXT DEFAULT '',
    status TEXT DEFAULT 'discovered',
    annual_cost REAL DEFAULT 0,
    automation_score INTEGER DEFAULT 0,
    recommendation TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS automations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    trigger_source TEXT DEFAULT 'manual',
    trigger_event TEXT DEFAULT '',
    conditions TEXT DEFAULT '[]',
    actions TEXT DEFAULT '[]',
    enabled INTEGER DEFAULT 1,
    run_count INTEGER DEFAULT 0,
    last_run_at TEXT DEFAULT '',
    last_status TEXT DEFAULT '',
    last_log TEXT DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS integration_settings (
    key TEXT PRIMARY KEY,
    name TEXT DEFAULT '',
    kind TEXT DEFAULT 'api',
    status TEXT DEFAULT 'unconfigured',
    config TEXT DEFAULT '{}',
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sops (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    category TEXT DEFAULT 'sop',
    body TEXT DEFAULT '',
    version INTEGER DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ai_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow TEXT NOT NULL,
    input_preview TEXT DEFAULT '',
    output TEXT DEFAULT '',
    provider TEXT DEFAULT '',
    model TEXT DEFAULT '',
    tokens_in INTEGER DEFAULT 0,
    tokens_out INTEGER DEFAULT 0,
    duration_ms REAL DEFAULT 0,
    status TEXT DEFAULT 'done',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT DEFAULT '',
    type TEXT DEFAULT '',
    payload TEXT DEFAULT '{}',
    created_at TEXT NOT NULL
);
"""

PROCESS_STATUSES = ("discovered", "scoping", "building", "shipped", "adopted", "deferred")
ACTION_TYPES = ("asana_create_task", "sheets_append", "gmail_send",
                "hubspot_update", "webhook_out", "ai_run", "log_event")
TRIGGER_SOURCES = ("asana", "webhook", "sheets", "forms", "schedule", "manual")
CONDITION_OPS = ("eq", "neq", "contains", "exists")

SECRET_KEY_PARTS = ("token", "secret", "password", "api_key", "apikey", "pat")

# ---------------------------------------------------------------------------
# Integrations registry (static catalog; live config lives in the DB)
# ---------------------------------------------------------------------------
INTEGRATIONS: list[dict[str, Any]] = [
    {"key": "asana", "name": "Asana", "kind": "api",
     "desc": "Project & task sync — triggers on task completion, creates tasks with pre-populated inputs.",
     "fields": [{"key": "pat", "label": "Personal Access Token", "type": "secret", "placeholder": "2/…"}]},
    {"key": "spapi", "name": "Amazon SP-API", "kind": "api",
     "desc": "Product type definitions (getDefinitionsProductType) → Product Pipelines. LWA auth: refresh_token + client_id + client_secret (or a direct access_token).",
     "fields": [
         {"key": "refresh_token", "label": "Refresh Token", "type": "secret", "placeholder": "LWA refresh_token"},
         {"key": "client_id", "label": "Client ID", "type": "secret", "placeholder": "LWA client_id"},
         {"key": "client_secret", "label": "Client Secret", "type": "secret", "placeholder": "LWA client_secret"},
         {"key": "access_token", "label": "Direct Access Token (optional)", "type": "secret", "placeholder": "x-amz-access-token"},
         {"key": "region", "label": "Region", "type": "text", "placeholder": "na | eu | fe"},
     ]},
    {"key": "google_sheets", "name": "Google Sheets", "kind": "connector",
     "desc": "Append rows, log automation runs, keep data in sync with the spreadsheet layer.",
     "fields": [{"key": "sheet_id", "label": "Spreadsheet ID", "type": "text", "placeholder": "1A2b3C…"}]},
    {"key": "google_docs", "name": "Google Docs", "kind": "connector",
     "desc": "Generate documents from templates (reports, onboarding packets).",
     "fields": []},
    {"key": "google_forms", "name": "Google Forms", "kind": "connector",
     "desc": "Intake forms — responses become automation trigger events.",
     "fields": []},
    {"key": "gmail", "name": "Gmail", "kind": "connector",
     "desc": "Send templated emails from automations (onboarding, notifications).",
     "fields": []},
    {"key": "hubspot", "name": "HubSpot", "kind": "api",
     "desc": "CRM sync — update contacts/deals when lifecycle events fire.",
     "fields": [{"key": "api_key", "label": "Private App Token", "type": "secret", "placeholder": "pat-…"}]},
    {"key": "looker_studio", "name": "Looker Studio", "kind": "connector",
     "desc": "Reporting pipelines — refresh/export data for dashboards.",
     "fields": [{"key": "report_url", "label": "Report URL", "type": "url", "placeholder": "https://lookerstudio.google.com/…"}]},
    {"key": "zapier", "name": "Zapier", "kind": "nocode",
     "desc": "No-code handoffs — push events into Zapier catch hooks.",
     "fields": [{"key": "webhook_url", "label": "Catch Hook URL", "type": "url", "placeholder": "https://hooks.zapier.com/hooks/catch/…"}]},
    {"key": "make", "name": "Make.com", "kind": "nocode",
     "desc": "No-code scenarios — trigger Make scenarios from Conductor events.",
     "fields": [{"key": "webhook_url", "label": "Scenario Webhook URL", "type": "url", "placeholder": "https://hook.eu1.make.com/…"}]},
    {"key": "webhooks", "name": "Inbound Webhooks", "kind": "webhook",
     "desc": "Generic event intake — POST JSON to /webhooks/automation/{source} to trigger automations.",
     "fields": []},
]

# ---------------------------------------------------------------------------
# AI workflow catalog
# ---------------------------------------------------------------------------
AI_WORKFLOWS: dict[str, dict[str, str]] = {
    "categorize_feedback": {
        "title": "Categorize client feedback",
        "desc": "Bucket raw client feedback into category, sentiment, priority and a recommended next action.",
        "prompt": (
            "You are a business-process analyst at an Amazon growth agency managing 80+ brands. "
            "Categorize the client feedback below. Respond ONLY with compact JSON: "
            '{"category": "<catalog|advertising|creative|logistics|finance|operations|other>", '
            '"sentiment": "positive|neutral|negative", "priority": "low|medium|high", '
            '"action": "<one-line recommended next step>"}.\n\n'
            "Feedback:\n\"\"\"{input}\"\"\""
        ),
    },
    "summarize_transcript": {
        "title": "Summarize meeting transcript",
        "desc": "Turn a raw meeting transcript into decisions, action items with owners, and open questions.",
        "prompt": (
            "Summarize the meeting transcript below in concise markdown with four sections: "
            "**TL;DR**, **Decisions**, **Action items** (each as `- [ ] task — @owner (due date)`), "
            "and **Open questions**. Skip pleasantries.\n\n"
            "Transcript:\n\"\"\"{input}\"\"\""
        ),
    },
    "parse_document": {
        "title": "Parse & extract from document",
        "desc": "Extract structured entities (dates, amounts, obligations, contacts) from a document.",
        "prompt": (
            "Extract structured data from the document below. Respond ONLY with JSON: "
            '{"entities": [], "dates": [], "amounts": [], "obligations": [], "contacts": []}. '
            "Omit empty arrays.\n\nDocument:\n\"\"\"{input}\"\"\""
        ),
    },
    "extract_actions": {
        "title": "Extract action items",
        "desc": "Pull a to-do list out of any free-form text (email, note, ticket).",
        "prompt": (
            "Extract every action item from the text below. Respond ONLY with a JSON array of "
            '{"task": "...", "owner": "name or null", "due": "date or null"} objects. '
            "If there are none, respond with an empty array [].\n\nText:\n\"\"\"{input}\"\"\""
        ),
    },
    "draft_sop": {
        "title": "Draft an SOP",
        "desc": "Generate a markdown SOP from rough process notes.",
        "prompt": (
            "Write a concise SOP in markdown from the process notes below. Sections: "
            "**Purpose**, **Scope**, **Steps** (numbered), **Guardrails & validation**, "
            "**Owner & review cadence**. Keep it tight and operational.\n\n"
            "Process notes:\n\"\"\"{input}\"\"\""
        ),
    },
    "classify_email": {
        "title": "Classify support email",
        "desc": "Classify a support email into intent, urgency and a suggested reply.",
        "prompt": (
            "Classify the support email below. Respond ONLY with JSON: "
            '{"intent": "<short label>", "urgency": "low|medium|high", '
            '"suggested_response": "<2-3 sentence draft reply>"}.\n\n'
            "Email:\n\"\"\"{input}\"\"\""
        ),
    },
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _rows(sql: str, params: tuple = ()) -> list[dict]:
    out = []
    for r in storage._conn().execute(sql, params).fetchall():
        d = dict(r)
        for k in ("conditions", "actions", "payload"):
            if k in d and isinstance(d[k], str):
                try:
                    d[k] = json.loads(d[k])
                except Exception:
                    pass
        out.append(d)
    return out


def _row(sql: str, params: tuple = ()) -> dict | None:
    rows = _rows(sql, params)
    return rows[0] if rows else None


def _mask(config: dict) -> dict:
    out = {}
    for k, v in config.items():
        if any(s in k.lower() for s in SECRET_KEY_PARTS) and v:
            out[k] = f"••••••{str(v)[-4:]}" if len(str(v)) > 4 else "••••"
        else:
            out[k] = v
    return out


def _compute_process(name: str, manual_hours_week: float, error_rate: float,
                     delay_hours: float, pain_points: str, current_process: str) -> tuple[float, int, str]:
    annual_cost = round(manual_hours_week * WEEKS_PER_YEAR * HOURLY_RATE, 2)
    score = 50 + min(30, manual_hours_week * 3) + min(15, error_rate) + (10 if delay_hours > 0 else 0)
    score = max(0, min(100, round(score)))
    low = (pain_points + " " + current_process).lower()
    if error_rate >= 20 or any(w in low for w in ("redesign", "rework", "double-entry", "double entry")):
        rec = "Redesign the process first, then automate — automation would harden the current waste."
    elif manual_hours_week >= 5:
        rec = "Prime automation candidate — build an MVP now, then iterate."
    elif manual_hours_week >= 2:
        rec = "Good candidate — scope a lean MVP after a 30-min process walkthrough."
    else:
        rec = "Low volume — consider redesigning or deferring; cheap enough to run manually."
    return annual_cost, score, rec


def _get_integration_config(key: str) -> dict:
    row = _row("SELECT config FROM integration_settings WHERE key=?", (key,))
    try:
        return json.loads(row["config"]) if row and row["config"] else {}
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Action execution engine (live where credentials exist, else simulated)
# ---------------------------------------------------------------------------
def _render(template: str, ctx: dict) -> str:
    """Tiny template renderer: {field} placeholders pulled from ctx."""
    out = str(template)
    for k, v in ctx.items():
        if isinstance(v, (str, int, float, bool)):
            out = out.replace("{" + k + "}", str(v))
    return out


def _asana_client():
    """Return (headers, base_url) for live Asana calls, or (None, None)."""
    try:
        import asana_sync
        cfg = asana_sync.get_config()
        pat = cfg.get("pat") or ""
        if pat:
            return {"Authorization": f"Bearer {pat}", "Accept": "application/json"}, asana_sync.BASE_URL
    except Exception:
        pass
    return None, None


def _asana_project_gid(target: str) -> str | None:
    """Resolve a project name/gid via the local Asana mirror."""
    gid = str(target or "").strip()
    if gid.startswith("120") and len(gid) >= 12:  # looks like a gid already
        return gid
    for p in storage.list_asana_projects(include_archived=True):
        if p.get("name", "").lower() == gid.lower():
            return p["gid"]
    return None


def execute_action(action: dict, ctx: dict) -> dict:
    """Execute one action step. Returns {type, executed: live|simulated, detail, ok}."""
    atype = str(action.get("type") or "")
    payload = action.get("payload") or {}
    target = str(action.get("target") or "")

    if atype == "log_event":
        storage._conn().execute(
            "INSERT INTO events (source, type, payload, created_at) VALUES (?,?,?,?)",
            (ctx.get("source", "automation"), "action_log",
             json.dumps({"action": atype, "ctx_keys": sorted(ctx.keys())}), now_iso()),
        )
        storage._conn().commit()
        return {"type": atype, "executed": "live", "ok": True, "detail": "Event logged."}

    if atype == "asana_create_task":
        name_tpl = payload.get("name") or payload.get("name_template") or "Automated task"
        name = _render(name_tpl, ctx)
        notes = _render(payload.get("notes") or payload.get("notes_template") or "", ctx)
        headers, base = _asana_client()
        project_gid = _asana_project_gid(target)
        if headers and project_gid:
            body = {"data": {"name": name[:1200], "notes": notes[:100000], "projects": [project_gid]}}
            if payload.get("assignee"):
                body["data"]["assignee"] = str(payload["assignee"])
            if payload.get("due_on"):
                body["data"]["due_on"] = str(payload["due_on"])
            req = urllib.request.Request(f"{base}/tasks", data=json.dumps(body).encode(),
                                         headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    data = json.loads(r.read().decode())
                link = (data.get("data") or {}).get("permalink_url", "")
                return {"type": atype, "executed": "live", "ok": True,
                        "detail": f"Created Asana task '{name}'{(' — ' + link) if link else ''}."}
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")[:300]
                return {"type": atype, "executed": "live", "ok": False,
                        "detail": f"Asana API {exc.code}: {detail}"}
            except Exception as exc:
                return {"type": atype, "executed": "live", "ok": False, "detail": str(exc)}
        if not headers:
            return {"type": atype, "executed": "simulated", "ok": True,
                    "detail": f"No Asana PAT — would create task '{name}' in project '{target or '?'}'."}
        return {"type": atype, "executed": "simulated", "ok": True,
                "detail": f"Project '{target}' not found in local Asana mirror — run an Asana sync first, or paste the project GID."}

    if atype == "ai_run":
        workflow = payload.get("workflow") or payload.get("name") or ""
        wf = AI_WORKFLOWS.get(workflow)
        if not wf:
            return {"type": atype, "executed": "live", "ok": False,
                    "detail": f"Unknown AI workflow '{workflow}'."}
        source = payload.get("input_field") or payload.get("input") or ""
        text = ctx.get(source) if source and source in ctx else (payload.get("input_text") or "")
        if not text:
            text = json.dumps(ctx, default=str)[:4000]
        try:
            result = run_ai(workflow, str(text)[:20000], record=True)
            return {"type": atype, "executed": result["provider"] != "none", "ok": True,
                    "detail": f"AI '{workflow}' ({result['provider']}) → {result['output'][:120]}"}
        except HTTPException as exc:
            return {"type": atype, "executed": "simulated", "ok": True,
                    "detail": f"AI not available: {exc.detail}"}

    if atype == "webhook_out":
        url = payload.get("url") or ""
        if not url:
            return {"type": atype, "executed": "simulated", "ok": True, "detail": "No target URL — nothing sent."}
        req = urllib.request.Request(url, data=json.dumps(ctx, default=str).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return {"type": atype, "executed": "live", "ok": r.status < 300,
                        "detail": f"POSTed event to {url} → HTTP {r.status}."}
        except Exception as exc:
            return {"type": atype, "executed": "live", "ok": False, "detail": str(exc)}

    if atype in ("sheets_append", "gmail_send", "hubspot_update"):
        friendly = {"sheets_append": "Google Sheets", "gmail_send": "Gmail", "hubspot_update": "HubSpot"}[atype]
        return {"type": atype, "executed": "simulated", "ok": True,
                "detail": f"{friendly} not wired in this MVP — connect the integration to run live. Payload keys: {sorted(payload.keys())}."}

    return {"type": atype, "executed": "simulated", "ok": False, "detail": f"Unknown action type '{atype}'."}


def _eval_conditions(conditions: list, ctx: dict) -> bool:
    if not conditions:
        return True
    for c in conditions:
        field = str(c.get("field") or "")
        op = c.get("op") or "eq"
        want = c.get("value")
        have = ctx.get(field)
        if op == "exists":
            if (have is not None) != bool(want):
                return False
            continue
        if op == "eq" and str(have) != str(want):
            return False
        if op == "neq" and str(have) == str(want):
            return False
        if op == "contains":
            if have is None or str(want).lower() not in str(have).lower():
                return False
    return True


def run_automation(a: dict, event_ctx: dict | None = None) -> dict:
    """Evaluate conditions, execute every action, record the run on the row."""
    ctx = dict(event_ctx or {})
    ctx.setdefault("source", a.get("trigger_source", "manual"))
    ctx.setdefault("event", a.get("trigger_event", ""))
    ctx.setdefault("automation", a.get("name", ""))

    conditions = a.get("conditions") or []
    if not isinstance(conditions, list):
        conditions = []
    actions = a.get("actions") or []
    if not isinstance(actions, list):
        actions = []

    results: list[dict] = []
    if not _eval_conditions(conditions, ctx):
        _record_run(a["id"], "skipped", f"Conditions not met for event {ctx.get('event') or ctx.get('source')}.")
        return {"automation": a["name"], "status": "skipped", "results": []}

    for action in actions:
        try:
            results.append(execute_action(action, ctx))
        except Exception as exc:
            results.append({"type": action.get("type"), "executed": "live", "ok": False, "detail": str(exc)})

    live = sum(1 for r in results if r.get("executed") == "live" and r.get("ok"))
    sim = sum(1 for r in results if r.get("executed") == "simulated")
    failed = sum(1 for r in results if not r.get("ok"))
    status = "error" if failed else ("success" if live and not sim else "partial" if live else "simulated")
    log = "; ".join(r.get("detail", "")[:140] for r in results)[:900]
    _record_run(a["id"], status, log)
    return {"automation": a["name"], "status": status,
            "live_steps": live, "simulated_steps": sim, "failed_steps": failed,
            "log": log, "results": results}


def _record_run(auto_id: int, status: str, log: str) -> None:
    conn = storage._conn()
    conn.execute(
        "UPDATE automations SET run_count = COALESCE(run_count,0)+1, last_run_at=?, last_status=?, last_log=? WHERE id=?",
        (now_iso(), status, log, auto_id),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# AI runner (DeepSeek cloud API or local llama.cpp — same engines as chat.py)
# ---------------------------------------------------------------------------
def _llama_complete(messages: list[dict], cfg: dict) -> str:
    import llama
    port = llama._find_running_server()
    if port is None:
        llama.start_server({"model": cfg["llama_model"], "ctx": cfg["llama_ctx"], "port": cfg["llama_port"]})
        port = llama._find_running_server()
        if port is None:
            raise HTTPException(500, "Local llama server failed to start — check Settings → AI Chat.")
    from pathlib import Path
    model_name = Path(llama.resolve_model(cfg["llama_model"])).name
    chunks: list[str] = []
    for delta in llama.stream_chat(messages, model_name, port=port, max_tokens=1600, temperature=0.4):
        chunks.append(delta)
    return "".join(chunks)


def _deepseek_complete(messages: list[dict], cfg: dict) -> tuple[str, dict]:
    payload = {"model": cfg["model"], "messages": messages, "stream": False,
               "temperature": 0.4, "max_tokens": 1600}
    req = urllib.request.Request(
        f"{cfg['base_url']}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {cfg['api_key']}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=240) as resp:
        obj = json.loads(resp.read().decode("utf-8"))
    content = (obj.get("choices") or [{}])[0].get("message", {}).get("content", "")
    return content, obj.get("usage") or {}


def run_ai(workflow: str, input_text: str, record: bool = True) -> dict:
    """Run an AI workflow with the configured provider. Raises 400 when no provider."""
    wf = AI_WORKFLOWS.get(workflow)
    if not wf:
        raise HTTPException(404, f"Unknown workflow '{workflow}'. Available: {', '.join(AI_WORKFLOWS)}")
    if not input_text.strip():
        raise HTTPException(400, "Input text is required for this workflow.")

    import chat
    cfg = chat._load_config()
    provider = cfg["provider"]
    if provider != "llama" and not cfg["api_key"]:
        raise HTTPException(400, "No AI provider configured — open Settings → AI Chat and add an API key, or switch to a local Llama model.")

    messages = [
        {"role": "system", "content": "You are Salmon, Conductor's automation copilot. Follow the workflow instructions exactly; output format only."},
        {"role": "user", "content": wf["prompt"].replace("{input}", input_text)},
    ]

    started = time.perf_counter()
    tokens_in = tokens_out = 0
    try:
        if provider == "llama":
            output = _llama_complete(messages, cfg)
            model = cfg["llama_model"]
            usage_obj = {}
        else:
            output, usage_obj = _deepseek_complete(messages, cfg)
            model = cfg["model"]
        status = "done"
        tokens_in = int(usage_obj.get("prompt_tokens") or 0)
        tokens_out = int(usage_obj.get("completion_tokens") or 0)
    except urllib.error.HTTPError as exc:
        output = f"Provider error {exc.code}: {exc.read().decode('utf-8', errors='replace')[:300]}"
        model, status = cfg["model"], "error"
    except Exception as exc:
        output = f"{type(exc).__name__}: {exc}"
        model, status = cfg["model"], "error"
    duration_ms = (time.perf_counter() - started) * 1000

    if tokens_in or tokens_out:
        try:
            import usage
            usage.record(input_tokens=tokens_in, output_tokens=tokens_out)
        except Exception:
            pass

    run_id = None
    if record:
        conn = storage._conn()
        cur = conn.execute(
            "INSERT INTO ai_runs (workflow, input_preview, output, provider, model, tokens_in, tokens_out, duration_ms, status, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (workflow, input_text[:400], output[:50000], provider, model, tokens_in, tokens_out,
             round(duration_ms, 1), status, now_iso()),
        )
        conn.commit()
        run_id = cur.lastrowid

    return {"id": run_id, "workflow": workflow, "title": wf["title"], "output": output,
            "provider": provider, "model": model, "status": status,
            "tokens_in": tokens_in, "tokens_out": tokens_out, "duration_ms": round(duration_ms, 1)}


# ---------------------------------------------------------------------------
# Seed data (first run only)
# ---------------------------------------------------------------------------
def seed() -> None:
    conn = storage._conn()
    if conn.execute("SELECT COUNT(*) AS n FROM integration_settings").fetchone()["n"] == 0:
        for it in INTEGRATIONS:
            conn.execute(
                "INSERT INTO integration_settings (key, name, kind, status, config, updated_at) VALUES (?,?,?,?,?,?)",
                (it["key"], it["name"], it["kind"], "unconfigured", "{}", now_iso()),
            )
        conn.commit()

    if conn.execute("SELECT COUNT(*) AS n FROM automations").fetchone()["n"] == 0:
        seeds = [
            {
                "name": "Supply Chain → Catalog handoff",
                "description": "A completed Supply Chain task triggers a Catalog notification with all required inputs pre-populated. (The canonical Luminize handoff.)",
                "trigger_source": "asana", "trigger_event": "task_completed",
                "conditions": [{"field": "project", "op": "contains", "value": "Supply Chain"}],
                "actions": [
                    {"type": "asana_create_task", "target": "Catalog Ops",
                     "payload": {"name": "Catalog: {task_name} ready for intake",
                                 "notes": "Auto-created by Conductor.\nSupply Chain task completed: {task_name}\nLink: {task_url}\n\nAll required inputs are pre-populated below."}},
                    {"type": "log_event"},
                ],
            },
            {
                "name": "Client feedback triage",
                "description": "Inbound client feedback is AI-categorized and routed to the right team automatically.",
                "trigger_source": "webhook", "trigger_event": "feedback_received",
                "conditions": [],
                "actions": [
                    {"type": "ai_run", "payload": {"workflow": "categorize_feedback", "input_field": "feedback"}},
                    {"type": "asana_create_task", "target": "Brand Ops",
                     "payload": {"name": "Feedback triage: {feedback}", "notes": "AI categorization result attached."}},
                    {"type": "log_event"},
                ],
            },
            {
                "name": "New-hire onboarding kickoff",
                "description": "A form submission triggers the standard onboarding task list plus a welcome email.",
                "trigger_source": "forms", "trigger_event": "form_submitted",
                "conditions": [{"field": "form", "op": "contains", "value": "onboarding"}],
                "actions": [
                    {"type": "asana_create_task", "target": "People Ops",
                     "payload": {"name": "Onboard {name}", "notes": "New hire intake: {name} ({email}). Follow the HR onboarding runbook."}},
                    {"type": "gmail_send", "payload": {"to": "{email}", "subject": "Welcome to Luminize!", "body_template": "Hi {name}…"}},
                    {"type": "log_event"},
                ],
            },
        ]
        for s in seeds:
            conn.execute(
                "INSERT INTO automations (name, description, trigger_source, trigger_event, conditions, actions, enabled, created_at) "
                "VALUES (?,?,?,?,?,?,1,?)",
                (s["name"], s["description"], s["trigger_source"], s["trigger_event"],
                 json.dumps(s["conditions"]), json.dumps(s["actions"]), now_iso()),
            )
        conn.commit()

    if conn.execute("SELECT COUNT(*) AS n FROM sops").fetchone()["n"] == 0:
        sops = [
            {
                "title": "Runbook — Testing an automation end-to-end",
                "category": "runbook",
                "body": (
                    "# Testing an automation end-to-end\n\n"
                    "## Purpose\nProve a Conductor automation works before enabling it in production.\n\n"
                    "## Steps\n"
                    "1. Open **Automations** and pick the automation under test.\n"
                    "2. Confirm the trigger source matches where the real event will come from (Asana, webhook, form).\n"
                    "3. Click **Run now** and paste a realistic sample payload (same shape as production).\n"
                    "4. Check each step's badge: `live` means it executed for real, `simulated` means credentials are missing or the target is not wired.\n"
                    "5. Verify the output in the target system (task created, message posted, row appended).\n"
                    "6. Toggle **Enabled** on only after a successful live run.\n\n"
                    "## Guardrails\n"
                    "- Never test against production data with `live` actions until step 5 has passed once.\n"
                    "- Re-run monthly after any trigger or action change.\n\n"
                    "## Owner\nBusiness Process Automation Specialist · review every 30 days."
                ),
            },
            {
                "title": "SOP template — <process name>",
                "category": "sop",
                "body": (
                    "# <Process name>\n\n"
                    "## Purpose\nWhat outcome this process produces and why it exists.\n\n"
                    "## Scope\nWho runs it, what inputs it consumes, what outputs it produces.\n\n"
                    "## Steps\n1. …\n2. …\n\n"
                    "## Guardrails & validation\nHow we error-proof the inputs and what exceptions look like.\n\n"
                    "## Owner & review cadence\nOwner: … · Reviewed: monthly."
                ),
            },
        ]
        for s in sops:
            conn.execute(
                "INSERT INTO sops (title, category, body, version, created_at, updated_at) VALUES (?,?,?,1,?,?)",
                (s["title"], s["category"], s["body"], now_iso(), now_iso()),
            )
        conn.commit()


def init() -> None:
    conn = storage._conn()
    conn.executescript(SCHEMA)
    conn.commit()
    seed()


init()

# ---------------------------------------------------------------------------
# Endpoints — 1. Process Discovery & Design
# ---------------------------------------------------------------------------
@router.get("/api/processes")
def list_processes():
    return _rows("SELECT * FROM processes ORDER BY automation_score DESC, id DESC")


@router.post("/api/processes", status_code=201)
def create_process(body: dict):
    name = str(body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "name is required")
    try:
        hours = max(0.0, float(body.get("manual_hours_week") or 0))
        err = max(0.0, min(100.0, float(body.get("error_rate") or 0)))
        delay = max(0.0, float(body.get("delay_hours") or 0))
    except (TypeError, ValueError):
        raise HTTPException(400, "manual_hours_week, error_rate and delay_hours must be numbers")
    annual_cost, score, rec = _compute_process(
        name, hours, err, delay,
        str(body.get("pain_points") or ""), str(body.get("current_process") or ""),
    )
    ts = now_iso()
    conn = storage._conn()
    cur = conn.execute(
        "INSERT INTO processes (name, department, owner, trigger_desc, current_process, manual_hours_week, "
        "error_rate, delay_hours, pain_points, status, annual_cost, automation_score, recommendation, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (name, str(body.get("department") or ""), str(body.get("owner") or ""),
         str(body.get("trigger_desc") or ""), str(body.get("current_process") or ""),
         hours, err, delay, str(body.get("pain_points") or ""),
         str(body.get("status") or "discovered"), annual_cost, score, rec, ts, ts),
    )
    conn.commit()
    return get_process(cur.lastrowid)


@router.get("/api/processes/{process_id}")
def get_process(process_id: int):
    p = _row("SELECT * FROM processes WHERE id=?", (process_id,))
    if not p:
        raise HTTPException(404, "Process not found")
    return p


@router.patch("/api/processes/{process_id}")
def update_process(process_id: int, body: dict):
    p = _row("SELECT * FROM processes WHERE id=?", (process_id,))
    if not p:
        raise HTTPException(404, "Process not found")
    allowed = {"name", "department", "owner", "trigger_desc", "current_process", "pain_points",
               "manual_hours_week", "error_rate", "delay_hours", "status"}
    upd = {k: v for k, v in body.items() if k in allowed}
    if "status" in upd and upd["status"] not in PROCESS_STATUSES:
        raise HTTPException(400, f"status must be one of {', '.join(PROCESS_STATUSES)}")
    merged = {**p, **upd}
    annual_cost, score, rec = _compute_process(
        str(merged["name"]), float(merged["manual_hours_week"] or 0),
        float(merged["error_rate"] or 0), float(merged["delay_hours"] or 0),
        str(merged["pain_points"] or ""), str(merged["current_process"] or ""),
    )
    conn = storage._conn()
    sets, vals = [], []
    for k, v in upd.items():
        sets.append(f"{k}=?")
        vals.append(v)
    sets += ["annual_cost=?", "automation_score=?", "recommendation=?", "updated_at=?"]
    vals += [annual_cost, score, rec, now_iso(), process_id]
    conn.execute(f"UPDATE processes SET {', '.join(sets)} WHERE id=?", vals)
    conn.commit()
    return get_process(process_id)


@router.delete("/api/processes/{process_id}", status_code=204)
def delete_process(process_id: int):
    conn = storage._conn()
    conn.execute("DELETE FROM processes WHERE id=?", (process_id,))
    conn.commit()
    return None


# ---------------------------------------------------------------------------
# Endpoints — 2. Automation Infrastructure
# ---------------------------------------------------------------------------
def _validate_automation(body: dict) -> dict:
    name = str(body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "name is required")
    source = str(body.get("trigger_source") or "manual")
    if source not in TRIGGER_SOURCES:
        raise HTTPException(400, f"trigger_source must be one of {', '.join(TRIGGER_SOURCES)}")
    conditions = body.get("conditions") or []
    if not isinstance(conditions, list):
        raise HTTPException(400, "conditions must be a list")
    for c in conditions:
        if not isinstance(c, dict) or not c.get("field"):
            raise HTTPException(400, "each condition needs {field, op?, value?}")
        if (c.get("op") or "eq") not in CONDITION_OPS:
            raise HTTPException(400, f"condition op must be one of {', '.join(CONDITION_OPS)}")
    actions = body.get("actions") or []
    if not isinstance(actions, list) or not actions:
        raise HTTPException(400, "actions must be a non-empty list")
    for a in actions:
        if not isinstance(a, dict) or a.get("type") not in ACTION_TYPES:
            raise HTTPException(400, f"action type must be one of {', '.join(ACTION_TYPES)}")
    return {
        "name": name,
        "description": str(body.get("description") or ""),
        "trigger_source": source,
        "trigger_event": str(body.get("trigger_event") or ""),
        "conditions": json.dumps(conditions),
        "actions": json.dumps(actions),
        "enabled": 1 if body.get("enabled", True) else 0,
    }


@router.get("/api/automations")
def list_automations():
    return _rows("SELECT * FROM automations ORDER BY id")


@router.post("/api/automations", status_code=201)
def create_automation(body: dict):
    a = _validate_automation(body)
    conn = storage._conn()
    cur = conn.execute(
        "INSERT INTO automations (name, description, trigger_source, trigger_event, conditions, actions, enabled, created_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (a["name"], a["description"], a["trigger_source"], a["trigger_event"],
         a["conditions"], a["actions"], a["enabled"], now_iso()),
    )
    conn.commit()
    return _row("SELECT * FROM automations WHERE id=?", (cur.lastrowid,))


@router.patch("/api/automations/{auto_id}")
def update_automation(auto_id: int, body: dict):
    if not _row("SELECT id FROM automations WHERE id=?", (auto_id,)):
        raise HTTPException(404, "Automation not found")
    current = _row("SELECT * FROM automations WHERE id=?", (auto_id,))
    merged = {**current, **body}
    a = _validate_automation(merged)
    conn = storage._conn()
    conn.execute(
        "UPDATE automations SET name=?, description=?, trigger_source=?, trigger_event=?, conditions=?, actions=?, enabled=? WHERE id=?",
        (a["name"], a["description"], a["trigger_source"], a["trigger_event"],
         a["conditions"], a["actions"], a["enabled"], auto_id),
    )
    conn.commit()
    return _row("SELECT * FROM automations WHERE id=?", (auto_id,))


@router.delete("/api/automations/{auto_id}", status_code=204)
def delete_automation(auto_id: int):
    conn = storage._conn()
    conn.execute("DELETE FROM automations WHERE id=?", (auto_id,))
    conn.commit()
    return None


@router.post("/api/automations/{auto_id}/run")
def run_automation_now(auto_id: int, body: dict | None = None):
    a = _row("SELECT * FROM automations WHERE id=?", (auto_id,))
    if not a:
        raise HTTPException(404, "Automation not found")
    if not a.get("enabled"):
        raise HTTPException(400, "Automation is disabled — enable it first (or use its PATCH endpoint).")
    payload = (body or {}).get("payload", body or {})
    if isinstance(payload, dict):
        ctx = dict(payload)
    else:
        ctx = {"payload": payload}
    return run_automation(a, ctx)


@router.get("/api/integrations")
def list_integrations():
    saved = {r["key"]: r for r in _rows("SELECT key, status, config, updated_at FROM integration_settings")}
    out = []
    for it in INTEGRATIONS:
        row = saved.get(it["key"], {})
        cfg = row.get("config") or {}
        if not isinstance(cfg, dict):
            cfg = {}
        status = row.get("status", "unconfigured")
        if it["key"] == "asana":
            try:
                import asana_sync
                status = "configured" if asana_sync.has_credentials() else (status if cfg else "unconfigured")
            except Exception:
                pass
        if it["key"] == "spapi":
            try:
                import productpipeline
                status = "configured" if productpipeline.get_config()["has_key"] else (status if cfg else "unconfigured")
            except Exception:
                pass
        out.append({**it, "status": status, "config": _mask(cfg), "updated_at": row.get("updated_at", "")})
    return out


@router.post("/api/integrations/{key}")
def save_integration(key: str, body: dict):
    it = next((x for x in INTEGRATIONS if x["key"] == key), None)
    if not it:
        raise HTTPException(404, f"Unknown integration '{key}'")
    allowed = {f["key"] for f in it["fields"]}
    cfg = {k: str(v).strip() for k, v in (body.get("config") or {}).items() if k in allowed and str(v).strip()}
    # Asana PAT flows into the asana sync config so live actions use the same credential.
    if key == "asana" and cfg.get("pat"):
        try:
            import asana_sync
            asana_sync.save_config(pat=cfg["pat"])
        except Exception:
            pass
    # SP-API credentials flow into the product-pipeline config (data/spapi.json).
    if key == "spapi":
        try:
            import productpipeline
            productpipeline.apply_config(cfg)
        except Exception:
            pass
    status = "configured" if cfg else "unconfigured"
    if key == "spapi":
        try:
            import productpipeline
            # reflect real credential readiness, not just "a field was set"
            status = "configured" if productpipeline.get_config()["has_key"] else "unconfigured"
        except Exception:
            pass
    conn = storage._conn()
    conn.execute(
        "INSERT INTO integration_settings (key, name, kind, status, config, updated_at) VALUES (?,?,?,?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET status=excluded.status, config=excluded.config, updated_at=excluded.updated_at",
        (key, it["name"], it["kind"], status, json.dumps(cfg), now_iso()),
    )
    conn.commit()
    return {"ok": True, "key": key, "status": status, "config": _mask(cfg)}


@router.post("/api/integrations/{key}/test")
def test_integration(key: str):
    it = next((x for x in INTEGRATIONS if x["key"] == key), None)
    if not it:
        raise HTTPException(404, f"Unknown integration '{key}'")
    cfg = _get_integration_config(key)

    if key == "asana":
        headers, base = _asana_client()
        if not headers:
            return {"ok": False, "mode": "unconfigured", "detail": "No Asana PAT configured — add one in Settings → Asana."}
        try:
            with urllib.request.urlopen(urllib.request.Request(f"{base}/users/me", headers=headers), timeout=15) as r:
                me = json.loads(r.read().decode()).get("data", {})
            return {"ok": True, "mode": "live", "detail": f"Connected as {me.get('name')} ({me.get('email')})."}
        except urllib.error.HTTPError as exc:
            return {"ok": False, "mode": "live", "detail": f"Asana API {exc.code}: {exc.read().decode('utf-8', errors='replace')[:200]}"}

    if key == "spapi":
        try:
            import productpipeline
            return productpipeline.test_connection()
        except Exception as exc:
            return {"ok": False, "mode": "live", "detail": str(exc)}

    if key in ("zapier", "make"):
        url = cfg.get("webhook_url", "")
        if not url:
            return {"ok": False, "mode": "unconfigured", "detail": "No webhook URL configured."}
        try:
            req = urllib.request.Request(url, data=json.dumps({"text": "Conductor connection test"}).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=15) as r:
                body = r.read().decode("utf-8", errors="replace")
            return {"ok": True, "mode": "live", "detail": f"Webhook accepted (HTTP {r.status}): {body[:120]}"}
        except urllib.error.HTTPError as exc:
            return {"ok": False, "mode": "live", "detail": f"Webhook rejected ({exc.code}): {exc.read().decode('utf-8', errors='replace')[:200]}"}
        except Exception as exc:
            return {"ok": False, "mode": "live", "detail": str(exc)}

    return {"ok": True, "mode": "simulated",
            "detail": f"{it['name']} credentials are stored but this MVP doesn't call the API live yet. "
                      "A production build would complete OAuth/API setup and verify with a ping."}


@router.post("/webhooks/automation/{source}")
async def webhook_automation(source: str, request: Request):
    """Generic inbound event receiver: POST JSON → trigger matching automations.

    Body shape: {"event": "task_completed", "payload": {…}} — or a bare JSON
    object (used as the payload directly, event = '').
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Expected a JSON body")
    if isinstance(body, dict) and set(body.keys()) <= {"event", "payload"} and "payload" in body:
        event = str(body.get("event") or "")
        payload = body.get("payload") if isinstance(body.get("payload"), dict) else {"payload": body["payload"]}
    else:
        event, payload = "", body if isinstance(body, dict) else {"payload": body}

    ctx = dict(payload)
    ctx.setdefault("source", source)
    ctx.setdefault("event", event)

    conn = storage._conn()
    conn.execute("INSERT INTO events (source, type, payload, created_at) VALUES (?,?,?,?)",
                 (source, event, json.dumps(payload, default=str)[:8000], now_iso()))
    conn.commit()

    matches = _rows("SELECT * FROM automations WHERE enabled=1 AND trigger_source=? AND (trigger_event='' OR trigger_event=?)",
                    (source, event))
    results = [run_automation(a, ctx) for a in matches]
    return {"accepted": True, "source": source, "event": event,
            "matched_automations": len(matches),
            "runs": results}


@router.get("/api/events")
def list_events(limit: int = 100):
    rows = _rows("SELECT * FROM events ORDER BY id DESC LIMIT ?", (min(limit, 500),))
    return rows


# ---------------------------------------------------------------------------
# Endpoints — 3. AI Integration
# ---------------------------------------------------------------------------
@router.get("/api/ai/workflows")
def ai_workflows():
    return [{"workflow": k, "title": v["title"], "desc": v["desc"]} for k, v in AI_WORKFLOWS.items()]


@router.post("/api/ai/run")
def ai_run(body: dict):
    workflow = str(body.get("workflow") or "")
    text = str(body.get("input") or body.get("text") or "")
    return run_ai(workflow, text)


@router.get("/api/ai/runs")
def ai_runs(limit: int = 50):
    return _rows("SELECT * FROM ai_runs ORDER BY id DESC LIMIT ?", (min(limit, 200),))


# ---------------------------------------------------------------------------
# Endpoints — 4. SOPs / Runbooks / Governance
# ---------------------------------------------------------------------------
@router.get("/api/sops")
def list_sops(category: str | None = None):
    if category:
        return _rows("SELECT * FROM sops WHERE category=? ORDER BY updated_at DESC", (category,))
    return _rows("SELECT * FROM sops ORDER BY updated_at DESC")


@router.get("/api/sops/search")
def search_sops(q: str = ""):
    q = q.strip()
    if not q:
        return []
    like = f"%{q}%"
    return _rows("SELECT * FROM sops WHERE title LIKE ? OR body LIKE ? ORDER BY updated_at DESC LIMIT 50", (like, like))


@router.post("/api/sops", status_code=201)
def create_sop(body: dict):
    title = str(body.get("title") or "").strip()
    if not title:
        raise HTTPException(400, "title is required")
    category = str(body.get("category") or "sop")
    if category not in ("sop", "runbook", "training", "governance"):
        raise HTTPException(400, "category must be sop|runbook|training|governance")
    ts = now_iso()
    conn = storage._conn()
    cur = conn.execute(
        "INSERT INTO sops (title, category, body, version, created_at, updated_at) VALUES (?,?,?,1,?,?)",
        (title, category, str(body.get("body") or ""), ts, ts),
    )
    conn.commit()
    return _row("SELECT * FROM sops WHERE id=?", (cur.lastrowid,))


@router.get("/api/sops/{sop_id}")
def get_sop(sop_id: int):
    s = _row("SELECT * FROM sops WHERE id=?", (sop_id,))
    if not s:
        raise HTTPException(404, "SOP not found")
    return s


@router.patch("/api/sops/{sop_id}")
def update_sop(sop_id: int, body: dict):
    s = _row("SELECT * FROM sops WHERE id=?", (sop_id,))
    if not s:
        raise HTTPException(404, "SOP not found")
    merged = {**s, **{k: v for k, v in body.items() if k in ("title", "category", "body")}}
    if merged["category"] not in ("sop", "runbook", "training", "governance"):
        raise HTTPException(400, "category must be sop|runbook|training|governance")
    if not str(merged["title"]).strip():
        raise HTTPException(400, "title is required")
    conn = storage._conn()
    conn.execute(
        "UPDATE sops SET title=?, category=?, body=?, version=COALESCE(version,0)+1, updated_at=? WHERE id=?",
        (str(merged["title"]).strip(), merged["category"], str(merged["body"] or ""), now_iso(), sop_id),
    )
    conn.commit()
    return _row("SELECT * FROM sops WHERE id=?", (sop_id,))


@router.delete("/api/sops/{sop_id}", status_code=204)
def delete_sop(sop_id: int):
    conn = storage._conn()
    conn.execute("DELETE FROM sops WHERE id=?", (sop_id,))
    conn.commit()
    return None


# ---------------------------------------------------------------------------
# Dashboard rollup
# ---------------------------------------------------------------------------
@router.get("/api/automation/stats")
def automation_stats():
    conn = storage._conn()
    procs = _rows("SELECT * FROM processes")
    autos = _rows("SELECT * FROM automations")
    sops = _rows("SELECT id FROM sops")
    ai = _rows("SELECT * FROM ai_runs ORDER BY id DESC LIMIT 50")
    events = _rows("SELECT * FROM events ORDER BY id DESC LIMIT 50")

    hours_saved = sum(float(p.get("manual_hours_week") or 0) for p in procs
                      if p.get("status") in ("shipped", "adopted"))
    by_status: dict[str, int] = {}
    for p in procs:
        by_status[p.get("status", "discovered")] = by_status.get(p.get("status", "discovered"), 0) + 1

    try:
        import chat
        cfg = chat._load_config()
        provider = {"provider": cfg["provider"], "model": cfg["llama_model"] if cfg["provider"] == "llama" else cfg["model"],
                    "configured": bool(cfg["api_key"]) or cfg["provider"] == "llama"}
    except Exception:
        provider = {"provider": "none", "model": "", "configured": False}

    return {
        "processes": {"total": len(procs), "by_status": by_status,
                      "annual_cost": round(sum(float(p.get("annual_cost") or 0) for p in procs), 2)},
        "automations": {"total": len(autos), "enabled": sum(1 for a in autos if a.get("enabled")),
                        "runs": sum(int(a.get("run_count") or 0) for a in autos),
                        "last_statuses": {a["name"]: a.get("last_status") for a in autos if a.get("last_run_at")}},
        "ai": {"runs": len(ai), "tokens_in": sum(int(r.get("tokens_in") or 0) for r in ai),
               "tokens_out": sum(int(r.get("tokens_out") or 0) for r in ai)},
        "sops": len(sops),
        "events": len(events),
        "hours_saved_week": round(hours_saved, 1),
        "hours_saved_year": round(hours_saved * WEEKS_PER_YEAR, 1),
        "savings_year": round(hours_saved * WEEKS_PER_YEAR * HOURLY_RATE, 2),
        "provider": provider,
        "recent_ai": ai[:8],
        "recent_events": events[:8],
    }
