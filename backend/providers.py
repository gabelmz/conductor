"""Conductor — multi-provider chat & embedding registry.

Brings multi-provider architecture into Conductor's FastAPI backend:
- Presets for 22 top providers: OpenAI, Anthropic, Google Gemini, OpenRouter, DeepSeek,
  xAI (Grok), HuggingFace, Venice AI, Groq, Together AI, Mistral AI, Perplexity AI,
  Fireworks AI, Cohere, Replicate, SiliconFlow, Qwen (DashScope), Novita AI, Ollama,
  LM Studio, Moonshot AI, 01.AI.
- Per-provider config in `data/provider-config.json`:
  {providerId: {baseUrl, mode: 'direct'|'proxy', defaultModelId, enabled}}
- Provider keys in `data/provider-keys.json`:
  {providerId: {value: <base64>, encrypted: bool, updatedAt}}.
- Full models list, chat/completions (SSE with reasoning support), and embeddings support.
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
    "openai": {
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "env_key": "OPENAI_API_KEY",
        "default_model": "gpt-4o-mini",
        "default_embedding_model": "text-embedding-3-small",
        "kind": "openai-compatible",
    },
    "anthropic": {
        "label": "Anthropic (Claude)",
        "base_url": "https://api.anthropic.com",
        "env_key": "ANTHROPIC_API_KEY",
        "default_model": "claude-3-7-sonnet-20250219",
        "default_embedding_model": "",
        "kind": "anthropic",
    },
    "gemini": {
        "label": "Google Gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "env_key": "GEMINI_API_KEY",
        "default_model": "gemini-2.0-flash",
        "default_embedding_model": "text-embedding-004",
        "kind": "openai-compatible",
    },
    "openrouter": {
        "label": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "env_key": "OPENROUTER_API_KEY",
        "default_model": "auto",
        "default_embedding_model": "openai/text-embedding-3-small",
        "kind": "openai-compatible",
    },
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "env_key": "DEEPSEEK_API_KEY",
        "default_model": "deepseek-chat",
        "default_embedding_model": "",
        "kind": "openai-compatible",
    },
    "grok": {
        "label": "Grok (x.ai)",
        "base_url": "https://api.x.ai/v1",
        "env_key": "XAI_API_KEY",
        "default_model": "grok-2-latest",
        "default_embedding_model": "",
        "kind": "openai-compatible",
    },
    "huggingface": {
        "label": "HuggingFace",
        "base_url": "https://api-inference.huggingface.co/v1",
        "env_key": "HF_TOKEN",
        "default_model": "meta-llama/Llama-3.3-70B-Instruct",
        "default_embedding_model": "BAAI/bge-small-en-v1.5",
        "kind": "openai-compatible",
    },
    "venice": {
        "label": "Venice AI",
        "base_url": "https://api.venice.ai/api/v1",
        "env_key": "VENICE_API_KEY",
        "default_model": "llama-3.3-70b",
        "default_embedding_model": "default",
        "kind": "openai-compatible",
    },
    "groq": {
        "label": "Groq",
        "base_url": "https://api.groq.com/openai/v1",
        "env_key": "GROQ_API_KEY",
        "default_model": "llama-3.3-70b-versatile",
        "default_embedding_model": "",
        "kind": "openai-compatible",
    },
    "together": {
        "label": "Together AI",
        "base_url": "https://api.together.xyz/v1",
        "env_key": "TOGETHER_API_KEY",
        "default_model": "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo",
        "default_embedding_model": "BAAI/bge-large-en-v1.5",
        "kind": "openai-compatible",
    },
    "mistral": {
        "label": "Mistral AI",
        "base_url": "https://api.mistral.ai/v1",
        "env_key": "MISTRAL_API_KEY",
        "default_model": "mistral-large-latest",
        "default_embedding_model": "mistral-embed",
        "kind": "openai-compatible",
    },
    "perplexity": {
        "label": "Perplexity AI",
        "base_url": "https://api.perplexity.ai",
        "env_key": "PERPLEXITY_API_KEY",
        "default_model": "sonar-pro",
        "default_embedding_model": "",
        "kind": "openai-compatible",
    },
    "fireworks": {
        "label": "Fireworks AI",
        "base_url": "https://api.fireworks.ai/inference/v1",
        "env_key": "FIREWORKS_API_KEY",
        "default_model": "accounts/fireworks/models/llama-v3p3-70b-instruct",
        "default_embedding_model": "nomic-ai/nomic-embed-text-v1.5",
        "kind": "openai-compatible",
    },
    "cohere": {
        "label": "Cohere",
        "base_url": "https://api.cohere.com/compatibility/v1",
        "env_key": "COHERE_API_KEY",
        "default_model": "command-r-plus",
        "default_embedding_model": "embed-english-v3.0",
        "kind": "openai-compatible",
    },
    "replicate": {
        "label": "Replicate",
        "base_url": "https://openai-proxy.replicate.com/v1",
        "env_key": "REPLICATE_API_TOKEN",
        "default_model": "meta/meta-llama-3-70b-instruct",
        "default_embedding_model": "",
        "kind": "openai-compatible",
    },
    "siliconflow": {
        "label": "SiliconFlow",
        "base_url": "https://api.siliconflow.cn/v1",
        "env_key": "SILICONFLOW_API_KEY",
        "default_model": "deepseek-ai/DeepSeek-V3",
        "default_embedding_model": "BAAI/bge-large-en-v1.5",
        "kind": "openai-compatible",
    },
    "dashscope": {
        "label": "Qwen (DashScope)",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "env_key": "DASHSCOPE_API_KEY",
        "default_model": "qwen-max",
        "default_embedding_model": "text-embedding-v2",
        "kind": "openai-compatible",
    },
    "novita": {
        "label": "Novita AI",
        "base_url": "https://api.novita.ai/v3/openai",
        "env_key": "NOVITA_API_KEY",
        "default_model": "meta-llama/llama-3.3-70b-instruct",
        "default_embedding_model": "BAAI/bge-large-en-v1.5",
        "kind": "openai-compatible",
    },
    "ollama": {
        "label": "Ollama (Local)",
        "base_url": "http://localhost:11434/v1",
        "env_key": "OLLAMA_API_KEY",
        "default_model": "llama3.2",
        "default_embedding_model": "nomic-embed-text",
        "kind": "openai-compatible",
    },
    "lmstudio": {
        "label": "LM Studio (Local)",
        "base_url": "http://localhost:1234/v1",
        "env_key": "LMSTUDIO_API_KEY",
        "default_model": "local-model",
        "default_embedding_model": "text-embedding-nomic-embed-text-v1.5",
        "kind": "openai-compatible",
    },
    "moonshot": {
        "label": "Moonshot AI (Kimi)",
        "base_url": "https://api.moonshot.cn/v1",
        "env_key": "MOONSHOT_API_KEY",
        "default_model": "moonshot-v1-8k",
        "default_embedding_model": "",
        "kind": "openai-compatible",
    },
    "01ai": {
        "label": "01.AI (Yi)",
        "base_url": "https://api.lingyiwanwu.com/v1",
        "env_key": "ZEROONE_API_KEY",
        "default_model": "yi-lightning",
        "default_embedding_model": "",
        "kind": "openai-compatible",
    },
    "nvidia": {
        "label": "NVIDIA NIM",
        "base_url": "https://integrate.api.nvidia.com/v1",
        "env_key": "NVIDIA_API_KEY",
        # Highest-parameter model on the free NIM catalog (confirmed live against
        # GET /v1/models with the account's own key, 2026-09-03): 550B total / 55B
        # active hybrid Mamba-Transformer MoE.
        "default_model": "nvidia/nemotron-3-ultra-550b-a55b",
        "default_embedding_model": "nvidia/embed-qa-4",
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
    """Key resolution order: per-request key → stored plaintext → env var."""
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
        val = os.environ.get(env)
        if val:
            return val
    # Local providers (ollama, lmstudio) don't strictly require a key
    if provider_id in ("ollama", "lmstudio"):
        return "local"
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
    """OpenAI-compatible adapter supporting /chat/completions, /models, /embeddings."""

    def __init__(
        self,
        provider_id: str,
        base_url: str,
        api_key: str,
        default_model: str,
        default_embedding_model: str = "",
    ):
        self.id = provider_id
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or ""
        self.default_model = default_model
        self.default_embedding_model = default_embedding_model

    def _headers(self) -> dict:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": "Conductor/1.9.5",
        }
        if self.id == "openrouter":
            headers["HTTP-Referer"] = "https://conductor.app"
            headers["X-Title"] = "Conductor"
        return headers

    def list_models(self) -> list[dict]:
        req = urllib.request.Request(
            f"{self.base_url}/models",
            headers=self._headers(),
        )
        try:
            with urllib.request.urlopen(req, timeout=6) as r:
                data = json.loads(r.read().decode("utf-8"))
            raw_models = data.get("data", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
            models = []
            for m in raw_models:
                if isinstance(m, dict) and m.get("id"):
                    mid = str(m["id"])
                    if mid.startswith("models/"):
                        mid = mid[7:]
                    models.append({"id": mid, "providerId": self.id})
            if models:
                return models
        except Exception:
            pass
        return [{"id": self.default_model, "providerId": self.id}]

    def health(self) -> dict:
        start = time.time()
        try:
            self.list_models()
            return {"healthy": True, "latencyMs": int((time.time() - start) * 1000)}
        except Exception as exc:
            return {"healthy": False, "latencyMs": int((time.time() - start) * 1000), "error": str(exc)}

    def embed(self, input_val: str | list[str], model: str | None = None) -> dict:
        target_model = model or self.default_embedding_model or self.default_model
        payload = {
            "input": input_val,
            "model": target_model,
        }
        req = urllib.request.Request(
            f"{self.base_url}/embeddings",
            data=json.dumps(payload).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = _http_error_detail(exc)
            raise ValueError(f"HTTP_{exc.code}: {detail}")
        except Exception as exc:
            raise ValueError(f"Embedding request failed: {exc}")

    def stream_chat(
        self, messages: list[dict], model: str, max_tokens: int = 1200, temperature: float = 0.6
    ):
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
            headers=self._headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                for obj in parse_sse_lines(resp):
                    if obj.get("usage"):
                        yield {
                            "type": "usage",
                            "prompt_tokens": obj["usage"].get("prompt_tokens") or 0,
                            "completion_tokens": obj["usage"].get("completion_tokens") or 0,
                        }
                    choices = obj.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    if delta.get("reasoning_content"):
                        yield {"type": "thinking", "text": delta["reasoning_content"]}
                    elif delta.get("reasoning"):
                        yield {"type": "thinking", "text": delta["reasoning"]}
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
            return {"healthy": False, "latencyMs": int((time.time() - start) * 1000), "error": str(exc)}

    def embed(self, input_val: str | list[str], model: str | None = None) -> dict:
        raise ValueError(
            "Anthropic API does not offer native embeddings. Use OpenAI, Gemini, OpenRouter, HuggingFace, Cohere, etc."
        )

    def stream_chat(
        self, messages: list[dict], model: str, max_tokens: int = 1200, temperature: float = 0.6
    ):
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
                            payload_str = text[5:].strip()
                            try:
                                obj = json.loads(payload_str)
                            except json.JSONDecodeError:
                                event_name = None
                                continue
                            if obj.get("type") == "content_block_start":
                                block = obj.get("content_block") or {}
                            elif obj.get("type") == "content_block_delta":
                                delta = obj.get("delta") or {}
                                if delta.get("type") == "thinking_delta":
                                    yield {"type": "thinking", "text": delta.get("thinking", "")}
                                elif delta.get("type") == "text_delta":
                                    yield {"type": "text", "text": delta.get("text", "")}
                            elif obj.get("type") == "message_delta":
                                usage = obj.get("usage") or {}
                                yield {
                                    "type": "usage",
                                    "prompt_tokens": usage.get("input_tokens") or 0,
                                    "completion_tokens": usage.get("output_tokens") or 0,
                                }
                            event_name = None
        except urllib.error.HTTPError as exc:
            yield {"type": "error", "code": f"HTTP_{exc.code}", "message": _http_error_detail(exc)}
        except Exception as exc:
            yield {"type": "error", "code": type(exc).__name__, "message": str(exc)}


class ProxyAdapter:
    """Supabase Edge Function Proxy adapter."""

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

    def embed(self, input_val: str | list[str], model: str | None = None) -> dict:
        target_model = model or self.default_model
        payload = {"providerId": self.id, "modelId": target_model, "input": input_val, "action": "embeddings"}
        req = urllib.request.Request(
            f"{self.function_url}/embeddings",
            data=json.dumps(payload).encode("utf-8"),
            headers={**self.auth_headers, "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            raise ValueError(f"Proxy embedding failed: {exc}")

    def stream_chat(
        self, messages: list[dict], model: str, max_tokens: int = 1200, temperature: float = 0.6
    ):
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
                        yield {
                            "type": "usage",
                            "prompt_tokens": obj.get("promptTokens") or 0,
                            "completion_tokens": obj.get("completionTokens") or 0,
                        }
                    elif ev_type == "error":
                        yield {
                            "type": "error",
                            "code": obj.get("error", {}).get("code", "PROXY_ERROR"),
                            "message": obj.get("error", {}).get("message", "proxy chat failed"),
                        }
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
    meta = HOSTED_PROVIDERS.get(provider_id)
    if not meta:
        return None
    cfg = read_provider_config(provider_id)
    mode = cfg.get("mode") or "direct"
    base_url = (cfg.get("baseUrl") or meta["base_url"]).rstrip("/")
    default_model = cfg.get("defaultModelId") or meta["default_model"]
    default_embedding_model = meta.get("default_embedding_model", "")

    if mode == "proxy":
        auth = _proxy_auth_headers()
        if not auth:
            return None
        return ProxyAdapter(provider_id, base_url, auth, default_model)
    if not api_key and provider_id not in ("ollama", "lmstudio"):
        return None
    if meta["kind"] == "anthropic":
        return AnthropicAdapter(provider_id, base_url, api_key or "", default_model)
    return OpenAICompatAdapter(provider_id, base_url, api_key or "", default_model, default_embedding_model)


def registry() -> dict[str, object]:
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
            "defaultEmbeddingModel": meta.get("default_embedding_model", ""),
            "enabled": cfg.get("enabled", True),
            "hasKey": has,
            "configured": pid in reg,
            "models": models,
        })
    return out


def stream_provider(
    provider_id: str,
    messages: list[dict],
    model: str | None = None,
    api_key: str | None = None,
    max_tokens: int = 1200,
    temperature: float = 0.6,
):
    key = resolve_api_key(provider_id, api_key)
    adapter = build_adapter(provider_id, key)
    if adapter is None:
        raise ValueError(
            f"Provider '{provider_id}' is not configured. Add an API key in Settings → AI Chat."
        )
    if not model:
        cfg = read_provider_config(provider_id)
        model = cfg.get("defaultModelId") or HOSTED_PROVIDERS[provider_id]["default_model"]
    yield from adapter.stream_chat(messages, model, max_tokens=max_tokens, temperature=temperature)
