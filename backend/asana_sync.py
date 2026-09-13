"""Parker — Asana sync engine.

Pulls ALL of Asana (workspaces, users, teams, projects, custom fields,
tasks + custom fields, stories/comments, subtasks, attachments) into the
local SQLite store, using API patterns discovered from the Luminize Asana
sync scripts (Code.gs / asana-testing-04, sync_asana.py, .odc Power Query
connections):

  - Workspace GID      : 1161027935621444  (discovered, auto-detect fallback)
  - Portfolio GID      : 1210875219129229  (used when project_source=portfolio)
  - PAT identity       : 2/1205116828574744/1214636016249478:... (owner GID
                        1205116828574744 = Gabe; secret tail is stored in
                        Apps Script Properties / Power Query, not on disk)
  - Task opt_fields    : from Code.gs TASK_OPT_FIELDS (v4 catalog sync)
  - Weight rule        : /keepa/i tasks count 0.3, everything else 1.0

Credentials live in data/asana.json (alongside chat.json / compliance.db),
with ASANA_PAT env var as an override — so the installed desktop app works
without env vars.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Callable

from storage import DATA_DIR, now_iso

log = logging.getLogger(__name__)

BASE_URL = "https://app.asana.com/api/1.0"

# --- Discovered defaults -----------------------------------------------------
DEFAULT_WORKSPACE_GID = "1161027935621444"
DEFAULT_PORTFOLIO_GID = "1210875219129229"

CONFIG_PATH = DATA_DIR / "asana.json"

# --- Tunables ----------------------------------------------------------------
# Every value below is the *default*; data/asana.json may override it under a
# "tuning" object (see _tuning()). Overrides are clamped to the floors further
# down, so a bad config can only ever make us gentler on Asana, never harsher.
BATCH_SIZE = 100            # page size (Asana caps `limit` at 100 on list endpoints)
MAX_RETRIES = 5             # attempts per request, including the first
RATE_LIMIT_MS = 450         # min gap between two requests on the SAME token, in ms
MIN_INTERVAL_S = RATE_LIMIT_MS / 1000.0  # ^ same number in seconds — what the pacer uses
REQUEST_TIMEOUT_S = 60      # per-attempt socket timeout
TIMEOUT_BUFFER_MS = 300_000  # total wall-clock budget for one call incl. all backoff sleeps

# Owner-mandated floors. A config override may meet or exceed these; anything
# lower is a regression and is clamped back up (with a warning).
MIN_BATCH_SIZE = 100
MIN_RETRY_LIMIT = 3
MIN_RATE_LIMIT_MS = 200
MIN_REQUEST_TIMEOUT_S = 5
MIN_TIMEOUT_BUFFER_MS = 300_000
# Asana's own ceiling on `limit`; asking for more is rejected by the API.
ASANA_MAX_PAGE_SIZE = 100

# Backoff shape (exponential + jitter, see _backoff_delay).
BACKOFF_BASE_S = 1.0
BACKOFF_CAP_S = 60.0
DEFAULT_RETRY_AFTER_S = 5.0  # assumed floor for a 429 that carries no Retry-After

# Multi-PAT policy: key 1 is required, keys 2-4 are optional.
MAX_PATS = 4
QUARANTINE_AFTER_401S = 3  # consecutive 401s on one key before it leaves the rotation

# --- Task opt_fields (discovered from Code.gs v4 TASK_OPT_FIELDS) ------------
TASK_OPT_FIELDS = (
    "gid,name,resource_type,created_at,completed_at,modified_at,completed,"
    "assignee.gid,assignee.name,assignee.email,due_on,start_on,notes,permalink_url,"
    "tags.name,followers.name,followers.email,parent.gid,parent.name,"
    "memberships.project.gid,memberships.project.name,memberships.section.name,"
    "dependencies.gid,dependents.gid,num_subtasks,"
    "custom_fields.gid,custom_fields.name,custom_fields.resource_subtype,"
    "custom_fields.display_value,custom_fields.enum_value.name,"
    "custom_fields.multi_enum_values.name,custom_fields.number_value,"
    "custom_fields.text_value,custom_fields.date_value.date,"
    "attachments.gid,attachments.name,attachments.host,"
    "attachments.download_url,attachments.view_url,attachments.permanent_url,"
    "attachments.created_at"
)

PROJECT_OPT_FIELDS = (
    "gid,name,archived,color,notes,created_at,modified_at,permalink_url,"
    "team.gid,team.name"
)

# --- Config ----------------------------------------------------------------
def _read_raw_config() -> dict:
    """Parsed data/asana.json, exactly as written (no env merge, no defaults)."""
    if CONFIG_PATH.exists():
        try:
            raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return raw
        except Exception:
            pass
    return {}


def _load_config() -> dict:
    """Config with env fallback + defaults applied.

    Unknown/extra keys from the file are passed through untouched: sync_all()
    round-trips this dict straight back through _save_config(), so dropping them
    here would silently erase "tuning"/"pat_status" on every completed sync.
    """
    cfg = _read_raw_config()
    pat = cfg.get("pat") or os.environ.get("ASANA_PAT", "")
    pats = cfg.get("pats") or ([pat] if pat else [])
    pats = [p for p in pats if p]
    if len(pats) > MAX_PATS:
        log.warning("asana: %d PATs configured, using the first %d", len(pats), MAX_PATS)
        pats = pats[:MAX_PATS]
    return {
        **cfg,
        "pat": pat,
        "pats": pats,
        "workspace_gid": cfg.get("workspace_gid") or DEFAULT_WORKSPACE_GID,
        "portfolio_gid": cfg.get("portfolio_gid") or DEFAULT_PORTFOLIO_GID,
        "project_source": cfg.get("project_source") or "workspace",
        "last_sync": cfg.get("last_sync") or "",
    }


def _save_config(cfg: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


# --- Tuning (data/asana.json -> "tuning": {...}) ----------------------------
def _clamp_int(value, default: int, floor: int, ceiling: int | None = None) -> int:
    try:
        out = int(value)
    except (TypeError, ValueError):
        return default
    if out < floor:
        log.warning("asana: tuning value %r below floor %d — using %d", value, floor, floor)
        out = floor
    if ceiling is not None and out > ceiling:
        out = ceiling
    return out


def _tuning(cfg: dict | None = None) -> dict:
    """Resolved request tunables: config override -> module default -> floor.

    Module-level constants stay the defaults (so monkeypatching them still works);
    data/asana.json's "tuning" object overrides them; the owner floors clamp the
    result so an override can never make us more aggressive than the contract.
    """
    if cfg is None:
        cfg = _load_config()
    tun = cfg.get("tuning") if isinstance(cfg.get("tuning"), dict) else {}
    batch = _clamp_int(tun.get("batch_size", BATCH_SIZE), BATCH_SIZE,
                       MIN_BATCH_SIZE, ASANA_MAX_PAGE_SIZE)
    retries = _clamp_int(tun.get("max_retries", MAX_RETRIES), MAX_RETRIES, MIN_RETRY_LIMIT)
    rate_ms = _clamp_int(tun.get("rate_limit_ms", round(MIN_INTERVAL_S * 1000)),
                         round(MIN_INTERVAL_S * 1000), MIN_RATE_LIMIT_MS)
    timeout = _clamp_int(tun.get("timeout_s", REQUEST_TIMEOUT_S), REQUEST_TIMEOUT_S,
                         MIN_REQUEST_TIMEOUT_S)
    buffer_ms = _clamp_int(tun.get("timeout_buffer_ms", TIMEOUT_BUFFER_MS), TIMEOUT_BUFFER_MS,
                           MIN_TIMEOUT_BUFFER_MS)
    return {
        "batch_size": batch,
        "max_retries": retries,
        "rate_limit_ms": rate_ms,
        "min_interval_s": rate_ms / 1000.0,
        "timeout_s": timeout,
        "timeout_buffer_ms": buffer_ms,
        "timeout_buffer_s": buffer_ms / 1000.0,
    }


# --- PAT identity / status --------------------------------------------------
def _digest(token: str) -> str:
    """Stable, non-reversible id for a PAT — safe to persist, log and return."""
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()[:16]


def _mask(token: str) -> str:
    return f"****{token[-4:]}" if token else ""


def _pat_status(cfg: dict) -> dict:
    status = cfg.get("pat_status")
    return dict(status) if isinstance(status, dict) else {}


def _is_enabled(status: dict, token: str) -> bool:
    entry = status.get(_digest(token)) or {}
    return not entry.get("disabled")


def _active_pats(cfg: dict) -> list[tuple[int, str]]:
    """[(config index, token)] for keys eligible to serve a request."""
    status = _pat_status(cfg)
    return [(i, p) for i, p in enumerate(cfg.get("pats") or []) if _is_enabled(status, p)]


def _write_pat_status(digest: str, entry: dict) -> None:
    """Merge one key's status into the file without re-persisting derived fields.

    Writes through the RAW config (not _load_config's env-merged view) so an
    ASANA_PAT that only ever lived in the environment isn't quietly written to disk.
    """
    raw = _read_raw_config()
    status = raw.get("pat_status")
    status = dict(status) if isinstance(status, dict) else {}
    status[digest] = {**(status.get(digest) or {}), **entry}
    raw["pat_status"] = status
    _save_config(raw)


def list_pats() -> list[dict]:
    """Per-key identity/health. Never contains a raw token."""
    cfg = _load_config()
    status = _pat_status(cfg)
    out = []
    for i, token in enumerate(cfg.get("pats") or []):
        digest = _digest(token)
        entry = status.get(digest) or {}
        state = _key_state.get(digest) or {}
        out.append({
            "index": i,
            "id": digest,
            "masked": _mask(token),
            "is_primary": i == 0,
            "enabled": not entry.get("disabled"),
            "quarantined": bool(entry.get("quarantined_at")) and bool(entry.get("disabled")),
            "quarantined_at": entry.get("quarantined_at", ""),
            "quarantine_reason": entry.get("reason", ""),
            "last_used": state.get("last_used", ""),
            "requests": int(state.get("requests", 0)),
            "consecutive_failures": int(state.get("consecutive_failures", 0)),
        })
    return out


def get_config() -> dict:
    cfg = _load_config()
    pat = cfg.get("pat") or ""
    pats = cfg.get("pats") or []
    keys = list_pats()
    return {
        "has_pat": bool(pat),
        "pat_masked": _mask(pat),
        "num_pats": len(pats),
        "max_pats": MAX_PATS,
        "num_active_pats": sum(1 for k in keys if k["enabled"]),
        "keys": keys,
        "tuning": _tuning(cfg),
        "workspace_gid": cfg.get("workspace_gid") or "",
        "portfolio_gid": cfg.get("portfolio_gid") or "",
        "project_source": cfg.get("project_source") or "workspace",
        "last_sync": cfg.get("last_sync") or "",
    }


def save_config(**kwargs) -> dict:
    cfg = _load_config()
    for k in ("pat", "workspace_gid", "portfolio_gid", "project_source"):
        if k in kwargs and kwargs[k] is not None:
            cfg[k] = str(kwargs[k]).strip()
    if "pat" in kwargs and kwargs["pat"]:
        # Keep primary PAT + any additional tokens in the rotation.
        new_pat = str(kwargs["pat"]).strip()
        pats = [p for p in (cfg.get("pats") or []) if p]
        if new_pat not in pats:
            if len(pats) >= MAX_PATS:
                raise ValueError(
                    f"At most {MAX_PATS} Asana PATs are supported — remove one first."
                )
            pats.append(new_pat)
        cfg["pats"] = pats
        # Re-submitting a token is an explicit "this key is good again": clear any
        # quarantine so a recovered key rejoins the rotation without a file edit.
        status = _pat_status(cfg)
        digest = _digest(new_pat)
        if digest in status:
            status[digest] = {**status[digest], "disabled": False, "quarantined_at": "", "reason": ""}
            cfg["pat_status"] = status
        _key_state.pop(digest, None)
    _save_config(cfg)
    return get_config()


def remove_pat(index: int) -> dict:
    """Drop key `index` from the rotation. Key 1 (the primary) is required, so the
    last remaining key cannot be removed — replace it via save_config(pat=...) instead."""
    cfg = _load_config()
    pats = [p for p in (cfg.get("pats") or []) if p]
    if index < 0 or index >= len(pats):
        raise ValueError(f"No Asana PAT at index {index} (have {len(pats)}).")
    if len(pats) == 1:
        raise ValueError("At least one Asana PAT is required — replace it instead of removing it.")
    token = pats.pop(index)
    status = _pat_status(cfg)
    status.pop(_digest(token), None)
    _key_state.pop(_digest(token), None)
    cfg["pats"] = pats
    cfg["pat_status"] = status
    cfg["pat"] = pats[0]  # primary always tracks slot 0
    _save_config(cfg)
    return get_config()


def set_pat_enabled(index: int, enabled: bool) -> dict:
    """Disable/re-enable key `index` without deleting it. Re-enabling also clears a
    quarantine. The last enabled key cannot be manually disabled (that would leave
    the rotation empty); automatic quarantine is the only thing allowed to do that."""
    cfg = _load_config()
    pats = [p for p in (cfg.get("pats") or []) if p]
    if index < 0 or index >= len(pats):
        raise ValueError(f"No Asana PAT at index {index} (have {len(pats)}).")
    status = _pat_status(cfg)
    token = pats[index]
    digest = _digest(token)
    if not enabled and len([1 for p in pats if _is_enabled(status, p)]) <= 1:
        raise ValueError("Cannot disable the last enabled Asana PAT.")
    if enabled:
        status[digest] = {**(status.get(digest) or {}), "disabled": False,
                          "quarantined_at": "", "reason": ""}
        state = _key_state.get(digest)
        if state:
            state["consecutive_failures"] = 0
    else:
        status[digest] = {**(status.get(digest) or {}), "disabled": True,
                          "reason": "disabled manually"}
    cfg["pat_status"] = status
    _save_config(cfg)
    return get_config()


def has_credentials() -> bool:
    """True when at least one *usable* (enabled, non-quarantined) PAT is configured."""
    return bool(_active_pats(_load_config()))


# --- API client (multi-PAT round-robin + rate limiter) ----------------------
import threading

_req_lock = threading.Lock()
_req_count = 0
# token digest -> monotonic time at which that token's NEXT request may start.
# Holds a *reservation*, not a past timestamp: _headers() books the slot under the
# lock and then sleeps outside it, so pacing one caller never blocks the others.
# (tests/test_wave1_regressions.py resets this to a list — self-heal, don't crash.)
_last_use: dict[str, float] = {}
# token digest -> {"index", "requests", "consecutive_failures", "last_used"} (in-memory only)
_key_state: dict[str, dict] = {}


def _new_key_state(index: int = -1) -> dict:
    return {"index": index, "requests": 0, "consecutive_failures": 0, "last_used": ""}


# --- Telemetry ---------------------------------------------------------------
_stats_lock = threading.Lock()
_MAX_RETRY_AFTER_SAMPLES = 50


def _blank_stats() -> dict:
    return {
        "requests": 0,            # HTTP attempts issued (first tries + retries)
        "responses": 0,           # attempts that returned a parsed body
        "retries": 0,             # attempts that were a retry of a failed attempt
        "rate_limited": 0,        # 429s observed
        "server_errors": 0,       # 5xx responses observed
        "network_errors": 0,      # URLError (DNS/connect/timeout)
        "auth_failures": 0,       # 401/403 responses observed
        "quarantined_keys": 0,    # PATs pulled from rotation after repeated 401s
        "sleep_seconds": 0.0,     # pacing + backoff combined
        "pacing_sleep_seconds": 0.0,
        "backoff_sleep_seconds": 0.0,
        "retry_after_max": 0.0,
    }


_stats: dict = _blank_stats()
_stats.update({"since": now_iso(), "last_429_at": "", "retry_after_values": [],
               "last_error": ""})
_current_run: dict | None = None
_last_run: dict | None = None


def _bump(field: str, amount: float = 1) -> None:
    with _stats_lock:
        _stats[field] = _stats.get(field, 0) + amount


def _counter_snapshot() -> dict:
    with _stats_lock:
        return {k: _stats[k] for k in _blank_stats()}


def _counter_delta(before: dict) -> dict:
    now = _counter_snapshot()
    out = {k: (round(v - before.get(k, 0), 3) if isinstance(v, float) else v - before.get(k, 0))
           for k, v in now.items()}
    # retry_after_max is a high-water mark, not a counter — report the run's own max.
    out["retry_after_max"] = now["retry_after_max"]
    return out


def get_stats() -> dict:
    """Process-wide Asana API telemetry.

    Cumulative counters since process start (or the last reset_stats()), plus the
    per-sync-run view: ``run`` is the sync currently in flight (or the last one that
    died mid-way, so a failed run's 429 storm stays visible) and ``last_run`` is the
    last run that completed. This is the evidence base that
    docs/decisions/2026-09-12-asana-parallel-fetch.md defers the parallel-fetch
    decision on: requests, 429s, 5xx, retries, sleep seconds and observed Retry-After.
    """
    with _stats_lock:
        snapshot = dict(_stats)
        snapshot["retry_after_values"] = list(_stats["retry_after_values"])
    snapshot["sleep_seconds"] = round(snapshot["sleep_seconds"], 3)
    snapshot["pacing_sleep_seconds"] = round(snapshot["pacing_sleep_seconds"], 3)
    snapshot["backoff_sleep_seconds"] = round(snapshot["backoff_sleep_seconds"], 3)
    run = None
    if _current_run:
        run = {k: v for k, v in _current_run.items() if k != "baseline"}
        run.update(_counter_delta(_current_run["baseline"]))
        run["in_flight"] = True
    snapshot["run"] = run
    snapshot["last_run"] = dict(_last_run) if _last_run else None
    snapshot["keys"] = list_pats()
    return snapshot


def reset_stats() -> None:
    """Zero the cumulative counters (tests, and 'start measuring from now')."""
    global _stats, _current_run
    with _stats_lock:
        _stats = _blank_stats()
        _stats.update({"since": now_iso(), "last_429_at": "", "retry_after_values": [],
                       "last_error": ""})
    _current_run = None


def _begin_run(mode: str) -> None:
    global _current_run
    _current_run = {"mode": mode, "started_at": now_iso(), "baseline": _counter_snapshot()}


def _end_run(counts: dict) -> None:
    global _current_run, _last_run
    if not _current_run:
        return
    run = {k: v for k, v in _current_run.items() if k != "baseline"}
    run.update(_counter_delta(_current_run["baseline"]))
    run["finished_at"] = now_iso()
    run["tasks"] = counts.get("tasks", 0)
    run["in_flight"] = False
    _last_run = run
    _current_run = None
    log.info(
        "asana sync telemetry: mode=%s requests=%d retries=%d 429s=%d 5xx=%d "
        "net_errors=%d slept=%.1fs (pacing %.1fs / backoff %.1fs) max_retry_after=%.1fs",
        run.get("mode"), run["requests"], run["retries"], run["rate_limited"],
        run["server_errors"], run["network_errors"], run["sleep_seconds"],
        run["pacing_sleep_seconds"], run["backoff_sleep_seconds"], run["retry_after_max"],
    )


def _record_sleep(seconds: float, kind: str) -> None:
    with _stats_lock:
        _stats["sleep_seconds"] += seconds
        _stats[f"{kind}_sleep_seconds"] += seconds


def _record_retry_after(seconds: float | None) -> None:
    if seconds is None:
        return
    with _stats_lock:
        values = _stats["retry_after_values"]
        values.append(round(seconds, 3))
        if len(values) > _MAX_RETRY_AFTER_SAMPLES:
            del values[:-_MAX_RETRY_AFTER_SAMPLES]
        _stats["retry_after_max"] = max(_stats["retry_after_max"], seconds)


# --- Backoff -----------------------------------------------------------------
def _parse_retry_after(value) -> float | None:
    """Retry-After in seconds, accepting BOTH forms RFC 7231 allows.

    Asana normally sends delta-seconds, but the header is also legal as an HTTP-date
    ("Wed, 21 Oct 2026 07:28:00 GMT"); int() on that raised ValueError *inside* the
    429 handler, turning a routine rate-limit into a hard crash mid-sync.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return max(0.0, float(text))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())


def _backoff_delay(attempt: int, retry_after: float | None = None) -> float:
    """Exponential backoff with jitter; Retry-After (when present) is the floor.

    Was linear and unjittered (2*attempt), so every worker that hit the same 429
    woke up together and re-collided. Equal jitter keeps the expected wait growing
    exponentially while spreading wake-ups across the window.
    """
    window = min(BACKOFF_CAP_S, BACKOFF_BASE_S * (2 ** max(0, attempt - 1)))
    delay = window / 2 + random.uniform(0, window / 2)
    if retry_after is not None:
        # Never come back sooner than Asana asked; jitter on top so N callers
        # released by the same Retry-After don't stampede at the same instant.
        delay = max(delay, retry_after) + random.uniform(0, min(1.0, window / 2))
    return delay


def _sleep_backoff(delay: float, deadline: float, url: str) -> None:
    """Sleep `delay`, unless that would blow the per-call TIMEOUT_BUFFER budget."""
    if time.monotonic() + delay > deadline:
        raise RuntimeError(
            f"Asana API retry budget exhausted (timeout_buffer) before the next "
            f"{delay:.1f}s backoff for {url}"
        )
    _record_sleep(delay, "backoff")
    time.sleep(delay)


def _headers() -> dict:
    """Next PAT in the rotation, paced per-token so we never trip 429s.

    The pacing sleep happens OUTSIDE _req_lock: the lock only books this token's
    next slot. Holding it across time.sleep() (as it used to) would serialize every
    caller behind one token's pacing, which is exactly what a future parallel
    fetcher must not inherit.
    """
    global _req_count, _last_use
    cfg = _load_config()
    active = _active_pats(cfg)
    if not active:
        if cfg.get("pats"):
            raise RuntimeError(
                "Every configured Asana PAT is disabled or quarantined (repeated 401s) — "
                "re-enable or replace it in Settings → Asana."
            )
        raise RuntimeError("Asana PAT not configured — add it in Settings → Asana (or set ASANA_PAT).")
    min_interval = _tuning(cfg)["min_interval_s"]
    with _req_lock:
        if not isinstance(_last_use, dict):
            _last_use = {}
        idx, token = active[_req_count % len(active)]
        _req_count += 1
        digest = _digest(token)
        start_at = max(time.monotonic(), _last_use.get(digest, 0.0))
        _last_use[digest] = start_at + min_interval
        state = _key_state.setdefault(digest, _new_key_state(idx))
        state["index"] = idx
        state["requests"] += 1
        state["last_used"] = now_iso()
    wait = start_at - time.monotonic()
    if wait > 0:
        _record_sleep(wait, "pacing")
        time.sleep(wait)
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


def _digest_from_headers(headers: dict) -> str | None:
    auth = (headers or {}).get("Authorization") or ""
    if not auth.startswith("Bearer "):
        return None
    return _digest(auth[len("Bearer "):])


def _note_success(headers: dict) -> None:
    digest = _digest_from_headers(headers)
    state = _key_state.get(digest) if digest else None
    if state:
        state["consecutive_failures"] = 0


def _note_auth_failure(headers: dict, code: int) -> None:
    """Count a 401/403 and quarantine the key after repeated 401s.

    One expired token in a 4-key rotation otherwise fails ~1 request in 4 forever;
    pulling it out of rotation keeps the remaining keys serving.
    """
    _bump("auth_failures")
    digest = _digest_from_headers(headers)
    if not digest or code != 401:
        return
    state = _key_state.setdefault(digest, _new_key_state())
    state["consecutive_failures"] += 1
    if state["consecutive_failures"] < QUARANTINE_AFTER_401S:
        return
    try:
        _write_pat_status(digest, {
            "disabled": True,
            "quarantined_at": now_iso(),
            "reason": f"{state['consecutive_failures']} consecutive 401 responses",
        })
    except Exception as exc:  # a read-only config dir must not kill the sync
        log.warning("asana: could not persist quarantine for key %s: %s", digest, exc)
        return
    _bump("quarantined_keys")
    log.warning("asana: PAT %s quarantined after %d consecutive 401s",
                digest, state["consecutive_failures"])


def _error_body(e: urllib.error.HTTPError) -> str:
    try:
        return e.read(300).decode("utf-8", errors="replace")
    except Exception:
        return ""


def _request(headers: dict, path: str, *, params: dict | None = None,
             body: dict | None = None) -> dict:
    """One Asana call with retry, exponential+jittered backoff and telemetry.

    Shared by api_get/api_post so the two can never drift apart again.
    """
    tun = _tuning()
    url = f"{BASE_URL}{path}" if path.startswith("/") else path
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    payload = None
    req_headers = headers
    method = "GET"
    if body is not None:
        payload = json.dumps(body).encode("utf-8")
        req_headers = {**headers, "Content-Type": "application/json"}
        method = "POST"
    max_retries = tun["max_retries"]
    deadline = time.monotonic() + tun["timeout_buffer_s"]
    for attempt in range(1, max_retries + 1):
        req = urllib.request.Request(url, data=payload, headers=req_headers, method=method)
        _bump("requests")
        if attempt > 1:
            _bump("retries")
        try:
            with urllib.request.urlopen(req, timeout=tun["timeout_s"]) as resp:
                raw = resp.read().decode("utf-8")
            data = json.loads(raw)
            _bump("responses")
            _note_success(headers)
            return data
        except urllib.error.HTTPError as e:
            code = getattr(e, "code", 0)
            if code == 429:
                err_headers = getattr(e, "headers", None) or {}
                retry_after = _parse_retry_after(err_headers.get("Retry-After"))
                _bump("rate_limited")
                _record_retry_after(retry_after)
                with _stats_lock:
                    _stats["last_429_at"] = now_iso()
                log.warning("asana: 429 on %s (attempt %d/%d, Retry-After=%s)",
                            path, attempt, max_retries,
                            "n/a" if retry_after is None else f"{retry_after:.0f}s")
                if attempt >= max_retries:
                    break
                _sleep_backoff(
                    _backoff_delay(attempt, DEFAULT_RETRY_AFTER_S if retry_after is None
                                   else retry_after),
                    deadline, url)
                continue
            if code >= 500:
                _bump("server_errors")
                log.warning("asana: %d on %s (attempt %d/%d)", code, path, attempt, max_retries)
                if attempt >= max_retries:
                    break
                _sleep_backoff(_backoff_delay(attempt), deadline, url)
                continue
            detail = _error_body(e)
            if code in (401, 403):
                _note_auth_failure(headers, code)
            with _stats_lock:
                _stats["last_error"] = f"{code} on {path}"
            if code == 402:
                # /workspaces/{gid}/tasks/search (used by delta/recent/incremental modes) is a
                # premium-only Asana feature — a non-premium workspace gets 402 here, not a
                # generic auth/network error. Surface that distinctly so it's diagnosable
                # instead of reading as a mystery failure.
                raise RuntimeError(
                    "Asana API 402: task search requires a premium Asana workspace/team "
                    f"(endpoint: {path}). Delta/recent/incremental sync modes depend on this "
                    f"endpoint; mode='all' (full per-project scan) does not. Body: {detail}"
                )
            raise RuntimeError(f"Asana API {code}: {detail}")
        except urllib.error.URLError as e:
            _bump("network_errors")
            with _stats_lock:
                _stats["last_error"] = f"unreachable: {e}"
            # Check the attempt budget BEFORE sleeping: the old order burned a full
            # backoff sleep on the final attempt and then raised anyway.
            if attempt >= max_retries:
                raise RuntimeError(f"Asana API unreachable: {e}")
            _sleep_backoff(_backoff_delay(attempt), deadline, url)
    raise RuntimeError(f"Exceeded {max_retries} retries on 429/5xx for {url}")


def api_get(headers: dict, path: str, params: dict | None = None) -> dict:
    """GET with 429/5xx retry — mirrors asanaGet() from the Apps Script."""
    return _request(headers, path, params=params)


def api_post(headers: dict, path: str, body: dict) -> dict:
    """POST with the same 429/5xx retry/backoff as api_get.

    Task creation and comment posting used to bypass this entirely via a bare
    urllib POST in main.py (guarded by a `hasattr(asana_sync, "api_post")`
    check that was always False since this function never existed) — under
    load that meant those two write paths could trip Asana's 429s with no
    backoff at all, unlike every read call in this module.
    """
    return _request(headers, path, body=body)


def paginate(headers: dict, path: str, params: dict | None = None) -> list[dict]:
    """Paginate an Asana list endpoint (offset tokens), returning all items."""
    items: list[dict] = []
    p: dict = {"limit": _tuning()["batch_size"]}
    if params:
        p.update(params)
    while True:
        data = api_get(headers, path, p)
        items.extend(data.get("data", []) or [])
        nxt = data.get("next_page") or {}
        if nxt.get("offset"):
            p["offset"] = nxt["offset"]
        else:
            break
    return items


def paginate_search(headers: dict, path: str, params: dict) -> list[dict]:
    """Manually paginate Asana's workspace task-search endpoint.

    Unlike every other list endpoint, /workspaces/{gid}/tasks/search returns no next_page
    object at all — per developers.asana.com/reference/searchtasksforworkspace, search
    results "are not stable... the traditional pagination available elsewhere in the Asana
    API is not available here," and the docs instead direct callers to sort by a timestamp
    and advance the filter per page. Calling paginate() (offset-based) against this endpoint
    silently stops after the first page (<=100 items, BATCH_SIZE) since next_page never
    appears — for a large org, any window with more than 100 changed tasks would silently and
    permanently drop the rest. This sorts by modified_at ascending (matching the
    modified_at.after cursor this module already filters on) and advances that same filter to
    the last item's own modified_at after each full page.

    Known, accepted limitation: if >=100 tasks share the exact same modified_at timestamp at a
    page boundary, some could be split across pages in a way this can't fully reconcile (Asana
    offers no secondary/unique sort key on this endpoint) — astronomically unlikely in
    practice, and far better than the guaranteed silent truncation this replaces.
    """
    items: list[dict] = []
    p = dict(params)
    p["limit"] = BATCH_SIZE
    p["sort_by"] = "modified_at"
    p["sort_ascending"] = "true"
    seen_at_cursor: set[str] = set()
    while True:
        data = api_get(headers, path, p)
        page = data.get("data", []) or []
        items.extend(t for t in page if t.get("gid") not in seen_at_cursor)
        if len(page) < BATCH_SIZE:
            break
        last_modified = page[-1].get("modified_at")
        if not last_modified:
            break
        # modified_at.after is an exclusive lower bound, so advancing to the last item's own
        # modified_at won't return it again on the next page — except for tasks sharing that
        # exact timestamp, which seen_at_cursor guards against (harmless if .after turns out
        # to already exclude them).
        seen_at_cursor = {t.get("gid") for t in page if t.get("modified_at") == last_modified}
        p["modified_at.after"] = last_modified
    return items


# --- Weight rule (discovered: keepa tasks count 0.3) -------------------------
_KEEPA_RE = re.compile(r"keepa", re.IGNORECASE)


def task_weight(name: str) -> float:
    return 0.3 if _KEEPA_RE.search(name or "") else 1.0


def _cf_display(cf: dict) -> str:
    """Best display value for a custom field — mirrors taskCustomFieldMap()."""
    v = (
        cf.get("display_value")
        or (cf.get("enum_value") or {}).get("name")
        or ", ".join(x.get("name", "") for x in (cf.get("multi_enum_values") or []) if x.get("name"))
        or cf.get("text_value")
        or (str(cf["number_value"]) if cf.get("number_value") is not None else None)
        or (cf.get("date_value") or {}).get("date")
    )
    return v or ""


def _first_membership(task: dict) -> tuple[dict, dict]:
    """Return (primary membership, list of all memberships)."""
    memberships = task.get("memberships") or []
    primary = memberships[0] if memberships else {}
    return primary, memberships


# --- Sync orchestration ------------------------------------------------------
def sync_all(mode: str = "all", deep: bool = False,
             progress: Callable[[float, str], None] | None = None) -> dict:
    """Pull everything from Asana into SQLite.

    mode: 'all' (full refresh) | 'delta' (last N days via cfg['last_sync']) |
    'recent' (last 7 days) | 'incremental' (persistent Checkpoint cursor — see below).
    deep: also fetch stories/attachments/subtasks per task. For big orgs
    (e.g. 266k tasks) leave False — task details hydrate on demand when a
    task is opened.

    Incremental cursoring (mode='incremental'): uses sync_runner.Checkpoint (a durable,
    SQLite-backed cursor keyed by entity — "asana_tasks" here) instead of the ad hoc
    cfg['last_sync'] field 'delta'/'recent' use, so the cursor survives independently of
    asana.json and follows the same Checkpoint contract sync_runner.run_sync() uses for the
    hosted/local-fallback Supabase sync. On the first run (no checkpoint yet) it bootstraps
    with a full per-project scan, same strategy as mode='all'; afterwards it only asks Asana
    for tasks changed since the last checkpoint.
    """
    import storage

    cfg = _load_config()
    headers = _headers()
    started = now_iso()
    counts = {"projects": 0, "tasks": 0, "stories": 0, "subtasks": 0,
              "attachments": 0, "users": 0, "teams": 0, "custom_fields": 0,
              "workspaces": 0}

    def report(pct: float, msg: str) -> None:
        if progress:
            progress(pct, msg)

    # Batches local SQLite commits every 500 upserted rows instead of one commit per row —
    # see storage.batch_writes for why (a 266k-task workspace is 266k fsync'd commits
    # otherwise). Rows are still paginated from Asana and written to the DB one at a time as
    # they arrive; only the commit cadence changes.
    with storage.batch_writes(500):
        # 1) Workspaces
        report(1, "Fetching workspaces…")
        workspaces = paginate(headers, "/workspaces")
        for w in workspaces:
            storage.upsert_asana_workspace(gid=w["gid"], name=w.get("name", ""))
        counts["workspaces"] = len(workspaces)
        ws_gid = cfg.get("workspace_gid") or (workspaces[0]["gid"] if workspaces else "")
        if not ws_gid:
            raise RuntimeError("No Asana workspace found — set workspace_gid in Settings → Asana.")

        # 2) Users
        report(4, "Fetching users…")
        users = paginate(headers, f"/workspaces/{ws_gid}/users", {"opt_fields": "name,email"})
        for u in users:
            storage.upsert_asana_user(gid=u["gid"], name=u.get("name", ""), email=u.get("email", ""))
        counts["users"] = len(users)

        # 3) Teams (org endpoint, fallback derived from projects)
        report(6, "Fetching teams…")
        try:
            teams = paginate(headers, f"/organizations/{ws_gid}/teams",
                             {"opt_fields": "name,description"})
        except RuntimeError:
            teams = []
        for t in teams:
            storage.upsert_asana_team(gid=t["gid"], name=t.get("name", ""),
                                      description=t.get("description", ""))
        counts["teams"] = len(teams)

        # 4) Projects (workspace or portfolio source)
        report(8, "Fetching projects…")
        if cfg.get("project_source") == "portfolio":
            proj_gid = cfg.get("portfolio_gid") or DEFAULT_PORTFOLIO_GID
            projects = paginate(headers, f"/portfolios/{proj_gid}/items",
                                {"opt_fields": PROJECT_OPT_FIELDS})
        else:
            projects = paginate(headers, "/projects",
                                {"workspace": ws_gid, "opt_fields": PROJECT_OPT_FIELDS})
        active_projects = [p for p in projects if not p.get("archived")]
        for p in projects:
            team = p.get("team") or {}
            storage.upsert_asana_project(
                gid=p["gid"], name=p.get("name", ""), team_gid=team.get("gid", ""),
                team_name=team.get("name", ""), archived=1 if p.get("archived") else 0,
                color=p.get("color", ""), notes=p.get("notes", ""),
                created_at=p.get("created_at", ""), modified_at=p.get("modified_at", ""),
                permalink=p.get("permalink_url", ""),
            )
        counts["projects"] = len(projects)

        # 5) Custom field definitions — only in deep mode (bounded sample).
        #    Task rows already carry custom_fields name/value, so the catalog is
        #    a convenience; per-project settings = 1 call × every project, which
        #    is expensive in a 2,500-project workspace.
        report(10, "Fetching custom field definitions…")
        cf_seen: set[str] = set()
        if deep:
            for p in active_projects[:500]:
                try:
                    settings = paginate(headers, f"/projects/{p['gid']}/custom_field_settings",
                                        {"opt_fields": "custom_field.gid,custom_field.name,"
                                                        "custom_field.resource_subtype,"
                                                        "custom_field.description,"
                                                        "custom_field.enum_options.name"})
                except RuntimeError:
                    continue
                for s in settings:
                    cf = s.get("custom_field") or {}
                    gid = cf.get("gid")
                    if not gid or gid in cf_seen:
                        continue
                    cf_seen.add(gid)
                    storage.upsert_asana_custom_field(
                        gid=gid, name=cf.get("name", ""),
                        type=cf.get("resource_subtype", ""),
                        description=cf.get("description", ""),
                        enum_options=[e.get("name", "") for e in (cf.get("enum_options") or [])],
                    )
        counts["custom_fields"] = len(cf_seen)

        # 6) Tasks. 'all' = per-project full scan. 'delta'/'recent' = workspace search over
        #    tasks changed since a window. 'incremental' = workspace search since a persistent
        #    Checkpoint cursor. The windowed/incremental modes also pull stories/attachments/
        #    subtasks (bounded result set).
        proj_map = {p["gid"]: p for p in projects}
        fetched = 0

        def _scan_all_projects(label_prefix: str, *, deep_scan: bool) -> None:
            """Full per-project task scan — shared by mode='all' and the incremental
            bootstrap (first run, no checkpoint yet)."""
            nonlocal fetched
            total_projects = max(len(active_projects), 1)
            report(12, f"{label_prefix} — {len(active_projects)} projects…")
            for idx, proj in enumerate(active_projects):
                params: dict = {"project": proj["gid"], "opt_fields": TASK_OPT_FIELDS}
                for task in paginate(headers, "/tasks", params):
                    _store_task(storage, headers, task, proj_map, deep=deep_scan)
                    fetched += 1
                    counts["tasks"] += 1
                if (idx + 1) % 25 == 0 or idx == total_projects - 1:
                    report(min(95.0, 12 + (idx + 1) / total_projects * 83),
                           f"{label_prefix} — {idx + 1}/{len(active_projects)} projects, {fetched} tasks…")

        window = None
        checkpoint = None
        run_started_at = None
        if mode == "recent":
            window = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        elif mode == "delta" and cfg.get("last_sync"):
            window = cfg["last_sync"]
        elif mode == "delta":
            window = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        elif mode == "incremental":
            from sync_runner import Checkpoint  # local import: see module docstring for why

            checkpoint = Checkpoint()
            run_started_at = now_iso()
            window = checkpoint.get("asana_tasks")  # None on first run -> bootstrap below

        if window:
            report(12, f"Fetching tasks changed since {window[:10]} — workspace search…")
            # Asana's workspace task-search endpoint (POST /workspaces/{gid}/tasks/search,
            # issued here as a GET with query params like the rest of this module) filters on
            # `modified_at.after` (ISO-8601 datetime) — NOT `modified_since`. `modified_since`
            # is not a field this endpoint accepts; the only sibling of that shape here is
            # `completed_since`, on the unrelated plain /tasks-for-project listing endpoint.
            # Confirmed against developers.asana.com/reference/searchtasksforworkspace (2026-09).
            params_base: dict = {"opt_fields": TASK_OPT_FIELDS, "modified_at.after": window}
            for completed_flag in ("false", "true"):
                params = dict(params_base, completed=completed_flag)
                for task in paginate_search(headers, f"/workspaces/{ws_gid}/tasks/search", params):
                    _store_task(storage, headers, task, proj_map, deep=True)
                    fetched += 1
                    counts["tasks"] += 1
            if checkpoint is not None:
                # Only advance after this batch is fully stored (loop above has completed).
                checkpoint.advance("asana_tasks", run_started_at)
        elif mode == "incremental":
            # No checkpoint yet: bootstrap with a full per-project scan (same as mode='all'),
            # then start cursoring forward from this run's start time.
            _scan_all_projects("Bootstrapping incremental sync (no checkpoint yet)", deep_scan=deep)
            checkpoint.advance("asana_tasks", run_started_at)
        else:
            _scan_all_projects("Fetching tasks", deep_scan=deep)

    # 7) Done — record run + bump last_sync (report stored totals)
    final = storage.asana_counts()
    for k in ("projects", "tasks", "stories", "attachments", "subtasks",
              "users", "teams", "custom_fields"):
        if k in final:
            counts[k] = final[k]
    finished = now_iso()
    _save_config({**cfg, "last_sync": finished})
    storage.record_asana_run(mode=mode, status="done", started_at=started,
                             finished_at=finished, counts=counts, error="")
    report(100, f"Done — {counts['tasks']} tasks, {counts['stories']} comments, "
                f"{counts['attachments']} attachments, {counts['subtasks']} subtasks.")
    return counts


def _store_task(storage, headers: dict, task: dict, proj_map: dict,
                deep: bool = False) -> None:
    """Upsert one task; when deep=True also pull stories/attachments/subtasks.

    proj_map: {project_gid: project} — built from the workspace project list,
    used to attach team/name context from the task's memberships.
    """
    assignee = task.get("assignee") or {}
    parent = task.get("parent") or {}
    primary, memberships = _first_membership(task)
    section = (primary.get("section") or {}).get("name", "")
    proj_ref = primary.get("project") or {}
    project_gid = proj_ref.get("gid") or ""
    project_name = proj_ref.get("name") or ""
    proj = proj_map.get(project_gid) or {}
    team = proj.get("team") or {}
    if not project_name:
        project_name = proj.get("name", "")

    tags = [t.get("name", "") for t in (task.get("tags") or [])]
    followers = [f.get("name") or f.get("email", "") for f in (task.get("followers") or [])]
    deps = [d.get("gid", "") for d in (task.get("dependencies") or [])]
    dependents = [d.get("gid", "") for d in (task.get("dependents") or [])]

    custom_fields = []
    for cf in (task.get("custom_fields") or []):
        custom_fields.append({
            "gid": cf.get("gid", ""),
            "name": cf.get("name", ""),
            "type": cf.get("resource_subtype", ""),
            "value": _cf_display(cf),
            "raw": cf,
        })

    # Preserve every membership as a normalized fact: team KPI reporting cannot
    # depend on Asana's arbitrary first membership.
    membership_facts = []
    for membership in memberships:
        project_ref = membership.get("project") or {}
        project = proj_map.get(project_ref.get("gid")) or {}
        team_ref = project.get("team") or {}
        membership_facts.append({
            **membership,
            "team_gid": team_ref.get("gid", ""),
            "team_name": team_ref.get("name", ""),
        })

    storage.upsert_asana_task(
        gid=task["gid"], name=task.get("name", ""),
        resource_subtype=task.get("resource_type", ""),
        project_gid=project_gid, project_name=project_name,
        section=section, team_gid=team.get("gid", ""), team_name=team.get("name", ""),
        assignee_gid=assignee.get("gid", ""), assignee_name=assignee.get("name", ""),
        assignee_email=assignee.get("email", ""),
        due_on=task.get("due_on") or "", start_on=task.get("start_on") or "",
        completed=1 if task.get("completed") else 0,
        completed_at=task.get("completed_at") or "",
        created_at=task.get("created_at") or "",
        modified_at=task.get("modified_at") or "",
        permalink=task.get("permalink_url") or "",
        parent_gid=parent.get("gid", ""), parent_name=parent.get("name", ""),
        num_subtasks=int(task.get("num_subtasks") or 0),
        tags=tags, followers=followers, dependencies=deps, dependents=dependents,
        notes=task.get("notes") or "",
        custom_fields=custom_fields, memberships=membership_facts,
        weight=task_weight(task.get("name", "")),
    )
    storage.replace_asana_task_memberships(task["gid"], membership_facts)
    storage.replace_asana_task_custom_fields(task["gid"], custom_fields)

    # Stories / comments (deep sync only — lazy otherwise)
    if not deep:
        return
    try:
        stories = paginate(headers, f"/tasks/{task['gid']}/stories",
                           {"opt_fields": "gid,type,text,created_at,is_pinned,"
                                          "created_by.name,created_by.email"})
    except RuntimeError:
        stories = []
    for s in stories:
        author = s.get("created_by") or {}
        storage.upsert_asana_story(
            gid=s["gid"], task_gid=task["gid"], author=author.get("name", ""),
            author_email=author.get("email", ""),
            type="comment" if s.get("type") == "comment" else "system",
            text=s.get("text", ""), created_at=s.get("created_at", ""),
            is_pinned=1 if s.get("is_pinned") else 0,
        )
    # Attachments (inline from opt_fields)
    for a in (task.get("attachments") or []):
        storage.upsert_asana_attachment(
            gid=a["gid"], task_gid=task["gid"], name=a.get("name", ""),
            host=a.get("host", ""),
            url=a.get("download_url") or a.get("permanent_url") or "",
            view_url=a.get("view_url", ""), created_at=a.get("created_at", ""),
        )
    # Subtasks
    if task.get("num_subtasks"):
        try:
            subtasks = paginate(headers, f"/tasks/{task['gid']}/subtasks",
                                {"opt_fields": "gid,name,completed,completed_at,"
                                               "created_at,due_on,assignee.name,"
                                               "assignee.email,permalink_url"})
        except RuntimeError:
            subtasks = []
        for st in subtasks:
            st_assignee = st.get("assignee") or {}
            storage.upsert_asana_subtask(
                gid=st["gid"], parent_task_gid=task["gid"], name=st.get("name", ""),
                assignee_name=st_assignee.get("name", ""),
                assignee_email=st_assignee.get("email", ""),
                completed=1 if st.get("completed") else 0,
                completed_at=st.get("completed_at") or "",
                created_at=st.get("created_at") or "",
                due_on=st.get("due_on") or "",
                permalink=st.get("permalink_url") or "",
            )


def fetch_task_details(gid: str) -> dict:
    """Lazy-hydrate one task's stories/attachments/subtasks from Asana.

    Called on demand when a task detail is opened (deep sync is too slow
    for 266k tasks). Stores whatever it pulls, returns the fresh rows.
    """
    import storage

    headers = _headers()
    stories: list[dict] = []
    try:
        stories = paginate(headers, f"/tasks/{gid}/stories",
                           {"opt_fields": "gid,type,text,created_at,is_pinned,"
                                          "created_by.name,created_by.email"})
    except RuntimeError:
        pass
    for s in stories:
        author = s.get("created_by") or {}
        storage.upsert_asana_story(
            gid=s["gid"], task_gid=gid, author=author.get("name", ""),
            author_email=author.get("email", ""),
            type="comment" if s.get("type") == "comment" else "system",
            text=s.get("text", ""), created_at=s.get("created_at", ""),
            is_pinned=1 if s.get("is_pinned") else 0,
        )

    attachments: list[dict] = []
    try:
        attachments = paginate(headers, f"/tasks/{gid}/attachments",
                               {"opt_fields": "gid,name,host,download_url,"
                                              "view_url,permanent_url,created_at"})
    except RuntimeError:
        pass
    for a in attachments:
        storage.upsert_asana_attachment(
            gid=a["gid"], task_gid=gid, name=a.get("name", ""), host=a.get("host", ""),
            url=a.get("download_url") or a.get("permanent_url") or "",
            view_url=a.get("view_url", ""), created_at=a.get("created_at", ""),
        )

    subtasks: list[dict] = []
    task = storage.get_asana_task(gid)
    if task and task.get("num_subtasks"):
        try:
            subtasks = paginate(headers, f"/tasks/{gid}/subtasks",
                                {"opt_fields": "gid,name,completed,completed_at,"
                                               "created_at,due_on,assignee.name,"
                                               "assignee.email,permalink_url"})
        except RuntimeError:
            subtasks = []
        for st in subtasks:
            st_assignee = st.get("assignee") or {}
            storage.upsert_asana_subtask(
                gid=st["gid"], parent_task_gid=gid, name=st.get("name", ""),
                assignee_name=st_assignee.get("name", ""),
                assignee_email=st_assignee.get("email", ""),
                completed=1 if st.get("completed") else 0,
                completed_at=st.get("completed_at") or "",
                created_at=st.get("created_at") or "",
                due_on=st.get("due_on") or "",
                permalink=st.get("permalink_url") or "",
            )

    return {
        "stories": storage.list_asana_stories(gid),
        "attachments": storage.list_asana_attachments(gid),
        "subtasks": storage.list_asana_subtasks(gid),
    }
