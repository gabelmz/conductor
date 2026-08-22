from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "backend" / "asana_mcp_stdio.py"


def _module():
    spec = importlib.util.spec_from_file_location("asana_mcp_stdio", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_load_access_token_reads_primary_pat(tmp_path):
    cfg = tmp_path / "asana.json"
    cfg.write_text('{"pat":"secret-token","pats":["fallback"]}', encoding="utf-8")
    assert _module().load_access_token(cfg) == "secret-token"


def test_load_access_token_falls_back_to_rotation(tmp_path):
    cfg = tmp_path / "asana.json"
    cfg.write_text('{"pats":["first-token"]}', encoding="utf-8")
    assert _module().load_access_token(cfg) == "first-token"


def test_build_command_uses_bundled_server():
    command = _module().build_command(runtime="C:/runtime/node.exe")
    assert command[0] == "C:/runtime/node.exe"
    assert command[1].endswith("backend\\asana_mcp_server.cjs") or command[1].endswith("backend/asana_mcp_server.cjs")
