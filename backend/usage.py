"""Parker — cumulative LLM token usage counter.

Tracks input/output token totals across chat calls (DeepSeek + local llama)
and persists a snapshot to data/usage.json so totals survive restarts.

Module-level counters (single-user desktop app):
  - record(input_tokens, output_tokens)  accumulate one chat call
  - get()                                current totals (copy)
  - reset()                              zero the counters
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
USAGE_PATH = DATA_DIR / "usage.json"

_lock = threading.Lock()
_input_tokens = 0
_output_tokens = 0
_calls = 0
_updated_at = ""


def _load() -> None:
    global _input_tokens, _output_tokens, _calls, _updated_at
    try:
        if USAGE_PATH.exists():
            d = json.loads(USAGE_PATH.read_text(encoding="utf-8"))
            _input_tokens = int(d.get("input_tokens") or 0)
            _output_tokens = int(d.get("output_tokens") or 0)
            _calls = int(d.get("calls") or 0)
            _updated_at = str(d.get("updated_at") or "")
    except Exception:
        pass


def _save() -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        USAGE_PATH.write_text(
            json.dumps(
                {
                    "input_tokens": _input_tokens,
                    "output_tokens": _output_tokens,
                    "total_tokens": _input_tokens + _output_tokens,
                    "calls": _calls,
                    "updated_at": _updated_at,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception:
        pass


_load()


def record(input_tokens: int = 0, output_tokens: int = 0) -> None:
    """Accumulate one chat call's token usage and persist the snapshot."""
    global _input_tokens, _output_tokens, _calls, _updated_at
    with _lock:
        _input_tokens += max(int(input_tokens or 0), 0)
        _output_tokens += max(int(output_tokens or 0), 0)
        _calls += 1
        _updated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        _save()


def get() -> dict:
    with _lock:
        return {
            "input_tokens": _input_tokens,
            "output_tokens": _output_tokens,
            "total_tokens": _input_tokens + _output_tokens,
            "calls": _calls,
            "updated_at": _updated_at,
        }


def reset() -> dict:
    global _input_tokens, _output_tokens, _calls, _updated_at
    with _lock:
        _input_tokens = 0
        _output_tokens = 0
        _calls = 0
        _updated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        _save()
    return get()
