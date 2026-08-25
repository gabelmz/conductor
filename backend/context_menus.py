"""Global context-menu preference storage and validation.

Only user overrides and safe custom actions are persisted. Built-in command defaults
remain frontend-owned, so newly shipped commands are not hidden by a stale snapshot.
"""
from __future__ import annotations

import json
import os
import re
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from fastapi import APIRouter, HTTPException

try:
    from storage import DATA_DIR
except ImportError:  # package import in tests and tooling
    DATA_DIR = Path(__file__).resolve().parents[1] / "data"

router = APIRouter(prefix="/api/context-menus", tags=["context-menus"])
CONFIG_PATH = DATA_DIR / "context-menus.json"

SCHEMA_VERSION = 2
MAX_PAYLOAD_BYTES = 64 * 1024
MAX_JSON_DEPTH = 16
MAX_JSON_NODES = 2048
MAX_PREDICATE_DEPTH = 10
MAX_PREDICATE_NODES = 256
MAX_REGEX_LENGTH = 256
MAX_TEMPLATE_LENGTH = 4096
MAX_ACTIONS = 128

_LOCK = threading.RLock()
_DANGEROUS_PARTS = {"__proto__", "prototype", "constructor"}
_PREDICATE_OPS = {
    "eq", "ne", "in", "not-in", "contains", "exists", "truthy", "falsy",
    "matches", "and", "or", "not",
}
_PATH_ROOTS = {"surface", "target", "selection", "view", "context", "item", "user", "app"}
_ACTION_FIELDS = {
    "run-command": {"type", "commandId"},
    "navigate-view": {"type", "viewId"},
    "copy-template": {"type", "template"},
    "open-url": {"type", "url"},
    "same-origin-api": {"type", "path", "method", "confirmation", "body"},
}
_HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
_HTML_RE = re.compile(r"<\s*/?\s*[a-zA-Z][^>]*>")


def _defaults(revision: int = 0) -> dict[str, Any]:
    return {"version": SCHEMA_VERSION, "revision": revision, "overrides": {}, "customActions": []}


def _error(message: str, status_code: int = 422) -> None:
    raise HTTPException(status_code=status_code, detail=message)


def _check_json_limits(value: Any) -> None:
    try:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as exc:
        _error(f"Payload must be JSON serializable: {exc}")
    if len(encoded) > MAX_PAYLOAD_BYTES:
        _error(f"Payload exceeds {MAX_PAYLOAD_BYTES} bytes", 413)

    nodes = 0

    def walk(item: Any, depth: int) -> None:
        nonlocal nodes
        nodes += 1
        if nodes > MAX_JSON_NODES:
            _error("Payload contains too many values")
        if depth > MAX_JSON_DEPTH:
            _error("Payload nesting is too deep")
        if isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str):
                    _error("Object keys must be strings")
                if key.lower() in _DANGEROUS_PARTS:
                    _error(f"Forbidden object key: {key}")
                walk(child, depth + 1)
        elif isinstance(item, list):
            for child in item:
                walk(child, depth + 1)
        elif not isinstance(item, (str, int, float, bool, type(None))):
            _error("Payload contains a non-JSON value")

    walk(value, 0)


def _safe_id(value: Any, field: str, max_length: int = 160) -> str:
    if not isinstance(value, str) or not value.strip():
        _error(f"{field} must be a non-empty string")
    value = value.strip()
    if len(value) > max_length:
        _error(f"{field} is too long")
    if any(part.lower() in _DANGEROUS_PARTS for part in re.split(r"[./\\]", value)):
        _error(f"{field} contains a forbidden component")
    return value


def _validate_path(value: Any) -> str:
    path = _safe_id(value, "predicate path")
    parts = path.split(".")
    if parts[0] not in _PATH_ROOTS or any(not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", part) for part in parts):
        _error(f"Predicate path is not allowlisted: {path}")
    return path


def _validate_predicate(predicate: Any) -> None:
    count = 0

    def visit(node: Any, depth: int) -> None:
        nonlocal count
        count += 1
        if count > MAX_PREDICATE_NODES:
            _error("Predicate contains too many nodes")
        if depth > MAX_PREDICATE_DEPTH:
            _error("Predicate nesting is too deep")
        if not isinstance(node, dict):
            _error("Predicate nodes must be objects")
        op = node.get("op")
        if op not in _PREDICATE_OPS:
            _error(f"Predicate operator is not allowlisted: {op}")
        allowed = {"op", "path", "value", "args"}
        if set(node) - allowed:
            _error("Predicate contains unsupported fields")
        if op in {"and", "or", "not"}:
            args = node.get("args")
            if not isinstance(args, list) or not args:
                _error(f"Predicate operator '{op}' requires args")
            if op == "not" and len(args) != 1:
                _error("Predicate operator 'not' requires exactly one argument")
            for child in args:
                visit(child, depth + 1)
            return
        _validate_path(node.get("path"))
        if "args" in node:
            _error(f"Predicate operator '{op}' does not accept args")
        if op == "matches":
            pattern = node.get("value")
            if not isinstance(pattern, str) or len(pattern) > MAX_REGEX_LENGTH:
                _error(f"Predicate regex must be at most {MAX_REGEX_LENGTH} characters")
            try:
                re.compile(pattern)
            except re.error as exc:
                _error(f"Invalid predicate regex: {exc}")

    visit(predicate, 0)


def _validate_open_url(value: Any) -> None:
    url = _safe_id(value, "action url", 2048)
    try:
        parsed = urlsplit(url)
        port = parsed.port  # force malformed-port validation
    except ValueError as exc:
        _error(f"Invalid action URL: {exc}")
    del port
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        _error("open-url permits only absolute http/https URLs")
    if parsed.username is not None or parsed.password is not None:
        _error("Credential-bearing URLs are forbidden")


def _validate_api_action(action: dict[str, Any]) -> None:
    path = _safe_id(action.get("path"), "API path", 2048)
    parsed = urlsplit(path)
    decoded_path = unquote(parsed.path)
    if parsed.scheme or parsed.netloc or not decoded_path.startswith("/api/") or path.startswith("//"):
        _error("same-origin-api path must be a relative /api/* path")
    if "\\" in decoded_path or any(part == ".." for part in decoded_path.split("/")):
        _error("same-origin-api path contains traversal")
    method = str(action.get("method") or "GET").upper()
    if method not in _HTTP_METHODS:
        _error(f"API method is not allowlisted: {method}")
    action["method"] = method
    if method != "GET":
        confirmation = action.get("confirmation")
        if not isinstance(confirmation, str) or not confirmation.strip() or len(confirmation) > 240:
            _error("Destructive API methods require a confirmation message")
    if "body" in action:
        _check_json_limits(action["body"])


def _validate_action(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        _error("custom action.action must be an object")
    action = deepcopy(raw)
    kind = action.get("type")
    if kind not in _ACTION_FIELDS:
        _error(f"Custom action type is not allowlisted: {kind}")
    extras = set(action) - _ACTION_FIELDS[kind]
    if extras:
        _error(f"Custom action contains unsupported fields: {', '.join(sorted(extras))}")
    if kind == "run-command":
        action["commandId"] = _safe_id(action.get("commandId"), "commandId")
    elif kind == "navigate-view":
        action["viewId"] = _safe_id(action.get("viewId"), "viewId")
    elif kind == "copy-template":
        template = action.get("template")
        if not isinstance(template, str) or len(template) > MAX_TEMPLATE_LENGTH:
            _error(f"Copy template must be at most {MAX_TEMPLATE_LENGTH} characters")
        if _HTML_RE.search(template):
            _error("HTML is forbidden in copy templates")
    elif kind == "open-url":
        _validate_open_url(action.get("url"))
    elif kind == "same-origin-api":
        _validate_api_action(action)
    return action


def _validate_custom_actions(raw: Any) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > MAX_ACTIONS:
        _error(f"customActions must be a list of at most {MAX_ACTIONS} items")
    result: list[dict[str, Any]] = []
    ids: set[str] = set()
    allowed = {"id", "label", "surface", "icon", "group", "order", "shortcut", "when", "action"}
    for original in raw:
        if not isinstance(original, dict):
            _error("Each custom action must be an object")
        if set(original) - allowed:
            _error("Custom action contains unsupported top-level fields")
        item = deepcopy(original)
        item_id = _safe_id(item.get("id"), "custom action id")
        if item_id in ids:
            _error(f"Duplicate custom action id: {item_id}")
        ids.add(item_id)
        item["label"] = _safe_id(item.get("label"), "custom action label", 120)
        item["surface"] = _safe_id(item.get("surface"), "custom action surface", 80)
        for field in ("icon", "group", "shortcut"):
            if field in item:
                item[field] = _safe_id(item[field], field, 80)
        if "order" in item and (not isinstance(item["order"], int) or isinstance(item["order"], bool)):
            _error("Custom action order must be an integer")
        if "when" in item:
            _validate_predicate(item["when"])
        item["action"] = _validate_action(item.get("action"))
        result.append(item)
    return result


def _validate_overrides(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        _error("overrides must be an object keyed by surface")
    result = deepcopy(raw)
    for surface, commands in result.items():
        _safe_id(surface, "surface", 80)
        if not isinstance(commands, dict):
            _error("Each surface override must be an object keyed by command ID")
        for command_id, override in commands.items():
            _safe_id(command_id, "command ID")
            if not isinstance(override, dict):
                _error("Each command override must be an object")
            if "when" in override:
                _validate_predicate(override["when"])
    return result


def _validate_document(raw: Any, revision: int) -> dict[str, Any]:
    _check_json_limits(raw)
    if not isinstance(raw, dict):
        _error("Expected a JSON object")
    version = raw.get("version", SCHEMA_VERSION)
    if version != SCHEMA_VERSION:
        _error(f"Only context-menu schema version {SCHEMA_VERSION} can be saved")
    allowed = {"version", "revision", "baseRevision", "overrides", "customActions"}
    if set(raw) - allowed:
        _error("Preference document contains unsupported fields")
    document = {
        "version": SCHEMA_VERSION,
        "revision": revision,
        "overrides": _validate_overrides(raw.get("overrides")),
        "customActions": _validate_custom_actions(raw.get("customActions")),
    }
    _check_json_limits(document)
    return document


def _migrate(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("Context-menu preferences must contain an object")
    if raw.get("version", 1) == SCHEMA_VERSION:
        revision = raw.get("revision", 0)
        if not isinstance(revision, int) or revision < 0:
            raise ValueError("Invalid context-menu revision")
        return _validate_document(raw, revision)
    if raw.get("version", 1) != 1:
        raise ValueError("Unsupported context-menu schema version")
    overrides: dict[str, dict[str, Any]] = {}
    surfaces = raw.get("surfaces") or {}
    if isinstance(surfaces, dict):
        for surface, entries in surfaces.items():
            if isinstance(entries, list):
                overrides[surface] = {
                    entry["id"]: {k: v for k, v in entry.items() if k != "id"}
                    for entry in entries if isinstance(entry, dict) and isinstance(entry.get("id"), str)
                }
            elif isinstance(entries, dict):
                overrides[surface] = entries
    migrated = {
        "version": SCHEMA_VERSION,
        "overrides": overrides,
        "customActions": raw.get("customActions") or [],
    }
    revision = raw.get("revision", 0)
    if not isinstance(revision, int) or revision < 0:
        revision = 0
    return _validate_document(migrated, revision)


def _load() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return _defaults()
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return _migrate(raw)
    except HTTPException as exc:
        raise HTTPException(status_code=500, detail="Context-menu preferences are invalid") from exc
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=500, detail="Context-menu preferences are unreadable") from exc


def _save(document: dict[str, Any]) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = CONFIG_PATH.with_suffix(CONFIG_PATH.suffix + ".tmp")
    try:
        temporary.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(temporary, CONFIG_PATH)
    finally:
        if temporary.exists():
            temporary.unlink()


def _base_revision(body: Any, current: dict[str, Any]) -> int:
    if not isinstance(body, dict):
        _error("Expected a JSON object")
    base = body.get("baseRevision")
    if not isinstance(base, int) or isinstance(base, bool) or base < 0:
        _error("baseRevision must be a non-negative integer")
    if base != current["revision"]:
        raise HTTPException(
            status_code=409,
            detail={"message": "Context-menu preferences changed", "currentRevision": current["revision"]},
        )
    return base


def _replace(body: Any) -> dict[str, Any]:
    _check_json_limits(body)
    with _LOCK:
        current = _load()
        base = _base_revision(body, current)
        document = _validate_document(body, base + 1)
        _save(document)
        return document


@router.get("")
def get_preferences() -> dict[str, Any]:
    with _LOCK:
        return _load()


@router.put("")
def replace_preferences(body: dict[str, Any]) -> dict[str, Any]:
    return _replace(body)


@router.get("/config")
def get_config() -> dict[str, Any]:
    return get_preferences()


@router.put("/config")
def replace_config(body: dict[str, Any]) -> dict[str, Any]:
    return _replace(body)


@router.post("/import")
def import_preferences(body: dict[str, Any]) -> dict[str, Any]:
    _check_json_limits(body)
    if isinstance(body.get("config"), dict):
        imported = dict(body["config"])
        imported["baseRevision"] = body.get("baseRevision")
        imported.pop("revision", None)
        return _replace(imported)
    return _replace(body)


@router.post("/reset-surface")
def reset_surface(body: dict[str, Any]) -> dict[str, Any]:
    _check_json_limits(body)
    with _LOCK:
        current = _load()
        base = _base_revision(body, current)
        surface = _safe_id(body.get("surface"), "surface", 80)
        next_document = deepcopy(current)
        next_document["revision"] = base + 1
        next_document["overrides"].pop(surface, None)
        next_document["customActions"] = [item for item in next_document["customActions"] if item.get("surface") != surface]
        _save(next_document)
        return next_document


@router.post("/reset-all")
def reset_all(body: dict[str, Any]) -> dict[str, Any]:
    _check_json_limits(body)
    with _LOCK:
        current = _load()
        base = _base_revision(body, current)
        document = _defaults(base + 1)
        _save(document)
        return document
