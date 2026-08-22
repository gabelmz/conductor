"""Conductor — Business Process Automation hub (FastAPI backend).

Serves:
  - REST API (/api/*): products, compliance checks, regulations, requests log
  - Large file ingestion (/api/ingest/*): chunked resumable uploads + parsing
  - Webhook endpoint (/webhooks/ingest) for external HTTP pushes
  - Static Hermes-style desktop UI at /
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# Ensure backend/ is importable regardless of how uvicorn resolves the module
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import FastAPI, HTTPException, Request, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import storage
import automation
import bernie
import ai_ingest
from agents import DEV_ROOT, _safe_walk, list_agents, run_quick_action
from chat import router as chat_router
from llama import router as llama_router
from ui import router as ui_router
from compliance import REGULATIONS, evaluate_product, overall_score, overall_severity
from ingestion import (
    complete_upload, init_upload, run_compliance, upload_status, write_chunk,
)
import asana_sync

# Ensure schema exists (idempotent; creates any missing tables incl. tasks)
storage.init_db()
from hub import init_hub_db
from keepa import init_keepa_db
from people import init_people_db
from localsources import init_local_sources_db
from productpipeline import init_product_pipeline_db
from insights import init_insights_db
from attributeaudit import init_attribute_audit_db

init_hub_db()
init_keepa_db()
init_people_db()
init_local_sources_db()
init_product_pipeline_db()
init_insights_db()
init_attribute_audit_db()

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI(
    title="Conductor",
    description="Conductor — business process automation hub with AI workflows.",
    version="1.5.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    body_preview = ""
    if request.method in ("POST", "PUT", "PATCH") and "ingest" not in request.url.path:
        sensitive_prefixes = ("/api/mcp", "/api/supabase/config", "/api/supabase/test", "/api/asana/config")
        if request.url.path.startswith(sensitive_prefixes):
            body_preview = "[REDACTED CONFIG BODY]"
        else:
            try:
                body = await request.body()
                body_preview = body[:400].decode("utf-8", errors="replace")
            except Exception:
                pass
    response = await call_next(request)
    latency = (time.perf_counter() - start) * 1000
    storage.log_request(
        method=request.method,
        path=request.url.path,
        client=request.client.host if request.client else "",
        status=response.status_code,
        latency_ms=latency,
        body_preview=body_preview,
    )
    return response


# --------------------------------------------------------------------------
# Health / meta
# --------------------------------------------------------------------------
@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "service": "conductor",
        "version": "1.5.0",
        "products": storage.count_products(),
    }


@app.get("/api/regulations")
def regulations():
    return [{"code": r.code, "name": r.name, "markets": r.markets,
             "applies_to": r.applies_to, "description": r.description}
            for r in REGULATIONS]


# --------------------------------------------------------------------------
# Agent Gallery
# --------------------------------------------------------------------------
@app.get("/api/agents")
def agents_gallery():
    return list_agents()


@app.get("/api/agents/{agent_id}")
def agent_detail(agent_id: str):
    for a in list_agents():
        if a["id"] == agent_id:
            return a
    raise HTTPException(404, "Agent not found")


@app.post("/api/agents/{agent_id}/run")
def agent_run(agent_id: str):
    """Run an agent's quick action against its real workspace artifacts."""
    try:
        return run_quick_action(agent_id)
    except Exception as exc:
        raise HTTPException(500, f"Agent action failed: {exc}")


# --------------------------------------------------------------------------
# Products
# --------------------------------------------------------------------------
def _product_payload(body: dict) -> dict:
    sku = str(body.get("sku") or "").strip()
    name = str(body.get("name") or "").strip()
    if not sku or not name:
        raise HTTPException(400, "sku and name are required")
    return {
        "sku": sku,
        "name": name,
        "category": str(body.get("category") or "general"),
        "market": str(body.get("market") or "US"),
        "attributes": body.get("attributes") or {},
        "source": str(body.get("source") or "api"),
    }


@app.post("/api/products", status_code=201)
def create_product(body: dict):
    p = _product_payload(body)
    pid = storage.create_product(**p)
    result = run_compliance(pid)
    return {"product": storage.get_product(pid), "compliance": result}


@app.get("/api/products")
def products(limit: int = 200):
    return storage.list_products(limit)


@app.get("/api/products/{product_id}")
def product_detail(product_id: int):
    p = storage.get_product(product_id)
    if not p:
        raise HTTPException(404, "Product not found")
    checks = storage.list_checks(product_id)
    return {"product": p, "checks": checks}


@app.post("/api/products/{product_id}/check")
def check_product(product_id: int):
    if not storage.get_product(product_id):
        raise HTTPException(404, "Product not found")
    result = run_compliance(product_id)
    return {"product_id": product_id, **result, "checks": storage.list_checks(product_id)}


@app.delete("/api/products/{product_id}", status_code=204)
def delete_product(product_id: int):
    conn = storage._conn()
    conn.execute("DELETE FROM products WHERE id=?", (product_id,))
    conn.execute("DELETE FROM checks WHERE product_id=?", (product_id,))
    conn.commit()
    return None


# --------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------
@app.get("/api/checks")
def checks(product_id: int | None = None, limit: int = 500):
    return storage.list_checks(product_id, limit)


@app.get("/api/checks/summary")
def checks_summary():
    """Aggregated summary of latest check per product."""
    products = storage.list_products(200)
    out = []
    for p in products:
        latest = storage.latest_check_by_product(p["id"])
        if latest:
            out.append({"product": p, "regulation": latest["regulation"],
                        "status": latest["status"], "severity": latest["severity"],
                        "score": latest["score"]})
    return out


# --------------------------------------------------------------------------
# Jobs
# --------------------------------------------------------------------------
@app.get("/api/jobs")
def jobs(limit: int = 50):
    return storage.list_jobs(limit)


@app.get("/api/jobs/{job_id}")
def job_detail(job_id: int):
    j = storage.get_job(job_id)
    if not j:
        raise HTTPException(404, "Job not found")
    return j


# --------------------------------------------------------------------------
# Files / ingestion
# --------------------------------------------------------------------------
@app.post("/api/ingest/init")
def ingest_init(body: dict):
    filename = str(body.get("filename") or "catalog.csv")
    total_size = int(body.get("total_size") or 0)
    chunk_size = body.get("chunk_size")
    return init_upload(filename, total_size, chunk_size)


@app.put("/api/ingest/{upload_id}/chunk/{index}")
async def ingest_chunk(upload_id: str, index: int, request: Request):
    data = await request.body()
    if not data:
        raise HTTPException(400, "Empty chunk")
    try:
        return write_chunk(upload_id, index, data)
    except KeyError:
        raise HTTPException(404, "Unknown upload")
    except ValueError as exc:
        raise HTTPException(409, str(exc))


@app.get("/api/ingest/{upload_id}/status")
def ingest_status(upload_id: str):
    try:
        return upload_status(upload_id)
    except KeyError:
        raise HTTPException(404, "Unknown upload")


@app.post("/api/ingest/{upload_id}/complete")
def ingest_complete(upload_id: str):
    try:
        return complete_upload(upload_id)
    except KeyError:
        raise HTTPException(404, "Unknown upload")
    except ValueError as exc:
        raise HTTPException(409, str(exc))


@app.post("/api/ingest/{upload_id}/ai-process")
def ingest_ai_process(upload_id: str):
    """Kick off the AI catalog pass (categorize/clean/extract/flags/recs)."""
    try:
        return ai_ingest.ai_process(upload_id)
    except KeyError:
        raise HTTPException(404, "Unknown upload")
    except ValueError as exc:
        raise HTTPException(409, str(exc))


@app.get("/api/ingest/{upload_id}/ai")
def ingest_ai_findings(upload_id: str):
    meta = storage.get_file_by_upload(upload_id)
    if not meta:
        raise HTTPException(404, "Unknown upload")
    findings = storage.list_ai_findings(meta["id"])
    for f in findings:
        p = storage.get_product(f["product_id"]) or {}
        f["sku"] = p.get("sku") or ""
        f["product_name"] = p.get("name") or ""
    return {"upload_id": upload_id, "file_id": meta["id"], "count": len(findings),
            "findings": findings}


@app.post("/api/ingest/upload")
async def ingest_small_file(file: UploadFile = File(...)):
    """Single-request ingestion for smaller files (<~10MB)."""
    data = await file.read()
    if len(data) > 50 * 1024 * 1024:
        raise HTTPException(413, "File too large for single-request upload; use chunked ingestion")
    from parsers import parse_catalog
    from pathlib import Path as P
    import tempfile, os, uuid
    tmp = P(tempfile.gettempdir()) / f"ca_upload_{os.getpid()}_{file.filename}"
    tmp.write_bytes(data)
    try:
        rows = parse_catalog(tmp, file.filename or "catalog.csv")
    finally:
        tmp.unlink(missing_ok=True)
    upload_id = uuid.uuid4().hex[:12]
    file_id = storage.create_file(upload_id, file.filename or "catalog.csv", len(data), max(len(data), 1))
    storage.update_file(upload_id, status="parsing")
    job_id = storage.create_job("parse_catalog", file_id)
    storage.update_job(job_id, status="running", progress=0, message=f"Parsed {len(rows)} rows — ingesting…")
    import threading
    threading.Thread(target=_ingest_rows_job, args=(job_id, rows, file_id, upload_id), daemon=True).start()
    return {"rows": len(rows), "job_id": job_id, "upload_id": upload_id}


def _ingest_rows_job(job_id: int, rows: list[dict], file_id: int | None = None,
                     upload_id: str | None = None) -> None:
    total = len(rows)
    try:
        for i, row in enumerate(rows):
            pid = storage.create_product(
                sku=row["sku"], name=row["name"], category=row["category"],
                market=row["market"], attributes=row["attributes"], source="file",
                file_id=file_id,
            )
            run_compliance(pid)
            if i % 25 == 0:
                storage.update_job(job_id, progress=round(i / max(total, 1) * 100, 1))
        storage.update_job(job_id, status="done", progress=100,
                           message=f"Ingested {total} products with compliance checks.")
        if upload_id:
            storage.update_file(upload_id, status="done", record_count=total)
    except Exception as exc:
        storage.update_job(job_id, status="error", message=str(exc))
        if upload_id:
            storage.update_file(upload_id, status="error", error=str(exc))


@app.get("/api/files")
def files(limit: int = 100):
    return storage.list_files(limit)


# --------------------------------------------------------------------------
# Webhook (HTTP request support for external systems)
# --------------------------------------------------------------------------
@app.post("/webhooks/ingest")
async def webhook_ingest(request: Request):
    """Accept external HTTP pushes: either a single product object, a
    {'products': [...]} list, or a raw file upload (multipart or body bytes).
    """
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        uploaded = form.get("file")
        if uploaded and hasattr(uploaded, "read"):
            data = await uploaded.read()
            from parsers import parse_catalog
            from pathlib import Path as P
            import tempfile, os, threading
            tmp = P(tempfile.gettempdir()) / f"ca_wh_{os.getpid()}_{uploaded.filename}"
            tmp.write_bytes(data)
            try:
                rows = parse_catalog(tmp, uploaded.filename or "catalog.csv")
            finally:
                tmp.unlink(missing_ok=True)
            job_id = storage.create_job("webhook_ingest", None)
            storage.update_job(job_id, status="running", progress=0,
                               message=f"Webhook: parsing {len(rows)} rows")
            threading.Thread(target=_ingest_rows_job, args=(job_id, rows), daemon=True).start()
            return {"accepted": True, "source": "webhook-file", "rows": len(rows), "job_id": job_id}

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Expected JSON body (product object or {'products': [...]})")

    if isinstance(body, dict) and "products" in body and isinstance(body["products"], list):
        items = body["products"]
    elif isinstance(body, list):
        items = body
    else:
        items = [body]

    created = []
    for item in items:
        try:
            p = _product_payload(item)
            pid = storage.create_product(**p, source="webhook")
            result = run_compliance(pid)
            created.append({"id": pid, "sku": p["sku"], "score": result["overall_score"]})
        except HTTPException:
            continue
    return {"accepted": True, "source": "webhook-json", "created": len(created), "products": created}


# --------------------------------------------------------------------------
# Request log
# --------------------------------------------------------------------------
@app.get("/api/requests")
def requests(limit: int = 100):
    return storage.list_requests(limit)


# --------------------------------------------------------------------------
# Action queue (Obsidian triage → tasks)
# --------------------------------------------------------------------------
@app.post("/api/tasks/import")
def tasks_import():
    """Pull tasks from Obsidian Daily Triage notes into the action queue."""
    from agents import scan_obsidian_tasks
    items = scan_obsidian_tasks()
    inserted = storage.import_tasks(items)
    return {"scanned": len(items), "inserted": inserted, "total": len(storage.list_tasks())}


@app.get("/api/tasks")
def tasks(status: str | None = None, limit: int = 500):
    return storage.list_tasks(limit, status)


@app.patch("/api/tasks/{task_id}")
def task_update(task_id: int, body: dict):
    status = str(body.get("status") or "").strip()
    if status not in ("open", "done", "blocked"):
        raise HTTPException(400, "status must be open|done|blocked")
    if not storage.update_task(task_id, status):
        raise HTTPException(404, "Task not found")
    return {"id": task_id, "status": status}


@app.post("/api/tasks/clear-done", status_code=204)
def tasks_clear_done():
    storage.clear_done_tasks()
    return None


# --------------------------------------------------------------------------
# Asana sync (all of Asana → local SQLite store)
# --------------------------------------------------------------------------
@app.get("/api/asana/status")
def asana_status():
    """Sync config + store counts + last run."""
    return {
        "config": asana_sync.get_config(),
        "counts": storage.asana_counts(),
        "last_run": storage.last_asana_run(),
    }


@app.post("/api/asana/config")
def asana_config(body: dict):
    """Persist PAT / workspace / portfolio / source to data/asana.json."""
    allowed = {"pat", "workspace_gid", "portfolio_gid", "project_source"}
    payload = {k: v for k, v in body.items() if k in allowed}
    if not payload:
        raise HTTPException(400, "No valid config keys provided")
    if "project_source" in payload and payload["project_source"] not in ("workspace", "portfolio"):
        raise HTTPException(400, "project_source must be workspace|portfolio")
    return asana_sync.save_config(**payload)


@app.post("/api/asana/sync")
def asana_sync_start(body: dict):
    """Kick off a background full/delta sync via the jobs queue."""
    mode = str(body.get("mode") or "recent")
    if mode not in ("all", "delta", "recent"):
        raise HTTPException(400, "mode must be all|delta|recent")
    deep = bool(body.get("deep"))
    if not asana_sync.has_credentials():
        raise HTTPException(400, "Asana PAT not configured — add it in Settings → Asana (or set ASANA_PAT).")
    # Supersede any prior running asana sync jobs (e.g. after a server restart)
    conn = storage._conn()
    conn.execute(
        "UPDATE jobs SET status='error', message='Superseded by a new sync', "
        "updated_at=? WHERE kind='asana_sync' AND status IN ('running','queued')",
        (storage.now_iso(),),
    )
    conn.commit()
    job_id = storage.create_job("asana_sync", None)
    storage.update_job(job_id, status="running", progress=1,
                       message=f"Asana {mode} sync starting" + (" (deep)" if deep else "") + "…")

    def _run():
        try:
            def cb(pct: float, msg: str) -> None:
                storage.update_job(job_id, progress=round(pct, 1), message=msg)
            counts = asana_sync.sync_all(mode=mode, deep=deep, progress=cb)
            storage.update_job(job_id, status="done", progress=100,
                               message=f"Synced {counts['tasks']} tasks across {counts['projects']} projects.")
        except Exception as exc:
            storage.update_job(job_id, status="error", message=str(exc))

    import threading
    threading.Thread(target=_run, daemon=True).start()
    return {"job_id": job_id, "mode": mode, "deep": deep, "status": "started"}


@app.get("/api/asana/projects")
def asana_projects(include_archived: bool = False):
    return storage.list_asana_projects(include_archived=include_archived)


@app.get("/api/asana/tasks")
def asana_tasks(project: str | None = None, assignee: str | None = None,
                status: str | None = None, section: str | None = None,
                q: str | None = None, limit: int = 500):
    if status and status not in ("open", "completed"):
        raise HTTPException(400, "status must be open|completed")
    return storage.list_asana_tasks(project_gid=project, assignee_gid=assignee,
                                    status=status, section=section, q=q,
                                    limit=min(limit, 1000))


@app.get("/api/asana/tasks/{gid}")
def asana_task_detail(gid: str, refresh: bool = False):
    """One task + stories/attachments/subtasks (lazy-hydrated from Asana)."""
    task = storage.get_asana_task(gid)
    if not task:
        raise HTTPException(404, "Task not found — run a sync first")
    stories = storage.list_asana_stories(gid)
    attachments = storage.list_asana_attachments(gid)
    subtasks = storage.list_asana_subtasks(gid)
    # Lazy hydrate: fetch live details the first time a task is opened
    # (deep sync is skipped for large orgs). refresh=true forces a re-pull.
    if refresh or not (stories or attachments or subtasks):
        try:
            d = asana_sync.fetch_task_details(gid)
            stories, attachments, subtasks = d["stories"], d["attachments"], d["subtasks"]
        except Exception:
            pass  # return whatever is already stored
    return {
        "task": task,
        "stories": stories,
        "attachments": attachments,
        "subtasks": subtasks,
    }


@app.get("/api/asana/users")
def asana_users():
    return storage.list_asana_users()


@app.get("/api/asana/teams")
def asana_teams():
    return storage.list_asana_teams()


@app.get("/api/asana/summary")
def asana_summary():
    return {"counts": storage.asana_counts(), "kpis": storage.asana_summary(),
            "runs": storage.list_asana_runs(10)}


# --------------------------------------------------------------------------
# Home dashboard — stats + workspace folder tree
# --------------------------------------------------------------------------
_START_TIME = time.monotonic()
_TREE_SKIP = {".git", ".venv", "venv", "node_modules", "dist", "__pycache__",
              ".obsidian", ".trash", ".gitignore", "build", "target"}


def _count_subtree(path, budget=2500) -> tuple[int, int, int]:
    """Bounded recursive count of (files, notes, buckets) skipping heavy dirs."""
    notes = files = buckets = count = 0
    for dirpath, dirnames, filenames in os.walk(path, onerror=lambda e: None):
        dirnames[:] = [d for d in dirnames if d not in _TREE_SKIP and not d.startswith(".")]
        for fn in filenames:
            files += 1
            if fn.endswith(".md"):
                notes += 1
            if fn == ".eb-frontmatter.yaml":
                buckets += 1
            count += 1
            if count >= budget:
                return files, notes, buckets
    return files, notes, buckets


@app.get("/api/stats")
def stats():
    """Aggregate stats for the home dashboard + statusbar."""
    try:
        products = storage.count_products()
        checks_all = storage.list_checks(limit=2000)
        files = len(storage.list_files())
        tasks = storage.list_tasks(limit=1000)
        requests = len(storage.list_requests())
    except Exception:
        products = checks_all = files = tasks = requests = 0
    try:
        agents = len(list_agents())
    except Exception:
        agents = 0

    # severity breakdown of the latest check per product
    by_sev = {"blocker": 0, "warning": 0, "info": 0, "ok": 0}
    latest = {}
    for c in checks_all:
        latest[c["product_id"]] = c
    for c in latest.values():
        by_sev[c.get("severity", "ok")] = by_sev.get(c.get("severity", "ok"), 0) + 1

    db_size = 0
    try:
        db_size = storage.DB_PATH.stat().st_size
    except Exception:
        pass

    # Asana sync state (best-effort — tables may be empty pre-sync)
    asana = {"configured": False, "open": 0, "overdue": 0, "total": 0, "projects": 0, "last_sync": ""}
    try:
        asana_cfg = asana_sync.get_config()
        asana_counts = storage.asana_counts()
        asana["configured"] = asana_cfg["has_pat"]
        asana["open"] = asana_counts["open"]
        asana["overdue"] = asana_counts["overdue"]
        asana["total"] = asana_counts["tasks"]
        asana["projects"] = asana_counts["projects"]
        asana["last_sync"] = asana_cfg["last_sync"]
    except Exception:
        pass

    # AI provider + model + context window (from data/chat.json + live llama /props)
    model = {"provider": "deepseek", "name": "deepseek-v4-flash"}
    context_window = 16384
    llama_server = {"up": False, "port": None}
    try:
        import chat as chat_mod

        cfg = chat_mod._load_config()
        provider = cfg["provider"]
        model["provider"] = provider
        model["name"] = cfg["llama_model"] if provider == "llama" else cfg["model"]
        if provider == "llama":
            try:
                import llama as llama_mod

                st = llama_mod.server_status()
                llama_server["up"] = bool(st.get("running"))
                llama_server["port"] = st.get("port")
                n_ctx = None
                if st.get("running"):
                    n_ctx = llama_mod.server_props().get("n_ctx")
                context_window = int(n_ctx or cfg["llama_ctx"])
            except Exception:
                context_window = int(cfg["llama_ctx"])
        else:
            # deepseek: no per-call ctx reported — sane constant, overridable in chat.json
            context_window = int(cfg.get("model_ctx") or 16384)
    except Exception:
        pass

    # Cumulative token usage (survives restarts via data/usage.json)
    try:
        import usage

        token_usage = usage.get()
    except Exception:
        token_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "calls": 0, "updated_at": ""}

    # No per-agent last_run tracking exists (AGENT_DEFS are static defs) →
    # fall back to total agent count
    active_agents = agents

    return {
        "products": products,
        "checks": len(checks_all),
        "by_severity": by_sev,
        "agents": agents,
        "active_agents": active_agents,
        "files": files,
        "tasks_open": sum(1 for t in tasks if t.get("status") == "open"),
        "tasks_total": len(tasks),
        "asana": asana,
        "requests": requests,
        "db_size": db_size,
        "uptime_s": round(time.monotonic() - _START_TIME),
        "service": "conductor",
        "version": "1.5.0",
        "latest_jobs": storage.list_jobs(limit=5),
        # --- new statusbar fields (additive only — old keys unchanged) ---
        "model": model,
        "context_window": context_window,
        "token_usage": token_usage,
        "connections": {
            "llama_server": llama_server,
            "asana": {
                "last_sync": asana["last_sync"],
                "tasks": asana["total"],
                "open": asana["open"],
                "overdue": asana["overdue"],
                "projects": asana["projects"],
            },
            "provider": {"name": model["provider"]},
        },
    }


@app.get("/api/vault/tree")
def vault_tree(path: str = ""):
    """Workspace folder tree for the right-hand Folders panel (lazy expand)."""
    base = DEV_ROOT
    if path:
        target = (DEV_ROOT / path).resolve()
        if not str(target).startswith(str(DEV_ROOT.resolve())):
            raise HTTPException(400, "path escapes workspace")
    else:
        target = DEV_ROOT

    dirs, files = [], []
    try:
        entries = sorted(os.scandir(target), key=lambda e: (not e.is_dir(follow_symlinks=False), e.name.lower()))
    except OSError:
        raise HTTPException(404, "path not found")

    for e in entries:
        if e.name.startswith("."):
            continue
        rel = str(target.relative_to(DEV_ROOT))
        rel_path = f"{rel}/{e.name}" if rel else e.name
        if e.is_dir(follow_symlinks=False):
            if e.name in _TREE_SKIP:
                continue
            files_n, notes_n, buckets_n = _count_subtree(e.path)
            dirs.append({"name": e.name, "path": rel_path, "files": files_n,
                         "notes": notes_n, "buckets": buckets_n})
        else:
            try:
                size = e.stat(follow_symlinks=False).st_size
            except OSError:
                size = 0
            files.append({"name": e.name, "size": size,
                          "ext": e.name.rsplit(".", 1)[-1].lower() if "." in e.name else ""})
    return {"root": DEV_ROOT.name, "path": (str(target.relative_to(DEV_ROOT)) if target != DEV_ROOT else ""),
            "dirs": dirs[:80], "files": files[:60]}


app.include_router(chat_router)
app.include_router(llama_router)
app.include_router(ui_router)
app.include_router(automation.router)
app.include_router(bernie.router)
from plugins import router as plugins_router
from hub import router as hub_router
from reports import router as reports_router
from guidelines import router as guidelines_router
from flatfiles import router as flatfiles_router
from svl import router as svl_router
from data import router as data_router
from features import router as features_router
from brandcompare import router as brandcompare_router
from keepa import router as keepa_router
from people import router as people_router
from bulkimport import router as bulkimport_router
from localsources import router as localsources_router
from productpipeline import router as productpipeline_router
from insights import router as insights_router
from attributeaudit import router as attributeaudit_router
from hf import router as hf_router
from mcp_servers import router as mcp_router
from supabase_sync import router as supabase_sync_router

app.include_router(plugins_router)
app.include_router(hub_router)
app.include_router(reports_router)
app.include_router(guidelines_router)
app.include_router(flatfiles_router)
app.include_router(svl_router)
app.include_router(data_router)
app.include_router(features_router)
app.include_router(brandcompare_router)
app.include_router(keepa_router)
app.include_router(people_router)
app.include_router(bulkimport_router)
app.include_router(localsources_router)
app.include_router(productpipeline_router)
app.include_router(insights_router)
app.include_router(attributeaudit_router)
app.include_router(hf_router)
app.include_router(mcp_router)
app.include_router(supabase_sync_router)


# --------------------------------------------------------------------------
# Frontend (Hermes-style desktop UI)
# --------------------------------------------------------------------------
@app.middleware("http")
async def _no_cache_frontend(request, call_next):
    """Force refetch of frontend assets — Electron's HTTP cache otherwise
    serves stale CSS/JS across runs sharing the userData dir."""
    response = await call_next(request)
    p = request.url.path
    if p == "/" or p.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
    return response


@app.get("/")
def index():
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
