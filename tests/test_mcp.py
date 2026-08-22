from __future__ import annotations

import json
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import mcp_servers as mcp


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp, "CONFIG_PATH", tmp_path / "mcp.json")
    app = FastAPI()
    app.include_router(mcp.router)
    return TestClient(app)


def test_registry_crud_persists_and_redacts_secrets(client):
    payload = {
        "name": "Asana",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "asana-mcp"],
        "env": {"ASANA_ACCESS_TOKEN": "top-secret", "MODE": "live"},
    }
    created = client.post("/api/mcp", json=payload)
    assert created.status_code == 201
    body = created.json()
    assert body["id"]
    assert body["env"] == {"ASANA_ACCESS_TOKEN": "***", "MODE": "***"}
    assert body["args"] == ["***"]

    server_id = body["id"]
    assert client.get("/api/mcp").json() == [body]
    on_disk = json.loads(mcp.CONFIG_PATH.read_text(encoding="utf-8"))
    assert on_disk[0]["env"]["ASANA_ACCESS_TOKEN"] == "top-secret"

    updated = client.put(
        f"/api/mcp/{server_id}",
        json={"name": "Asana renamed", "env": {"ASANA_ACCESS_TOKEN": "new-secret"}},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Asana renamed"
    assert updated.json()["env"]["ASANA_ACCESS_TOKEN"] == "***"

    assert client.delete(f"/api/mcp/{server_id}").status_code == 204
    assert client.get("/api/mcp").json() == []


def test_registry_rejects_invalid_transport_and_duplicate_id(client):
    bad = client.post("/api/mcp", json={"name": "bad", "transport": "websocket"})
    assert bad.status_code == 422

    payload = {"id": "same", "name": "one", "transport": "http", "url": "https://mcp.test"}
    assert client.post("/api/mcp", json=payload).status_code == 201
    assert client.post("/api/mcp", json=payload).status_code == 409


def test_fresh_install_seeds_bundled_asana_server(tmp_path, monkeypatch):
    path = tmp_path / "mcp.json"
    monkeypatch.setattr(mcp, "CONFIG_PATH", path)
    monkeypatch.setattr(mcp, "DEFAULT_CONFIG_PATH", path)
    servers = mcp.list_servers()
    assert len(servers) == 1
    assert servers[0]["id"] == "asana"
    assert servers[0]["args"] == ["***"]
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved[0]["args"][0].endswith("asana_mcp_stdio.py")


class FakeSession:
    def __init__(self):
        self.initialized = False

    async def initialize(self):
        self.initialized = True

    async def list_tools(self):
        class Result:
            tools = [
                type("Tool", (), {"model_dump": lambda self, mode=None: {"name": "ping", "description": "Ping", "inputSchema": {}}})()
            ]
        return Result()

    async def call_tool(self, name, arguments):
        assert name == "ping"
        assert arguments == {"value": 7}
        return type("Result", (), {"model_dump": lambda self, mode=None: {"content": [{"type": "text", "text": "pong"}], "isError": False}})()


@pytest.fixture()
def connected_client(client, monkeypatch):
    session = FakeSession()

    @asynccontextmanager
    async def fake_session(server):
        assert server["name"] == "Remote"
        await session.initialize()
        yield session

    monkeypatch.setattr(mcp, "open_session", fake_session)
    created = client.post(
        "/api/mcp",
        json={"id": "remote", "name": "Remote", "transport": "http", "url": "https://mcp.test/rpc", "headers": {"Authorization": "Bearer hidden"}},
    )
    assert created.status_code == 201
    assert created.json()["headers"]["Authorization"] == "***"
    return client, session


def test_test_and_tools_initialize_mcp_session(connected_client):
    client, session = connected_client
    tested = client.post("/api/mcp/remote/test")
    assert tested.status_code == 200
    assert tested.json() == {"ok": True, "tool_count": 1}
    assert session.initialized

    tools = client.get("/api/mcp/remote/tools")
    assert tools.status_code == 200
    assert tools.json() == [{"name": "ping", "description": "Ping", "inputSchema": {}}]


def test_call_invokes_named_tool(connected_client):
    client, _ = connected_client
    response = client.post("/api/mcp/remote/call", json={"name": "ping", "arguments": {"value": 7}})
    assert response.status_code == 200
    assert response.json() == {"content": [{"type": "text", "text": "pong"}], "isError": False}


def test_missing_server_is_404(client):
    assert client.get("/api/mcp/missing/tools").status_code == 404


def test_subprocess_environment_does_not_leak_host_credentials(monkeypatch):
    monkeypatch.setenv("PATH", "safe-path")
    monkeypatch.setenv("HOME", "safe-home")
    monkeypatch.setenv("UNRELATED_SECRET", "must-not-leak")
    env = mcp._subprocess_env({"EXPLICIT_TOKEN": "allowed"})
    assert env["PATH"] == "safe-path"
    assert env["HOME"] == "safe-home"
    assert env["EXPLICIT_TOKEN"] == "allowed"
    assert "UNRELATED_SECRET" not in env
