#!/usr/bin/env python
"""Launch the guarded Asana stdio MCP server with Conductor's saved PAT."""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "data" / "asana.json"


def load_access_token(config_path: Path = DEFAULT_CONFIG) -> str:
    try:
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cannot read Conductor Asana config: {exc}") from exc
    token = str(cfg.get("pat") or "").strip()
    if not token:
        token = next((str(v).strip() for v in cfg.get("pats", []) if str(v).strip()), "")
    if not token:
        raise RuntimeError("Conductor has no Asana PAT configured")
    return token


BUNDLE_PATH = Path(__file__).with_name("asana_mcp_server.cjs")


def build_command(runtime: str | None = None) -> list[str]:
    runtime = runtime or os.environ.get("CONDUCTOR_ELECTRON_EXE") or shutil.which("node")
    if not runtime:
        raise RuntimeError("No bundled Electron/Node runtime is available for Asana MCP")
    if not BUNDLE_PATH.exists():
        raise RuntimeError(f"Bundled Asana MCP server is missing: {BUNDLE_PATH}")
    return [runtime, str(BUNDLE_PATH)]


def main() -> int:
    import subprocess

    try:
        command = build_command()
        token = load_access_token()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    env = os.environ.copy()
    env["ASANA_ACCESS_TOKEN"] = token
    env["ASANA_MCP_WRITE_MODE"] = env.get("ASANA_MCP_WRITE_MODE", "read_only")
    env["ELECTRON_RUN_AS_NODE"] = "1"
    return subprocess.call(command, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
