"""Parker — UI theme + appearance backend.

Serves:
  - GET  /api/ui/config   current UI theme blob ({theme, mode, tokens})
  - POST /api/ui/config   persist a UI theme blob
  - GET  /api/about       app/version/data info for the About settings page

The theme blob is the full design-token JSON (the "custom" palette) with
`theme` naming which preset drives the UI ('custom' or a builtin preset name)
and `mode` selecting light/dark for builtin presets. Presets themselves are
static data shipped in the frontend; only the user's custom blob + choice is
persisted here in data/ui.json (same pattern as chat.json / asana.json).
"""
from __future__ import annotations

import json
import os
import platform
import sys
import time

from fastapi import APIRouter, HTTPException

from storage import DATA_DIR

router = APIRouter(prefix="/api/ui", tags=["ui"])

CONFIG_PATH = DATA_DIR / "ui.json"
APP_START = time.time()

# Builtin theme names understood by the frontend preset gallery.
BUILTIN_THEMES = ("nous", "dune", "midnight", "ember", "mono", "cyberpunk", "slate")

# The default custom palette — the blob pasted by the user (primary slightly
# darkened vs the original #6E56CF per Gabe's request).
DEFAULT_THEME = {
    "theme": "nous",
    "mode": "light",
    "tokens": {
        "theme": "nous",
        "mode": "light",
        "gradient1": "linear-gradient(135deg, #0053FD 0%, #8B7CFF 100%)",
        "gradient2": "radial-gradient(ellipse at top, #BBD4FF 0%, transparent 100%)",
        "background1": "#F8FAFF",
        "background2": "#F3F7FF",
        "surface": {"base": "#FFFFFF", "raised": "#FFFFFF", "overlay": "rgba(255,255,255,0.72)"},
        "function": {
            "primary": "#0053FD",
            "secondary": "#EAF1FE",
            "success": "#2FA36B",
            "warning": "#B7791F",
            "danger": "#C72E4D",
            "info": "#0053FD",
        },
        "opacity": {"subtle": 0.06, "muted": 0.12, "half": 0.5, "strong": 0.72, "solid": 1},
        "density": {"scale": 1, "unit": 4, "controlHeight": 36, "padding": 12},
        "edges": {"radius": 4, "borderWidth": 1, "borderColor": "rgba(15,23,42,0.14)"},
        "highlights": {
            "topEdge": "rgba(255,255,255,0.85)",
            "glow": "rgba(0,83,253,0.22)",
            "selection": "rgba(0,83,253,0.18)",
        },
        "elevation": {
            "1": "0 1px 2px rgba(15,23,42,0.08)",
            "2": "0 6px 16px rgba(15,23,42,0.10)",
            "3": "0 24px 64px rgba(15,23,42,0.16)",
        },
        "depth": {"perspective": 1200, "layerOffset": 8, "innerShadow": "inset 0 2px 8px rgba(15,23,42,0.08)"},
        "gloss": {"intensity": 0.18, "angle": 115, "sheen": "rgba(255,255,255,0.9)", "blend": "overlay"},
        "headerFont": {"family": "Inter Tight, sans-serif", "weight": 650, "tracking": "-0.02em"},
        "bodyFont": {"family": "Inter, sans-serif", "weight": 400, "size": 15, "lineHeight": 1.55},
        "codeFont": {"family": "JetBrains Mono, monospace", "size": 13, "ligatures": True},
        "colorFont": {"heading": "#17171A", "body": "#17171A", "muted": "#666678", "link": "#0053FD", "code": "#242432"},
        "motion": {"duration": 200, "easing": "cubic-bezier(0.2,0,0,1)"},
        "blur": {"backdrop": 18},
        "overrides": {},
    },
    # Named skins: {name: {theme, mode, tokens, updated_at}}
    "skins": {},
}


def _load_config() -> dict:
    cfg = {}
    if CONFIG_PATH.exists():
        try:
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            cfg = {}
    merged = dict(DEFAULT_THEME)
    if isinstance(cfg, dict):
        merged.update({k: v for k, v in cfg.items() if v is not None})
    if not isinstance(merged.get("tokens"), dict):
        merged["tokens"] = dict(DEFAULT_THEME["tokens"])
    if merged.get("theme") not in BUILTIN_THEMES and merged.get("theme") != "custom":
        merged["theme"] = "custom"
    if merged.get("mode") not in ("dark", "light"):
        merged["mode"] = "dark"
    if not isinstance(merged.get("skins"), dict):
        merged["skins"] = {}
    return merged


def _save_config(cfg: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


@router.get("/config")
def get_config():
    cfg = _load_config()
    return {
        "theme": cfg["theme"],
        "mode": cfg["mode"],
        "tokens": cfg["tokens"],
        "skins": cfg["skins"],
        "updated_at": CONFIG_PATH.stat().st_mtime if CONFIG_PATH.exists() else None,
    }


@router.post("/config")
def set_config(body: dict):
    if not isinstance(body, dict) or not isinstance(body.get("tokens"), dict):
        raise HTTPException(status_code=422, detail="Expected a JSON object with a 'tokens' object.")

    theme = str(body.get("theme") or "custom")
    if theme not in BUILTIN_THEMES and theme != "custom":
        raise HTTPException(status_code=422, detail=f"Unknown theme '{theme}' — builtins: custom, {', '.join(BUILTIN_THEMES)}")
    mode = str(body.get("mode") or "dark")
    if mode not in ("dark", "light"):
        raise HTTPException(status_code=422, detail="mode must be 'dark' or 'light'.")

    tokens = dict(body["tokens"])
    # Keep the tokens' own mode field in sync with the top-level switch.
    if isinstance(tokens.get("mode"), str) and tokens["mode"] in ("dark", "light"):
        tokens["mode"] = mode
    cfg = {"theme": theme, "mode": mode, "tokens": tokens}
    # Preserve named skins — saving the active theme must not wipe them.
    existing = _load_config()
    if isinstance(existing.get("skins"), dict):
        cfg["skins"] = existing["skins"]
    _save_config(cfg)
    return {"ok": True, **cfg, "updated_at": CONFIG_PATH.stat().st_mtime if CONFIG_PATH.exists() else None}


def _validate_skin_name(name: str) -> str:
    name = str(name or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="Skin name is required.")
    if len(name) > 60:
        raise HTTPException(status_code=422, detail="Skin name too long (max 60 chars).")
    return name


@router.get("/skins")
def list_skins():
    return {"skins": _load_config().get("skins", {})}


@router.post("/skins")
def save_skin(body: dict):
    name = _validate_skin_name(body.get("name") if isinstance(body, dict) else None)
    theme = str(body.get("theme") or "custom")
    if theme not in BUILTIN_THEMES and theme != "custom":
        raise HTTPException(status_code=422, detail=f"Unknown theme '{theme}'.")
    mode = str(body.get("mode") or "dark")
    if mode not in ("dark", "light"):
        raise HTTPException(status_code=422, detail="mode must be 'dark' or 'light'.")
    tokens = body.get("tokens")
    if not isinstance(tokens, dict):
        raise HTTPException(status_code=422, detail="Skin needs a 'tokens' object.")
    cfg = _load_config()
    cfg.setdefault("skins", {})[name] = {
        "theme": theme,
        "mode": mode,
        "tokens": tokens,
        "updated_at": time.time(),
    }
    _save_config(cfg)
    return {"ok": True, "name": name, "skins": cfg["skins"]}


@router.delete("/skins/{name}")
def delete_skin(name: str):
    cfg = _load_config()
    skins = cfg.setdefault("skins", {})
    if name not in skins:
        raise HTTPException(status_code=404, detail=f"Skin '{name}' not found.")
    del skins[name]
    _save_config(cfg)
    return {"ok": True, "skins": skins}


@router.get("/about")
def about():
    db_size = 0
    db_path = DATA_DIR / "compliance.db"
    if db_path.exists():
        try:
            db_size = db_path.stat().st_size
        except OSError:
            pass
    return {
        "name": "Conductor",
        "version": "2.0.0",
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "data_dir": str(DATA_DIR),
        "db_size": db_size,
        "uptime_s": int(time.time() - APP_START),
        "pid": os.getpid(),
    }
