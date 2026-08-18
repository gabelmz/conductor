"""Conductor — AI chat backend (DeepSeek, OpenAI-compatible, streaming).

Serves:
  - POST /api/chat            streaming chat completion (text/plain chunks)
  - GET  /api/chat/config     current provider/model/base_url (key masked)
  - POST /api/chat/config     persist provider/model/base_url/api_key

Credentials live in data/chat.json (alongside compliance.db) so the
installed desktop app keeps working across restarts without env vars.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse

from storage import DATA_DIR
import usage

router = APIRouter(prefix="/api/chat", tags=["chat"])

CONFIG_PATH = DATA_DIR / "chat.json"

# --- chat document referencing ------------------------------------------
CHAT_DOCS_DIR = DATA_DIR / "chat-docs"
CHAT_DOCS_DIR.mkdir(parents=True, exist_ok=True)
TEXT_EXTS = {".txt", ".md", ".csv", ".tsv", ".json", ".ndjson", ".jsonl",
             ".log", ".html", ".xml", ".yaml", ".yml"}
DOC_TEXT_CAP = 12000  # chars injected per referenced doc


def _safe_doc_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", Path(name or "doc.txt").name)[:120]


@router.post("/docs")
async def upload_doc(file: UploadFile = File(...)):
    ref_id = uuid.uuid4().hex[:12]
    fname = _safe_doc_name(file.filename)
    d = CHAT_DOCS_DIR / ref_id
    d.mkdir(parents=True, exist_ok=True)
    raw = await file.read()
    (d / fname).write_bytes(raw)
    ext = Path(fname).suffix.lower()
    if ext in TEXT_EXTS:
        text = raw.decode("utf-8", errors="replace")
    else:
        text = f"[binary document — {len(raw)} bytes, not injected as text]"
    meta = {
        "ref_id": ref_id, "filename": fname, "bytes": len(raw),
        "chars": len(text), "text": text[:DOC_TEXT_CAP],
    }
    (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return {"ref_id": ref_id, "filename": fname, "bytes": len(raw), "chars": len(text)}


@router.get("/docs")
def list_docs():
    out = []
    if CHAT_DOCS_DIR.exists():
        for d in sorted(CHAT_DOCS_DIR.iterdir(),
                        key=lambda p: p.stat().st_mtime, reverse=True):
            mp = d / "meta.json"
            if not mp.exists():
                continue
            m = json.loads(mp.read_text(encoding="utf-8"))
            out.append({k: m.get(k) for k in ("ref_id", "filename", "bytes", "chars")})
    return {"docs": out}


@router.delete("/docs/{ref_id}")
def delete_doc(ref_id: str):
    d = CHAT_DOCS_DIR / ref_id
    if d.exists():
        shutil.rmtree(d)
    return {"ok": True}

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_PROVIDER = "deepseek"

SYSTEM_PROMPT = """You are Salmon, the Business Process Automation Specialist copilot running inside Conductor — a desktop app for Luminize (a top-5 Amazon seller managing 80+ brands). You live next to a live process-discovery board, an automation engine (Asana/Google/HubSpot/Zapier/Make handoffs), AI workflow runs, and an SOP/runbook library — all visible through context injected into this conversation.

Your tone: direct, practical, no fluff — like a sharp ops colleague. Answer in the same language the user writes in.

What you do well:
- Process discovery: help scope vague business problems into shippable MVPs; quantify hours/errors/delays; push back when a process should be redesigned before it is automated.
- Automation design: propose trigger → condition → action chains (e.g. a completed Supply Chain task that opens a Catalog task with inputs pre-populated); advise on REST/webhook basics (auth, pagination, rate limits).
- AI integration: pick the right LLM workflow (feedback categorization, transcript summarization, document parsing, action extraction, SOP drafting) and judge where a human should review.
- Governance: draft SOPs/runbooks, define guardrails, validation, and exception handling.

In-app moves to suggest: log a process in Process Discovery, build an automation, run an AI workflow, search SOPs, connect an integration in Settings. When you don't know something, say so and suggest a concrete action in the app.

Keep answers under ~200 words unless asked for depth. Use markdown-lite (bold, code, short lists) — no huge tables."""


def _load_config() -> dict:
    cfg = {}
    if CONFIG_PATH.exists():
        try:
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            cfg = {}
    return {
        "provider": cfg.get("provider") or DEFAULT_PROVIDER,
        "base_url": (cfg.get("base_url") or DEFAULT_BASE_URL).rstrip("/"),
        "model": cfg.get("model") or DEFAULT_MODEL,
        "api_key": cfg.get("api_key") or os.environ.get("DEEPSEEK_API_KEY", ""),
        "llama_model": cfg.get("llama_model") or "",
        "llama_ctx": int(cfg.get("llama_ctx") or 4096),
        "llama_port": int(cfg.get("llama_port") or 8098),
    }


def _save_config(cfg: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def _context_block() -> str:
    """Compact live context injected into the system prompt each call."""
    try:
        import storage

        products = storage.count_products()
        checks = len(storage.list_checks(limit=2000))
        open_tasks = len(storage.list_tasks(limit=1000, status="open")) if hasattr(storage, "list_tasks") else 0
    except Exception:
        products = checks = open_tasks = 0
    try:
        from agents import list_agents

        agents = [a["id"] for a in list_agents()]
    except Exception:
        agents = []
    return (
        f"\n[LIVE CONTEXT] products={products} | checks={checks} | open_tasks={open_tasks} "
        f"| agents={','.join(agents)}\n"
    )


@router.get("/config")
def get_config():
    cfg = _load_config()
    try:
        from llama import list_models, server_status

        llama_models = list_models().get("models", [])
        llama_status = server_status()
    except Exception:
        llama_models = []
        llama_status = {}
    return {
        "configured": bool(cfg["api_key"]),
        "provider": cfg["provider"],
        "base_url": cfg["base_url"],
        "model": cfg["model"],
        "llama_model": cfg["llama_model"],
        "llama_ctx": cfg["llama_ctx"],
        "llama_port": cfg["llama_port"],
        "llama_models": [m["name"] for m in llama_models],
        "llama_running": llama_status.get("running", False),
        "llama_loaded": llama_status.get("model"),
    }


@router.post("/config")
def set_config(body: dict):
    cfg = _load_config()
    if "api_key" in body and body.get("api_key"):
        cfg["api_key"] = str(body["api_key"]).strip()
    if body.get("model"):
        cfg["model"] = str(body["model"]).strip()
    if body.get("base_url"):
        cfg["base_url"] = str(body["base_url"]).strip().rstrip("/")
    if body.get("provider") in ("deepseek", "llama"):
        cfg["provider"] = str(body["provider"])
    # LAW-style per-provider patches: {providers: {pid: {mode, baseUrl, defaultModelId, enabled}}}
    prov_patches = body.get("providers")
    if isinstance(prov_patches, dict):
        import providers as providers_mod

        for pid, patch in prov_patches.items():
            if pid not in providers_mod.HOSTED_PROVIDERS:
                continue
            if not isinstance(patch, dict):
                continue
            clean: dict = {}
            if "mode" in patch and patch["mode"] in ("direct", "proxy"):
                clean["mode"] = patch["mode"]
            if "baseUrl" in patch and patch["baseUrl"]:
                clean["baseUrl"] = str(patch["baseUrl"]).strip().rstrip("/")
            if "defaultModelId" in patch and patch["defaultModelId"]:
                clean["defaultModelId"] = str(patch["defaultModelId"]).strip()
            if "enabled" in patch and isinstance(patch["enabled"], bool):
                clean["enabled"] = patch["enabled"]
            if clean:
                providers_mod.set_provider_config(pid, clean)
    if "llama_model" in body:
        cfg["llama_model"] = str(body.get("llama_model") or "").strip()
    if body.get("llama_ctx"):
        try:
            cfg["llama_ctx"] = max(512, min(32768, int(body["llama_ctx"])))
        except (TypeError, ValueError):
            pass
    if body.get("llama_port"):
        try:
            cfg["llama_port"] = max(1024, min(65535, int(body["llama_port"])))
        except (TypeError, ValueError):
            pass
    _save_config(cfg)
    return {
        "ok": True,
        "configured": bool(cfg["api_key"]),
        "provider": cfg["provider"],
        "model": cfg["model"],
        "base_url": cfg["base_url"],
        "llama_model": cfg["llama_model"],
        "llama_ctx": cfg["llama_ctx"],
        "llama_port": cfg["llama_port"],
    }


@router.post("")
async def chat(body: dict):
    message = str(body.get("message") or "").strip()
    if not message:
        raise HTTPException(400, "message is required")
    history = body.get("history") or []
    if not isinstance(history, list):
        history = []
    history = [h for h in history if isinstance(h, dict) and h.get("role") in ("user", "assistant")][-12:]

    cfg = _load_config()
    provider = str(body.get("provider") or cfg["provider"] or "deepseek")
    model = str(body.get("model") or "").strip() or None
    api_key = str(body.get("api_key") or "").strip() or None

    # Toggled workspace skills + referenced documents -> extra system context
    extra = ""
    skills = body.get("skills") or []
    if isinstance(skills, list) and skills:
        try:
            from hub import list_cards
            cards = {c["name"].lower(): c for c in list_cards().get("cards", [])}
        except Exception:
            cards = {}
        lines = []
        for s in skills:
            s = str(s).strip()
            if not s:
                continue
            c = cards.get(s.lower())
            lines.append(f"- {c['name']}: {c.get('desc') or '(no description)'}" if c else f"- {s}")
        if lines:
            extra += ("\n[ACTIVE SKILLS — the user toggled these workspace skills for this "
                      "request; use their capabilities where relevant]\n" + "\n".join(lines) + "\n")
    doc_refs = body.get("docs") or []
    if isinstance(doc_refs, list) and doc_refs:
        parts = []
        for rid in doc_refs:
            mp = CHAT_DOCS_DIR / str(rid) / "meta.json"
            if not mp.exists():
                continue
            m = json.loads(mp.read_text(encoding="utf-8"))
            parts.append(f"--- {m['filename']} ---\n{m.get('text') or '(binary, not injected)'}")
        if parts:
            extra += ("\n[REFERENCED DOCUMENTS — quoted content the user attached; answer "
                      "grounded in it and cite the filename]\n" + "\n\n".join(parts) + "\n")

    messages = [{"role": "system", "content": SYSTEM_PROMPT + _context_block() + extra}]
    messages.extend(history)
    messages.append({"role": "user", "content": message})

    if provider == "llama":
        return _llama_chat(messages, cfg)

    import providers

    if provider not in providers.HOSTED_PROVIDERS:
        raise HTTPException(400, f"Unknown provider '{provider}' — choose one of {', '.join(providers.HOSTED_PROVIDERS)} or 'llama'.")

    def generate():
        started = time.time()
        usage_obj = None
        try:
            for ev in providers.stream_provider(provider, messages, model=model, api_key=api_key):
                if ev["type"] == "text":
                    yield ev["text"]
                elif ev["type"] == "thinking":
                    yield f"⧙THINK⧚{ev['text']}⧙/THINK⧚"
                elif ev["type"] == "usage":
                    usage_obj = ev
                elif ev["type"] == "error":
                    yield f"\n[ERROR] {ev['code']}: {ev['message']}"
        except ValueError as exc:
            yield f"\n[ERROR] {exc}"
        finally:
            if usage_obj:
                usage.record(
                    input_tokens=usage_obj.get("prompt_tokens") or 0,
                    output_tokens=usage_obj.get("completion_tokens") or 0,
                )
            elapsed = time.time() - started
            yield f"\n\n_({elapsed:.1f}s · {provider})_"

    return StreamingResponse(generate(), media_type="text/plain")


@router.get("/providers")
def list_providers():
    """LAW-style provider registry view: every known provider with key presence,
    mode, models and health. Only providers with keys (or proxy mode) are
    'configured' — the UI must never offer a target that 401s."""
    import providers

    out = []
    for p in providers.available_providers():
        if p["configured"]:
            adapter = providers.build_adapter(p["id"], providers.resolve_api_key(p["id"]))
            try:
                p["health"] = adapter.health() if adapter else {"healthy": False}
            except Exception as exc:
                p["health"] = {"healthy": False, "error": str(exc)}
        out.append(p)
    return {"providers": out}


@router.get("/keys")
def list_keys():
    import providers

    return {"keys": {pid: providers.has_key(pid) for pid in providers.HOSTED_PROVIDERS}}


@router.post("/keys")
def set_key(body: dict):
    """Store a provider key. `value` is base64; `encrypted: true` means it is a
    safeStorage ciphertext produced by the Electron main process (never
    decryptable by this backend)."""
    import providers

    pid = str(body.get("providerId") or "")
    if pid not in providers.HOSTED_PROVIDERS:
        raise HTTPException(400, f"Unknown provider '{pid}'")
    value = str(body.get("value") or "")
    if not value:
        raise HTTPException(400, "value is required")
    encrypted = bool(body.get("encrypted"))
    was_encrypted = providers.set_key(pid, value, encrypted)
    return {"ok": True, "providerId": pid, "encrypted": was_encrypted}


@router.delete("/keys/{provider_id}")
def delete_key(provider_id: str):
    import providers

    removed = providers.delete_key(provider_id)
    if not removed:
        raise HTTPException(404, f"No key stored for '{provider_id}'")
    return {"ok": True, "providerId": provider_id}


def _llama_chat(messages: list[dict], cfg: dict) -> StreamingResponse:
    """Route chat through the local llama.cpp server (auto-start if needed)."""
    from pathlib import Path

    import llama

    # ensure a server is up (reuse an existing one on our port range)
    port = llama._find_running_server()
    if port is None:
        llama.start_server({"model": cfg["llama_model"], "ctx": cfg["llama_ctx"], "port": cfg["llama_port"]})
        port = llama._find_running_server()

    model_path = llama.resolve_model(cfg["llama_model"])
    model_name = model_path.name

    def generate():
        started = time.time()
        try:
            for delta in llama.stream_chat(messages, model_name, port=port, max_tokens=1200):
                yield delta
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
            yield f"\n[ERROR] llama-server {exc.code}: {detail}"
        except Exception as exc:
            yield f"\n[ERROR] {type(exc).__name__}: {exc}"
        finally:
            u = llama.take_last_usage()
            if u:
                usage.record(
                    input_tokens=u.get("prompt_tokens") or 0,
                    output_tokens=u.get("completion_tokens") or 0,
                )
            elapsed = time.time() - started
            yield f"\n\n_({elapsed:.1f}s · local llama)_"

    return StreamingResponse(generate(), media_type="text/plain")
