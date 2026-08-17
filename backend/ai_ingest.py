"""AI catalog pass — enrich/clean/categorize parsed products and surface
compliance, inventory, and data-quality flags plus recommendations.

Runs as a background job (kind='ai_process') after a file finishes parsing.
Uses the same hosted-provider plumbing as chat. Graceful when no AI key is
configured: the job reports an explicit error instead of failing silently.
"""
from __future__ import annotations

import json
import re
import threading

import storage

AI_BATCH = 10  # products per model call


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    return text.strip()


def _extract_json(text: str):
    text = _strip_code_fences(text)
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except Exception:
        return None


AI_SYSTEM = """You are the catalog AI inside Conductor, a desktop app for an Amazon seller.
You clean and enrich product catalog data. Respond with STRICT JSON ONLY — an array of
objects, one per input product, with these keys (include only ones that apply):
- "sku": echo the product's sku back exactly
- "category": a cleaner category string if the current one is missing, 'general', or wrong
- "cleaned_name": a cleaned product name if the raw name is messy
- "attributes": an object of extracted/normalized attributes (material, color, size, weight,
  batteries, voltage, certifications, etc.) — merge, don't invent
- "flags": array of {"type": "compliance"|"inventory"|"data"|"quality",
  "severity": "info"|"warning"|"blocker", "message": "..."} — flag compliance gaps
  (CE/FCC/RoHS/REACH/GPSR/Prop 65), inventory discrepancies (missing stock/price fields),
  or data problems
- "recommendations": array of short strings (e.g. Amazon flat-file field fixes, listing improvements)

No prose, no markdown, no commentary — JSON only."""


def ai_process(upload_id: str) -> dict:
    meta = storage.get_file_by_upload(upload_id)
    if not meta:
        raise KeyError(f"Unknown upload_id {upload_id}")
    if meta["status"] != "done":
        raise ValueError("File must finish parsing (status=done) before the AI pass")
    file_id = meta["id"]
    job_id = storage.create_job("ai_process", file_id)
    storage.update_job(job_id, status="running", progress=0, message="AI processing catalog…")
    threading.Thread(target=_ai_job, args=(job_id, file_id), daemon=True).start()
    return {"upload_id": upload_id, "job_id": job_id, "status": "ai_processing"}


def _provider_ready() -> tuple[str, str | None, str] | None:
    """Return (provider, model, api_key) when a hosted provider key exists."""
    try:
        from chat import _load_config
        import providers

        cfg = _load_config()
        provider = str(cfg.get("provider") or "deepseek")
        if provider == "llama" or provider not in providers.HOSTED_PROVIDERS:
            return None
        api_key = providers.resolve_api_key(provider, None)
        if not api_key:
            return None
        model = str(cfg.get("model") or "").strip() or None
        return provider, model, api_key
    except Exception:
        return None


def _ai_job(job_id: int, file_id: int) -> None:
    try:
        products = storage.list_products_by_file(file_id)
        if not products:
            raise ValueError("No products found for this file")
        ready = _provider_ready()
        if not ready:
            raise ValueError("No AI provider key configured — configure one in Settings → AI Chat, then retry")
        provider, model, api_key = ready
        import providers

        storage.clear_ai_findings(file_id)
        total = len(products)
        findings = 0
        enriched = 0
        for start in range(0, total, AI_BATCH):
            batch = products[start:start + AI_BATCH]
            payload = [{
                "sku": p["sku"], "name": p["name"],
                "category": p["category"], "market": p["market"],
                "attributes": p["attributes"],
            } for p in batch]
            messages = [
                {"role": "system", "content": AI_SYSTEM},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ]
            text = ""
            for ev in providers.stream_provider(provider, messages, model=model, api_key=api_key):
                if ev["type"] == "text":
                    text += ev["text"]
                elif ev["type"] == "error":
                    raise ValueError(f"Provider error: {ev.get('code')} {ev.get('message')}")
            results = _extract_json(text)
            if results is None:
                raise ValueError("AI returned unparseable output (expected a JSON array)")
            for res in results:
                if not isinstance(res, dict) or not res.get("sku"):
                    continue
                pid = next((p["id"] for p in batch if p["sku"] == res["sku"]), None)
                if pid is None:
                    continue
                changed = False
                category = res.get("category")
                if isinstance(category, str) and category.strip():
                    cat = category.strip().lower()
                    if cat not in ("general", "n/a", "unknown", ""):
                        storage.update_product(pid, category=category.strip())
                        changed = True
                cleaned = res.get("cleaned_name")
                if isinstance(cleaned, str) and cleaned.strip():
                    storage.update_product(pid, name=cleaned.strip())
                    changed = True
                attrs = res.get("attributes")
                if isinstance(attrs, dict) and attrs:
                    cur = storage.get_product(pid)["attributes"]
                    storage.update_product(pid, attributes={**cur, **attrs})
                    changed = True
                for f in res.get("flags") or []:
                    if isinstance(f, dict) and f.get("message"):
                        storage.save_ai_finding(
                            file_id, pid, "flag",
                            f"{f.get('type', 'flag')} · {f.get('severity', 'info')}",
                            str(f["message"]),
                        )
                        findings += 1
                for r in res.get("recommendations") or []:
                    if isinstance(r, str) and r.strip():
                        storage.save_ai_finding(file_id, pid, "recommendation",
                                                "recommendation", r.strip())
                        findings += 1
                if changed:
                    enriched += 1
            storage.update_job(job_id, progress=round(min(start + AI_BATCH, total) / total * 100, 1))
        storage.update_job(
            job_id, status="done", progress=100,
            message=f"AI pass complete — {enriched}/{total} products enriched, {findings} findings.",
        )
    except Exception as exc:
        storage.update_job(job_id, status="error", message=str(exc))
