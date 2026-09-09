"""Tests for backend/asana_sync.py's paginate_search().

Regression coverage for a real, silent data-loss bug: Asana's workspace task-search endpoint
(/workspaces/{gid}/tasks/search) returns no `next_page` object at all, unlike every other
Asana list endpoint. paginate() (offset-based) relies on `next_page.offset` to keep going, so
calling it against search silently stops after the first page (<=100 items) and drops the rest
of any larger changed-task batch. paginate_search() must instead manually advance the
modified_at.after filter itself.
"""
from __future__ import annotations

import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))
sys.path.insert(0, str(APP_DIR / "backend"))

import asana_sync


def test_paginate_search_handles_multi_page_results(monkeypatch):
    """A page of exactly BATCH_SIZE items must not be treated as the last page — paginate()
    would stop here (no next_page ever appears from this endpoint); paginate_search must keep
    going by advancing modified_at.after to the last item's own timestamp."""
    page1 = [{"gid": f"t{i}", "modified_at": f"2026-01-01T00:00:{i:02d}.000Z"} for i in range(100)]
    page2 = [{"gid": f"t{100 + i}", "modified_at": f"2026-01-01T00:01:{i:02d}.000Z"} for i in range(30)]
    calls: list[dict] = []

    def fake_api_get(headers, path, params=None):
        calls.append(dict(params or {}))
        return {"data": page1} if len(calls) == 1 else {"data": page2}

    monkeypatch.setattr(asana_sync, "api_get", fake_api_get)
    items = asana_sync.paginate_search(
        {}, "/workspaces/x/tasks/search", {"modified_at.after": "2026-01-01T00:00:00.000Z"}
    )

    assert len(items) == 130
    assert items[0]["gid"] == "t0"
    assert items[-1]["gid"] == "t129"
    assert len(calls) == 2, "must issue a second request instead of stopping after one page"
    assert calls[1]["modified_at.after"] == "2026-01-01T00:00:99.000Z"
    assert calls[1]["sort_by"] == "modified_at"
    assert calls[1]["sort_ascending"] == "true"
    assert calls[1]["limit"] == 100


def test_paginate_search_stops_on_short_page(monkeypatch):
    """A page shorter than BATCH_SIZE means there is nothing left to fetch."""
    page = [{"gid": "only-one", "modified_at": "2026-01-01T00:00:00.000Z"}]
    calls: list[dict] = []

    def fake_api_get(headers, path, params=None):
        calls.append(dict(params or {}))
        return {"data": page}

    monkeypatch.setattr(asana_sync, "api_get", fake_api_get)
    items = asana_sync.paginate_search({}, "/workspaces/x/tasks/search", {"modified_at.after": "x"})

    assert len(calls) == 1
    assert [it["gid"] for it in items] == ["only-one"]


def test_paginate_search_dedupes_boundary_ties(monkeypatch):
    """If modified_at.after turns out to be inclusive (or Asana returns boundary-timestamp
    tasks again), paginate_search must not double-count tasks that reappear across pages."""
    page1 = [{"gid": f"t{i}", "modified_at": "2026-01-01T00:00:00.000Z"} for i in range(100)]
    page2 = (
        [{"gid": f"t{i}", "modified_at": "2026-01-01T00:00:00.000Z"} for i in range(95, 100)]
        + [{"gid": f"t{100 + i}", "modified_at": "2026-01-01T00:01:00.000Z"} for i in range(10)]
    )
    calls: list[dict] = []

    def fake_api_get(headers, path, params=None):
        calls.append(dict(params or {}))
        return {"data": page1} if len(calls) == 1 else {"data": page2}

    monkeypatch.setattr(asana_sync, "api_get", fake_api_get)
    items = asana_sync.paginate_search(
        {}, "/workspaces/x/tasks/search", {"modified_at.after": "2020-01-01T00:00:00.000Z"}
    )

    gids = [it["gid"] for it in items]
    assert len(gids) == len(set(gids)), f"duplicate gids returned across pages: {gids}"
    assert len(items) == 110  # 100 from page1 + 10 genuinely new from page2
