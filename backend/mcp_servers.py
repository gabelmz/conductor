"""Generic Model Context Protocol server registry and client API.

Registry data is stored in ``data/mcp.json``.  Both local stdio servers and
remote Streamable HTTP servers use the official ``mcp`` Python client.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Literal
from urllib.parse import urlsplit, urlunsplit

import httpx2
from fastapi import APIRouter, HTTPException, Response, status
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

try:
    import storage

    DEFAULT_CONFIG_PATH = storage.DATA_DIR / "mcp.json"
except ImportError:  # package import in tests and tooling
    DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "data" / "mcp.json"
CONFIG_PATH = DEFAULT_CONFIG_PATH

router = APIRouter(prefix="/api/mcp", tags=["mcp"])
_LOCK = threading.RLock()
_REDACTED = "***"
_SECRET_PARTS = ("secret", "token", "password", "passwd", "api_key", "apikey", "authorization", "cookie", "pat")


class ServerConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    name: str = Field(min_length=1)
    transport: Literal["stdio", "http", "streamable_http"]
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    cwd: str | None = None
    url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    timeout: int = Field(default=120, ge=1, le=600)

    @model_validator(mode="after")
    def validate_transport_settings(self) -> "ServerConfig":
        if self.transport == "stdio" and not self.command:
            raise ValueError("stdio transport requires command")
        if self.transport in {"http", "streamable_http"} and not self.url:
            raise ValueError("Streamable HTTP transport requires url")
        return self


class ToolCall(BaseModel):
    name: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)


def _is_secret_key(key: object) -> bool:
    normalized = str(key).lower().replace("-", "_")
    return any(part in normalized for part in _SECRET_PARTS)


def redact(value: Any, parent_key: object = "") -> Any:
    """Recursively replace values whose field names identify credentials."""
    if _is_secret_key(parent_key):
        return _REDACTED
    if isinstance(value, dict):
        return {key: redact(item, key) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def _default_servers() -> list[dict[str, Any]]:
    wrapper = Path(__file__).with_name("asana_mcp_stdio.py")
    return [{
        "id": "asana", "name": "Asana", "transport": "stdio",
        "command": sys.executable, "args": [str(wrapper)], "env": {},
        "cwd": str(wrapper.parent.parent), "url": None, "headers": {}, "timeout": 120,
    }]


def _load() -> list[dict[str, Any]]:
    with _LOCK:
        if not CONFIG_PATH.exists():
            if CONFIG_PATH == DEFAULT_CONFIG_PATH:
                defaults = _default_servers()
                _save(defaults)
                return defaults
            return []
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=500, detail="MCP registry is unreadable") from exc
        if not isinstance(data, list):
            raise HTTPException(status_code=500, detail="MCP registry must contain a list")
        return data


def _save(servers: list[dict[str, Any]]) -> None:
    with _LOCK:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary = CONFIG_PATH.with_suffix(CONFIG_PATH.suffix + ".tmp")
        temporary.write_text(json.dumps(servers, indent=2), encoding="utf-8")
        temporary.replace(CONFIG_PATH)


def _validated(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return ServerConfig.model_validate(payload).model_dump(mode="json")
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors(include_url=False)) from exc


def _get(server_id: str) -> dict[str, Any]:
    server = next((item for item in _load() if item.get("id") == server_id), None)
    if server is None:
        raise HTTPException(status_code=404, detail="MCP server not found")
    return server


def _safe_public_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        if parsed.port:
            host = f"{host}:{parsed.port}"
        return urlunsplit((parsed.scheme, host, parsed.path, "", ""))
    except (TypeError, ValueError):
        return "[configured]"


def _public(server: dict[str, Any]) -> dict[str, Any]:
    out = redact(server)
    if server.get("args"):
        out["args"] = ["***"]
    out["env"] = {str(key): "***" for key in (server.get("env") or {})}
    out["headers"] = {str(key): "***" for key in (server.get("headers") or {})}
    if server.get("url"):
        out["url"] = _safe_public_url(str(server["url"]))
    return out


def _dump_model(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


def _subprocess_env(explicit: dict[str, str] | None = None) -> dict[str, str]:
    safe_names = {
        "PATH", "HOME", "USER", "LANG", "LC_ALL", "TERM", "SHELL", "TMPDIR",
        "TMP", "TEMP", "USERPROFILE", "SYSTEMROOT", "COMSPEC", "PATHEXT",
        "APPDATA", "LOCALAPPDATA", "CONDUCTOR_ELECTRON_EXE",
    }
    inherited = {
        key: value for key, value in os.environ.items()
        if key.upper() in safe_names or key.upper().startswith("XDG_")
    }
    inherited.update(explicit or {})
    return inherited


@asynccontextmanager
async def open_session(server: dict[str, Any]) -> AsyncIterator[ClientSession]:
    """Open and initialize an MCP session for either supported transport."""
    transport = server["transport"]
    if transport == "stdio":
        params = StdioServerParameters(
            command=server["command"],
            args=server.get("args") or [],
            env=_subprocess_env(server.get("env") or {}),
            cwd=server.get("cwd"),
        )
        async with stdio_client(params) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                yield session
        return

    headers = server.get("headers") or {}
    async with httpx2.AsyncClient(headers=headers, follow_redirects=True) as client:
        async with streamable_http_client(server["url"], http_client=client) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                yield session


async def _tools(server: dict[str, Any]) -> list[Any]:
    async with asyncio.timeout(float(server.get("timeout") or 120)):
        async with open_session(server) as session:
            result = await session.list_tools()
            return [_dump_model(tool) for tool in result.tools]


@router.get("")
def list_servers() -> list[dict[str, Any]]:
    return [_public(server) for server in _load()]


@router.post("", status_code=status.HTTP_201_CREATED)
def add_server(payload: dict[str, Any]) -> dict[str, Any]:
    server = _validated(payload)
    with _LOCK:
        servers = _load()
        if any(item.get("id") == server["id"] for item in servers):
            raise HTTPException(status_code=409, detail="MCP server id already exists")
        servers.append(server)
        _save(servers)
    return _public(server)


@router.put("/{server_id}")
def update_server(server_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    with _LOCK:
        servers = _load()
        index = next((i for i, item in enumerate(servers) if item.get("id") == server_id), None)
        if index is None:
            raise HTTPException(status_code=404, detail="MCP server not found")
        existing = servers[index]
        merged = {**existing, **payload, "id": server_id}
        # A UI can submit a redacted value without accidentally destroying the stored secret.
        for field in ("env", "headers"):
            if isinstance(payload.get(field), dict):
                merged[field] = dict(existing.get(field) or {})
                for key, value in payload[field].items():
                    if value != _REDACTED:
                        merged[field][key] = value
        server = _validated(merged)
        servers[index] = server
        _save(servers)
    return _public(server)


@router.delete("/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_server(server_id: str) -> Response:
    with _LOCK:
        servers = _load()
        remaining = [item for item in servers if item.get("id") != server_id]
        if len(remaining) == len(servers):
            raise HTTPException(status_code=404, detail="MCP server not found")
        _save(remaining)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{server_id}/test")
async def test_server(server_id: str) -> dict[str, Any]:
    try:
        tools = await _tools(_get(server_id))
        return {"ok": True, "tool_count": len(tools)}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"MCP connection failed: {type(exc).__name__}") from exc


@router.get("/{server_id}/tools")
async def list_tools(server_id: str) -> list[Any]:
    try:
        return await _tools(_get(server_id))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"MCP connection failed: {type(exc).__name__}") from exc


@router.post("/{server_id}/call")
async def call_tool(server_id: str, call: ToolCall) -> Any:
    try:
        server = _get(server_id)
        async with asyncio.timeout(float(server.get("timeout") or 120)):
            async with open_session(server) as session:
                result = await session.call_tool(call.name, call.arguments)
                return _dump_model(result)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"MCP tool call failed: {type(exc).__name__}") from exc
