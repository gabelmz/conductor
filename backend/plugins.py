"""Conductor — plugin registry (ported from LAW's plugin loader).

LAW's trust model (Obsidian-style, Option B): plugins are authored by the
owner by policy; permissions are declarative metadata only, no runtime
enforcement, and there is no dynamic install path — plugins ship bundled or
are dropped into the plugins directory by the user.

Backend responsibilities:
- Enumerate plugin manifests (bundled core-* plus any <frontend>/plugins/<id>/
  manifest.json the user drops in).
- Track enable/disable state in data/plugins.json ({disabled: [ids]}).
- The frontend plugin runtime loads the actual JS modules.

Manifest shape (LAW's PluginManifestSchema):
  {id, name, version, minAppVersion?, description?, author?, main,
   pages[], commands[], themes[], railItems[], permissions[]}
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

from storage import DATA_DIR

router = APIRouter(prefix="/api/plugins", tags=["plugins"])

# frontend/plugins/<id>/manifest.json + main.js — served statically with the
# rest of the frontend so the renderer can `import()` them.
PLUGINS_DIR = Path(__file__).resolve().parent.parent / "frontend" / "plugins"
PLUGINS_DIR.mkdir(parents=True, exist_ok=True)

STATE_PATH = DATA_DIR / "plugins.json"

BUNDLED_MANIFESTS = [
    {
        "id": "core-hub",
        "name": "Tool Hub",
        "version": "0.1.0",
        "description": "Team tool registry — catalog every app, skill, module, plugin and theme with status, owner and tags (ported from LAW's core-hub).",
        "author": "Gabe Maher",
        "main": "plugins/core-hub/main.js",
        "pages": ["hub"],
        "commands": ["hub:open", "hub:new-card"],
        "themes": [],
        "railItems": [],
        "permissions": [],
    },
]


def _read_state() -> dict:
    if STATE_PATH.exists():
        try:
            data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {}


def _write_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _scan_disk_manifests() -> list[dict]:
    """User-dropped plugins: <frontend>/plugins/<id>/manifest.json."""
    out = []
    if not PLUGINS_DIR.is_dir():
        return out
    for manifest_path in sorted(PLUGINS_DIR.glob("*/manifest.json")):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(manifest, dict) and manifest.get("id") and manifest.get("main"):
                manifest.setdefault("pages", [])
                manifest.setdefault("commands", [])
                manifest.setdefault("themes", [])
                manifest.setdefault("railItems", [])
                manifest.setdefault("permissions", [])
                # main is relative to the frontend root
                manifest["main"] = f"plugins/{manifest['id']}/{manifest['main'].lstrip('./')}"
                out.append(manifest)
        except Exception:
            continue
    return out


def all_manifests() -> list[dict]:
    by_id: dict[str, dict] = {}
    for m in [*BUNDLED_MANIFESTS, *_scan_disk_manifests()]:
        by_id[m["id"]] = m
    return list(by_id.values())


def is_enabled(plugin_id: str) -> bool:
    return plugin_id not in _read_state().get("disabled", [])


@router.get("")
def list_plugins():
    disabled = set(_read_state().get("disabled", []))
    out = []
    for m in all_manifests():
        entry = dict(m)
        entry["enabled"] = m["id"] not in disabled
        out.append(entry)
    return {"plugins": out}


@router.post("/{plugin_id}/enabled")
def set_enabled(plugin_id: str, body: dict):
    manifest_ids = {m["id"] for m in all_manifests()}
    if plugin_id not in manifest_ids:
        raise HTTPException(404, f"Unknown plugin '{plugin_id}'")
    state = _read_state()
    disabled = list(state.get("disabled", []))
    enabled = bool(body.get("enabled"))
    if enabled:
        disabled = [d for d in disabled if d != plugin_id]
    elif plugin_id not in disabled:
        disabled.append(plugin_id)
    state["disabled"] = disabled
    _write_state(state)
    return {"ok": True, "pluginId": plugin_id, "enabled": enabled}
