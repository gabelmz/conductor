"""Conductor — multi-provider chat registry (ported from LAW's provider layer).

Brings LAW's provider architecture into Conductor's FastAPI backend:

- Four hosted providers: anthropic, openai, grok (x.ai), deepseek — each with a
  default base URL and env-var fallback for the key.
- Per-provider config in `data/provider-config.json`:
  {providerId: {baseUrl, mode: 'direct'|'proxy', defaultModelId, enabled}}
- Provider keys in `data/provider-keys.json`:
  {providerId: {value: <base64>, encrypted: bool, updatedAt}}.
  `encrypted: true` means the value is a safeStorage ciphertext produced by the
  Electron main process (LAW's OS-keychain design); the backend cannot decrypt
  those, so the renderer injects the decrypted key per-request via IPC. Keys
  written in plain (dev mode, no Electron) are base64 utf-8.
- Registry builds only providers that are enabled AND have a key (or run in
  proxy mode) — LAW's "provider with no key is left out" rule, so the model
  picker never offers a target that 401s.
- Adapters normalize every vendor stream to a single event shape:
  {"type": "text", "text": ...} | {"type": "thinking", "text": ...} |
  {"type": "usage", "prompt_tokens": n, "completion_tokens": n} |
  {"type": "error", "code": ..., "message": ...}
"""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from storage import DATA_DIR

CONFIG_PATH = DATA_DIR / "provider-config.json"
KEYS_PATH = DATA_DIR / "provider-keys.json"

HOSTED_PROVIDERS: dict[str, dict] = {
    "anthropic": {
        "label": "Anthropic (Claude)",
        "base_url": "https://api.anthropic.com",
        "env_key": "ANTHROPIC_API_KEY",
        "default_model": "claude-sonnet-4-5",
        "kind": "anthropic",
    },
    "openai": {
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "env_key": "OPENAI_API_KEY",
        "default_model": "gpt-4o-mini",
        "kind": "openai-compatible",
    },
    "grok": {
        "label": "Grok (x.ai)",
        "base_url": "https://api.x.ai/v1",
        "env_key": "XAI_API_KEY",
        "default_model": "grok-4",
        "kind": "openai-compatible",
    },
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "env_key": "DEEPSEEK_API_KEY",
        "default_model": "deepseek-v4-flash",
        "kind": "openai-compatible",
    },
}

# ---------------------------------------------------------------------------
# persistence (config + keys)
# ---------------------------------------------------------------------------
def _read_json(path: Path) -> dict:
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {}


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def read_provider_config(provider_id: str) -> dict:
    return _read_json(CONFIG_PATH).get(provider_id) or {}


def set_provider_config(provider_id: str, patch: dict) -> dict:
    file = _read_json(CONFIG_PATH)
    file[provider_id] = {**file.get(provider_id, {}), **patch}
    _write_json(CONFIG_PATH, file)
    return file[provider_id]


def read_key_entry(provider_id: str) -> dict | None:
    return _read_json(KEYS_PATH).get(provider_id)


def set_key(provider_id: str, value_b64: str, encrypted: bool) -> bool:
    file = _read_json(KEYS_PATH)
    file[provider_id] = {
        "value": value_b64,
        "encrypted": bool(encrypted),
        "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    _write_json(KEYS_PATH, file)
    return bool(encrypted)


def delete_key(provider_id: str) -> bool:
    file = _read_json(KEYS_PATH)
    if provider_id not in file:
        return False
    del file[provider_id]
    _write_json(KEYS_PATH, file)
    return True


def has_key(provider_id: str) -> bool:
    return provider_id in _read_json(KEYS_PATH)


def resolve_api_key(provider_id: str, request_key: str | None = None) -> str | None:
    """Key resolution order: per-request key (renderer IPC decrypted) → stored
    plaintext (base64, encrypted=False) → env var. Encrypted-at-rest entries
    cannot be decrypted here — the renderer supplies them per request."""
    if request_key:
        return request_key.strip()
    entry = read_key_entry(provider_id)
    if entry and not entry.get("encrypted") and entry.get("value"):
        try:
            return base64.b64decode(entry["value"]).decode("utf-8")
        except Exception:
            return None
    env = HOSTED_PROVIDERS.get(provider_id, {}).get("env_key")
    if env:
        return os.environ.get(env) or None
    return None


# ---------------------------------------------------------------------------
# SSE parsing (shared by openai-compatible + proxy)
# ---------------------------------------------------------------------------
def parse_sse_lines(resp) -> list[dict]:
    """Collect `data: {...}` frames from an SSE response body into dicts."""
    out = []
    buf = b""
    for raw in resp:
        buf += raw
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            text = line.decode("utf-8", errors="replace").strip()
            if text.startswith("data:"):
                payload = text[5:].strip()
                if payload == "[DONE]":
                    return out
                try:
                    out.append(json.loads(payload))
                except json.JSONDecodeError:
                    continue
    # trailing frame without newline
    if buf:
        text = buf.decode("utf-8", errors="replace").strip()
        if text.startswith("data:"):
            payload = text[5:].strip()
            if payload != "[DONE]":
                try:
                    out.append(json.loads(payload))
                except json.JSONDecodeError:
                    pass
    return out


def _http_error_detail(exc: urllib.error.HTTPError) -> str:
    try:
        return exc.read().decode("utf-8", errors="replace")[:300]
    except Exception:
        return str(exc)


# ---------------------------------------------------------------------------
# adapters
# ---------------------------------------------------------------------------
class OpenAICompatAdapter:
    """openai / grok / deepseek — /chat/completions SSE with reasoning support."""

    def __init__(self, provider_id: str, base_url: str, api_key: str, default_model: str):
        self.id = provider_id
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.default_model = default_model

    def list_models(self) -> list[dict]:
        req = urllib.request.Request(
            f"{self.base_url}/models",
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=6) as r:
                data = json.loads(r.read().decode("utf-8"))
            return [{"id": m.get("id"), "providerId": self.id} for m in data.get("data", []) if m.get("id")]
        except Exception:
            return [{"id": self.default_model, "providerId": self.id}]

    def health(self) -> dict:
        start = time.time()
        try:
            self.list_models()
            return {"healthy": True, "latencyMs": int((time.time() - start) * 1000)}
        except Exception as exc:
            return {"healthy": False, "latencyMs": int((time.time() - start) * 1000),
                    "error": str(exc)}

    def stream_chat(self, messages: list[dict], model: str, max_tokens: int = 1200,
                    temperature: float = 0.6):
        """Yields normalized events from an OpenAI-compatible streaming chat."""
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                for obj in parse_sse_lines(resp):
                    if obj.get("usage"):
                        yield {"type": "usage",
                               "prompt_tokens": obj["usage"].get("prompt_tokens") or 0,
                               "completion_tokens": obj["usage"].get("completion_tokens") or 0}
                    choices = obj.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    if delta.get("reasoning_content"):
                        yield {"type": "thinking", "text": delta["reasoning_content"]}
                    if delta.get("content"):
                        yield {"type": "text", "text": delta["content"]}
        except urllib.error.HTTPError as exc:
            yield {"type": "error", "code": f"HTTP_{exc.code}", "message": _http_error_detail(exc)}
        except Exception as exc:
            yield {"type": "error", "code": type(exc).__name__, "message": str(exc)}


class AnthropicAdapter:
    """Native Anthropic Messages API — content blocks, thinking deltas, usage."""

    API_VERSION = "2023-06-01"

    def __init__(self, provider_id: str, base_url: str, api_key: str, default_model: str):
        self.id = provider_id
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.default_model = default_model

    def list_models(self) -> list[dict]:
        req = urllib.request.Request(
            f"{self.base_url}/v1/models",
            headers={"x-api-key": self.api_key, "anthropic-version": self.API_VERSION},
        )
        try:
            with urllib.request.urlopen(req, timeout=6) as r:
                data = json.loads(r.read().decode("utf-8"))
            return [{"id": m.get("id"), "providerId": self.id} for m in data.get("data", []) if m.get("id")]
        except Exception:
            return [{"id": self.default_model, "providerId": self.id}]

    def health(self) -> dict:
        start = time.time()
        try:
            self.list_models()
            return {"healthy": True, "latencyMs": int((time.time() - start) * 1000)}
        except Exception as exc:
            return {"healthy": False, "latencyMs": int((time.time() - start) * 1000),
                    "error": str(exc)}

    def stream_chat(self, messages: list[dict], model: str, max_tokens: int = 1200,
                    temperature: float = 0.6):
        payload = {
            "model": model,
            "messages": [m for m in messages if m.get("role") != "system"],
            "system": "\n".join(m["content"] for m in messages if m.get("role") == "system"),
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        req = urllib.request.Request(
            f"{self.base_url}/v1/messages",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": self.API_VERSION,
            },
            method="POST",
        )
        in_thinking = False
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                event_name = None
                buf = b""
                for raw in resp:
                    buf += raw
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        text = line.decode("utf-8", errors="replace").strip()
                        if text.startswith("event:"):
                            event_name = text[6:].strip()
                        elif text.startswith("data:"):
                            payload = text[5:].strip()
                            try:
                                obj = json.loads(payload)
                            except json.JSONDecodeError:
                                event_name = None
                                continue
                            if obj.get("type") == "content_block_start":
                                block = obj.get("content_block") or {}
                                in_thinking = block.get("type") == "thinking"
                            elif obj.get("type") == "content_block_delta":
                                delta = obj.get("delta") or {}
                                if delta.get("type") == "thinking_delta":
                                    yield {"type": "thinking", "text": delta.get("thinking", "")}
                                elif delta.get("type") == "text_delta":
                                    yield {"type": "text", "text": delta.get("text", "")}
                            elif obj.get("type") == "message_delta":
                                usage = obj.get("usage") or {}
                                yield {"type": "usage",
                                       "prompt_tokens": usage.get("input_tokens") or 0,
                                       "completion_tokens": usage.get("output_tokens") or 0}
                            event_name = None
        except urllib.error.HTTPError as exc:
            yield {"type": "error", "code": f"HTTP_{exc.code}", "message": _http_error_detail(exc)}
        except Exception as exc:
            yield {"type": "error", "code": type(exc).__name__, "message": str(exc)}


class ProxyAdapter:
    """LAW's proxy mode: POST to a Supabase edge function that normalizes every
    vendor stream server-side. Auth via env JWT/service key (loud failure when
    unprovisioned, matching LAW's default resolver)."""

    def __init__(self, provider_id: str, function_url: str, auth_headers: dict, default_model: str):
        self.id = provider_id
        self.function_url = function_url.rstrip("/")
        self.auth_headers = auth_headers
        self.default_model = default_model

    def list_models(self) -> list[dict]:
        return [{"id": self.default_model, "providerId": self.id}] if self.default_model else []

    def health(self) -> dict:
        if not self.auth_headers:
            return {"healthy": False, "error": "Proxy mode has no Supabase auth configured."}
        return {"healthy": True}

    def stream_chat(self, messages: list[dict], model: str, max_tokens: int = 1200,
                    temperature: float = 0.6):
        payload = {"providerId": self.id, "modelId": model, "messages": messages}
        req = urllib.request.Request(
            self.function_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={**self.auth_headers, "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                for obj in parse_sse_lines(resp):
                    ev_type = obj.get("type")
                    if ev_type == "content_block_delta" and (obj.get("delta") or {}).get("type") == "text_delta":
                        yield {"type": "text", "text": obj["delta"]["text"]}
                    elif ev_type == "thinking_delta":
                        yield {"type": "thinking", "text": obj.get("delta", {}).get("text", "")}
                    elif ev_type == "usage":
                        yield {"type": "usage",
                               "prompt_tokens": obj.get("promptTokens") or 0,
                               "completion_tokens": obj.get("completionTokens") or 0}
                    elif ev_type == "error":
                        yield {"type": "error", "code": obj.get("error", {}).get("code", "PROXY_ERROR"),
                               "message": obj.get("error", {}).get("message", "proxy chat failed")}
        except urllib.error.HTTPError as exc:
            yield {"type": "error", "code": f"HTTP_{exc.code}", "message": _http_error_detail(exc)}
        except Exception as exc:
            yield {"type": "error", "code": type(exc).__name__, "message": str(exc)}


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------
def _proxy_auth_headers() -> dict:
    jwt = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_ANON_KEY")
    anon = os.environ.get("SUPABASE_ANON_KEY")
    if not jwt:
        return {}
    headers = {"authorization": f"Bearer {jwt}"}
    if anon:
        headers["apikey"] = anon
    return headers


def build_adapter(provider_id: str, api_key: str | None) -> object | None:
    """Construct the adapter for a provider given its resolved key. Returns
    None when the provider must be left out of the registry (no key, not
    proxy) — callers report it as 'add a key' instead of a 401."""
    meta = HOSTED_PROVIDERS.get(provider_id)
    if not meta:
        return None
    cfg = read_provider_config(provider_id)
    mode = cfg.get("mode") or "direct"
    base_url = (cfg.get("baseUrl") or meta["base_url"]).rstrip("/")
    default_model = cfg.get("defaultModelId") or meta["default_model"]

    if mode == "proxy":
        auth = _proxy_auth_headers()
        if not auth:
            return None
        return ProxyAdapter(provider_id, base_url, auth, default_model)
    if not api_key:
        return None
    if meta["kind"] == "anthropic":
        return AnthropicAdapter(provider_id, base_url, api_key, default_model)
    return OpenAICompatAdapter(provider_id, base_url, api_key, default_model)


def registry() -> dict[str, object]:
    """ProviderId → adapter for every enabled+keyed provider (llama is added
    by chat.py's existing path — it has no key)."""
    out: dict[str, object] = {}
    for pid in HOSTED_PROVIDERS:
        cfg = read_provider_config(pid)
        if cfg.get("enabled") is False:
            continue
        if cfg.get("mode") == "proxy":
            adapter = build_adapter(pid, None)
            if adapter:
                out[pid] = adapter
            continue
        key = resolve_api_key(pid)
        adapter = build_adapter(pid, key)
        if adapter:
            out[pid] = adapter
    return out


def available_providers() -> list[dict]:
    """UI-facing list: every known provider with config, key presence, models."""
    reg = registry()
    out = []
    for pid, meta in HOSTED_PROVIDERS.items():
        cfg = read_provider_config(pid)
        key = resolve_api_key(pid)
        has = bool(key) or (cfg.get("mode") == "proxy" and bool(_proxy_auth_headers()))
        models = []
        adapter = reg.get(pid)
        if adapter:
            try:
                models = adapter.list_models()
            except Exception:
                models = [{"id": cfg.get("defaultModelId") or meta["default_model"], "providerId": pid}]
        out.append({
            "id": pid,
            "label": meta["label"],
            "mode": cfg.get("mode") or "direct",
            "baseUrl": cfg.get("baseUrl") or meta["base_url"],
            "defaultModelId": cfg.get("defaultModelId") or meta["default_model"],
            "enabled": cfg.get("enabled", True),
            "hasKey": has,
            "configured": pid in reg,
            "models": models,
        })
    return out


def stream_provider(provider_id: str, messages: list[dict], model: str | None = None,
                    api_key: str | None = None, max_tokens: int = 1200,
                    temperature: float = 0.6):
    """Stream normalized events from a hosted provider. Raises HTTPException-ish
    ValueError for unregistered providers (no key / disabled)."""
    key = resolve_api_key(provider_id, api_key)
    adapter = build_adapter(provider_id, key)
    if adapter is None:
        raise ValueError(
            f"Provider '{provider_id}' is not configured. Add an API key in Settings → AI Providers."
        )
    if not model:
        cfg = read_provider_config(provider_id)
        model = cfg.get("defaultModelId") or HOSTED_PROVIDERS[provider_id]["default_model"]
    yield from adapter.stream_chat(messages, model, max_tokens=max_tokens, temperature=temperature)
