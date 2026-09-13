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

from fastapi import APIRouter, HTTPException, UploadFile, File, Query
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

DEFAULT_SYSTEM_PROMPT = """You are Conductor Assistant, the user copilot running inside Conductor — a desktop workbench for Luminize (managing 80+ Amazon brands and multi-channel marketplaces).

Your primary role:
- Guide and assist users in navigating Conductor, managing tasks, inspecting catalog data, running AI workflows, and automating operations.
- Act as a thoughtful, articulate, user-focused assistant.
- Before making structural changes to the app, altering catalog schemas, or modifying automation pipelines, consult or delegate to specialist agents like Franky (Catalog Architect & Operations Engineer) or trigger the appropriate specialized agent workflow.

Specialist Agents Available:
- Franky: Senior Catalog Architect & Automation Specialist (multi-format parsing, Keepa live queries, Asana sync, catalog schemas).
- Asana Harvester: Asana task, subtask, story, and custom field synchronization.
- Keepa Analyst: Price history, Buy Box tracking, and sales rank analysis.
- Flow Canvas & Asana Rules: Node-graph flow builders and trigger-action automations.

Tone: Helpful, clear, proactive, and practical. Keep responses focused and concise unless detailed depth is requested."""

DEFAULT_LLAMA_SYSTEM_PROMPT = """You are the Conductor Local Assistant — a small, fully offline model that runs on this machine (no cloud, no API key) via Conductor's bundled llama.cpp engine.

Your job is narrow and practical:
- Log and summarize edits the user or the app just made — what changed, in plain language.
- Answer simple, quick questions about the app or the current workspace.
- Report and explain errors in plain language: what broke, the likely cause, and the next concrete step to try.
- Draft and clean up short documentation notes (README snippets, changelog lines, task notes).

You are not the primary Conductor Assistant (that's the cloud model) — don't attempt deep catalog analysis, multi-step planning, or long-form research. Keep answers short, direct, and actionable. If a request is clearly outside this scope, say so and suggest switching to the main Conductor Assistant."""


def _load_config() -> dict:
    cfg = {}
    if CONFIG_PATH.exists():
        try:
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            cfg = {}
    provider = cfg.get("provider")
    model = cfg.get("model")
    if not provider or not model:
        # No explicit selection saved yet — resolve through the spine's
        # active-state layer (user config > preferred > default) instead of a
        # locally hardcoded constant, so this can never drift out of sync with
        # what providers.py actually declares for a given provider.
        from spine.active import resolve_active_chat_target

        resolved = resolve_active_chat_target(requested_provider=provider, requested_model=model)
        provider = provider or resolved["provider"]
        model = model or resolved["model"]
    return {
        "provider": provider,
        "base_url": (cfg.get("base_url") or DEFAULT_BASE_URL).rstrip("/"),
        "model": model,
        "api_key": cfg.get("api_key") or os.environ.get("DEEPSEEK_API_KEY", ""),
        "system_prompt": cfg.get("system_prompt") or DEFAULT_SYSTEM_PROMPT,
        "llama_system_prompt": cfg.get("llama_system_prompt") or DEFAULT_LLAMA_SYSTEM_PROMPT,
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
        from llama import discover_models, server_status

        llama_models = discover_models().get("models", [])
        llama_status = server_status()
    except Exception:
        llama_models = []
        llama_status = {}
    return {
        "configured": bool(cfg["api_key"]),
        "provider": cfg["provider"],
        "base_url": cfg["base_url"],
        "model": cfg["model"],
        "system_prompt": cfg.get("system_prompt") or DEFAULT_SYSTEM_PROMPT,
        "llama_system_prompt": cfg.get("llama_system_prompt") or DEFAULT_LLAMA_SYSTEM_PROMPT,
        "llama_model": cfg["llama_model"],
        "llama_ctx": cfg["llama_ctx"],
        "llama_port": cfg["llama_port"],
        # `id` (bare filename, no extension) is the resolvable identifier — matches
        # the Settings picker's <option value> (GET /api/llama/discover) and what
        # llama.resolve_model() now knows how to find outside MODELS_DIR too.
        "llama_models": [m["id"] for m in llama_models],
        "llama_running": llama_status.get("running", False),
        "llama_loaded": llama_status.get("model"),
    }


@router.post("/config")
def set_config(body: dict):
    cfg = _load_config()
    if "api_key" in body and body.get("api_key"):
        cfg["api_key"] = str(body["api_key"]).strip()
    if body.get("base_url"):
        cfg["base_url"] = str(body["base_url"]).strip().rstrip("/")
    if "system_prompt" in body:
        cfg["system_prompt"] = str(body.get("system_prompt") or "").strip() or DEFAULT_SYSTEM_PROMPT
    if "llama_system_prompt" in body:
        cfg["llama_system_prompt"] = str(body.get("llama_system_prompt") or "").strip() or DEFAULT_LLAMA_SYSTEM_PROMPT
    import providers as providers_mod

    if body.get("provider") in providers_mod.HOSTED_PROVIDERS or body.get("provider") == "llama":
        cfg["provider"] = str(body["provider"])
    requested_model = str(body.get("model") or "").strip()
    if requested_model:
        if cfg["provider"] != "llama" and not providers_mod.model_is_allowed(cfg["provider"], requested_model):
            raise HTTPException(400, f"Model '{requested_model}' is not available for provider '{cfg['provider']}'.")
        cfg["model"] = requested_model
    elif cfg["provider"] != "llama" and not providers_mod.model_is_allowed(cfg["provider"], cfg.get("model") or ""):
        # Do not retain a known model from the previously selected provider.
        cfg["model"] = providers_mod.read_provider_config(cfg["provider"]).get("defaultModelId") or providers_mod.HOSTED_PROVIDERS[cfg["provider"]]["default_model"]
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
        "system_prompt": cfg["system_prompt"],
        "llama_system_prompt": cfg["llama_system_prompt"],
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

    if provider == "llama":
        sys_prompt = cfg.get("llama_system_prompt") or DEFAULT_LLAMA_SYSTEM_PROMPT
    else:
        sys_prompt = cfg.get("system_prompt") or DEFAULT_SYSTEM_PROMPT
    messages = [{"role": "system", "content": sys_prompt + _context_block() + extra}]
    messages.extend(history)
    messages.append({"role": "user", "content": message})

    if provider == "llama":
        return _llama_chat(messages, cfg)

    import providers

    if provider not in providers.HOSTED_PROVIDERS:
        raise HTTPException(400, f"Unknown provider '{provider}' — choose one of {', '.join(providers.HOSTED_PROVIDERS)} or 'llama'.")
    if model and not providers.model_is_allowed(provider, model):
        raise HTTPException(400, f"Model '{model}' is not available for provider '{provider}'.")

    def generate():
        import itertools

        started = time.time()
        usage_obj = None
        active_provider = provider
        try:
            events = providers.stream_provider(active_provider, messages, model=model, api_key=api_key)
            first = next(events, None)
            if first is not None and first["type"] == "error":
                # Outright failure before any text reached the user — retry once
                # against the spine's configured fallback target rather than
                # surfacing a bare error. A failure partway through a stream
                # (after text has already been yielded) is never retried here;
                # see the loop below, which only ever consumes `events` once.
                from spine.active import resolve_fallback_target

                fallback = resolve_fallback_target(exclude_provider=active_provider)
                if fallback:
                    yield f"[falling back to {fallback['provider']}/{fallback['model']}]\n"
                    active_provider = fallback["provider"]
                    events = providers.stream_provider(active_provider, messages, model=fallback["model"], api_key=None)
                    first = next(events, None)
            for ev in itertools.chain([first] if first is not None else [], events):
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
            yield f"\n\n_({elapsed:.1f}s · {active_provider})_"

    return StreamingResponse(generate(), media_type="text/plain")


@router.get("/providers")
def list_providers():
    """LAW-style provider registry view: every known provider with key presence,
    mode, models and health. Only providers with keys (or proxy mode) are
    'configured' — the UI must never offer a target that 401s."""
    import providers
    from concurrent.futures import ThreadPoolExecutor

    out = list(providers.available_providers())
    configured = [p for p in out if p["configured"]]

    def _check(p: dict) -> dict:
        adapter = providers.build_adapter(p["id"], providers.resolve_api_key(p["id"]))
        try:
            return adapter.health() if adapter else {"healthy": False}
        except Exception as exc:
            return {"healthy": False, "error": str(exc)}

    # Each health() call is a blocking network round-trip (up to a several-second timeout) —
    # doing them one after another made every Settings > AI Providers open take as long as the
    # sum of every configured provider's check. Run them concurrently instead.
    if configured:
        with ThreadPoolExecutor(max_workers=len(configured)) as pool:
            healths = list(pool.map(_check, configured))
        for p, health in zip(configured, healths):
            p["health"] = health

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


@router.get("/models")
def list_all_models(provider: str | None = None, all_providers: bool = Query(False, alias="all")):
    """List models for the selected provider, or all configured providers with `?all=true`."""
    import providers

    cfg = _load_config()
    selected_provider = str(provider or cfg.get("provider") or "deepseek")
    if not all_providers:
        if selected_provider == "llama":
            try:
                from llama import discover_models
                # discover_models() scans every known local install (Conductor's own
                # models/, Ollama, LM Studio, Jan/Atomic Chat) — not just MODELS_DIR —
                # so models installed outside Conductor are actually searchable here.
                # `id` is what llama.resolve_model() now knows how to resolve for any
                # of them (see llama.py's discovered-model fallback).
                models = [
                    {
                        "id": m.get("id"),
                        "provider": "llama",
                        "providerId": "llama",
                        "provider_label": "Local llama",
                        "source": "local",
                        "sizeBytes": m.get("sizeBytes"),
                        "sourceDir": m.get("sourceDir"),
                        "kind": m.get("kind"),
                    }
                    for m in discover_models().get("models", []) if m.get("id")
                ]
            except Exception:
                models = []
            return {"providerId": "llama", "models": models, "source": "local"}
        try:
            catalog, source = providers.list_provider_models(selected_provider)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        models = [
            {**model, "provider": selected_provider, "provider_label": providers.HOSTED_PROVIDERS[selected_provider]["label"]}
            for model in catalog
        ]
        return {"providerId": selected_provider, "models": models, "source": source}

    models = []
    for p in providers.available_providers():
        if p.get("configured"):
            for m in p.get("models") or []:
                models.append({
                    "id": m["id"],
                    "provider": p["id"],
                    "provider_label": p["label"],
                })
    return {"providerId": None, "models": models, "source": "all-configured"}


@router.post("/catalog/refresh")
def refresh_model_catalog(body: dict | None = None):
    """Re-pull model lists FROM PROVIDER ENDPOINTS. Backs the Refresh button.

    Every entry reports where its list actually came from, so the UI can tell
    a live endpoint pull apart from an unconfigured provider's placeholder.
    """
    import providers

    body = body or {}
    requested = body.get("providers") or body.get("provider")
    if isinstance(requested, str):
        requested = [requested]
    results = providers.refresh_catalog(requested)
    return {
        "providers": results,
        "counts": {
            "endpoint": sum(1 for r in results.values() if r["source"] == "endpoint"),
            "error": sum(1 for r in results.values() if r["source"] == "error"),
            "curated": sum(1 for r in results.values() if r["source"] == "curated"),
        },
        "totalModels": sum(len(r["models"]) for r in results.values()),
    }


@router.get("/catalog")
def get_model_catalog():
    """Last pulled catalog, per provider, with provenance and timestamps."""
    import providers

    return {"providers": providers.read_catalog_cache()}


@router.post("/embeddings")
@router.post("/embed")
async def create_embeddings(body: dict):
    """Generate embeddings using the configured or requested provider."""
    input_val = body.get("input") or body.get("text")
    if not input_val:
        raise HTTPException(400, "'input' or 'text' parameter is required")

    cfg = _load_config()
    provider = str(body.get("provider") or cfg.get("provider") or "openai")
    model = body.get("model") or None
    api_key = str(body.get("api_key") or "").strip() or None

    import providers as providers_mod

    key = providers_mod.resolve_api_key(provider, api_key)
    adapter = providers_mod.build_adapter(provider, key)
    if not adapter:
        raise HTTPException(400, f"Provider '{provider}' is not configured or missing API key.")

    if not hasattr(adapter, "embed"):
        raise HTTPException(400, f"Provider '{provider}' does not support embeddings.")

    try:
        res = adapter.embed(input_val, model=model)
        return res
    except Exception as exc:
        raise HTTPException(500, f"Embedding generation failed: {exc}")


def _llama_chat(messages: list[dict], cfg: dict) -> StreamingResponse:
    """Route chat through the local llama.cpp server (auto-start if needed).

    Lazily provisions the bundled default local model on first actual use —
    it is never bundled in the installer and never downloaded at app startup,
    only fetched the first time someone actually talks to the local assistant
    with no model configured yet.
    """
    from pathlib import Path

    import llama

    if not cfg.get("llama_model"):
        state = llama.ensure_default_model()
        if state["status"] != "ready":
            def waiting():
                pct = state.get("progress", 0)
                yield (
                    "Setting up the local assistant for the first time — downloading its "
                    f"model in the background ({pct}% so far). This happens once; send your "
                    "message again in a minute or two."
                )
            return StreamingResponse(waiting(), media_type="text/plain")
        cfg["llama_model"] = state["path"]
        _save_config(cfg)

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
