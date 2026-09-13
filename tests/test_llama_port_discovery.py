"""Local server detection must work on any port, and must never stop a server
we did not start.

Detection was previously hardcoded to ports 8098-8101 (the range Conductor
starts llama-server on), so a model served by Ollama (11434) or LM Studio
(1234) was invisible even though both ship in the provider catalog.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import llama


def test_managed_ports_are_the_original_range():
    assert llama.MANAGED_PORTS == (8098, 8099, 8100, 8101)


def test_discovery_covers_well_known_runtimes():
    ports = llama.discovery_ports()
    for expected in (11434, 1234, 8000):  # ollama, lm studio, vllm/unsloth
        assert expected in ports
    # managed ports must come first so the common case short-circuits
    assert ports[: len(llama.MANAGED_PORTS)] == llama.MANAGED_PORTS


def test_discovery_ports_env_override(monkeypatch):
    monkeypatch.setenv("CONDUCTOR_LLAMA_PORTS", "9001, 9002;9003")
    ports = llama.discovery_ports()
    assert 9001 in ports and 9002 in ports and 9003 in ports
    assert set(llama.MANAGED_PORTS).issubset(ports)


def test_discovery_ports_env_override_rejects_garbage(monkeypatch):
    monkeypatch.setenv("CONDUCTOR_LLAMA_PORTS", "abc, -5, 99999")
    assert llama.discovery_ports() == tuple(
        dict.fromkeys((*llama.MANAGED_PORTS, *llama.WELL_KNOWN_LOCAL_PORTS))
    )


def test_find_running_server_discovers_non_managed_port(monkeypatch):
    """The core regression: a server on 11434 must be found."""
    monkeypatch.setattr(llama, "_health_ok", lambda port, timeout=0.25: port == 11434)
    assert llama._find_running_server() == 11434


def test_find_running_server_prefers_managed_port(monkeypatch):
    monkeypatch.setattr(llama, "_health_ok", lambda port, timeout=0.25: port in (8099, 11434))
    assert llama._find_running_server() == 8099


def test_find_running_server_none_when_nothing_listening(monkeypatch):
    monkeypatch.setattr(llama, "_health_ok", lambda port, timeout=0.25: False)
    assert llama._find_running_server() is None


def test_health_ok_falls_back_to_v1_models(monkeypatch):
    """Ollama/LM Studio/vLLM do not implement llama.cpp's /health."""
    seen = []

    def fake_probe(port, path, timeout):
        seen.append(path)
        return path == "/v1/models"

    monkeypatch.setattr(llama, "_probe", fake_probe)
    assert llama._health_ok(11434) is True
    assert seen == ["/health", "/v1/models"]


@pytest.mark.parametrize("payload,expected", [
    ({"models": [{"model": "qwen2.5-7b.gguf"}]}, "qwen2.5-7b.gguf"),   # llama.cpp
    ({"data": [{"id": "gemma:latest"}]}, "gemma:latest"),               # openai shape
    ({"data": []}, None),
    ({}, None),
])
def test_model_name_handles_both_list_shapes(monkeypatch, payload, expected):
    import json as _json
    from contextlib import contextmanager

    @contextmanager
    def fake_urlopen(url, timeout=0):
        class R:
            def read(self):
                return _json.dumps(payload).encode()
        yield R()

    monkeypatch.setattr(llama.urllib.request, "urlopen", fake_urlopen)
    llama._model_cache.clear()
    assert llama._proc_model_name(11434) == expected
    llama._model_cache.clear()


def test_stop_server_never_sweeps_unmanaged_ports(monkeypatch):
    """Widening discovery must not widen the kill sweep - shutting down a port
    we did not start would kill the user's own Ollama."""
    probed: list[int] = []

    monkeypatch.setattr(llama, "_proc", None)
    monkeypatch.setattr(llama, "_health_ok", lambda port, timeout=0.25: probed.append(port) or False)
    llama.stop_server()

    assert probed == list(llama.MANAGED_PORTS)
    assert 11434 not in probed, "must never attempt to shut down Ollama"
