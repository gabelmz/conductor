"""Unified Cross-Channel Search Engine.

Searches in parallel across local Catalog Products, Asana Tasks, Keepa Market,
and Supabase Live Products, calculating cross-channel coverage gaps.

Router prefix: /api/search
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from fastapi import APIRouter, HTTPException, Query

import storage
import data

router = APIRouter(prefix="/api/search", tags=["search"])


def _search_catalog_products(q: str, limit: int = 20) -> list[dict[str, Any]]:
    """Search local catalog products table."""
    try:
        rows = storage.list_products(limit=limit * 2)
        results = []
        ql = q.lower()
        for p in rows:
            sku = str(p.get("sku") or "")
            name = str(p.get("name") or "")
            cat = str(p.get("category") or "")
            if ql in sku.lower() or ql in name.lower() or ql in cat.lower():
                results.append({
                    "id": str(p["id"]),
                    "title": name or sku,
                    "sku": sku,
                    "channel": "catalog",
                    "category": cat,
                    "market": p.get("market") or "US",
                    "source": p.get("source") or "local",
                    "created_at": p.get("created_at") or "",
                })
                if len(results) >= limit:
                    break
        return results
    except Exception:
        return []


def _search_asana_tasks(q: str, limit: int = 20) -> list[dict[str, Any]]:
    """Search local Asana task mirror."""
    try:
        rows = storage.list_asana_tasks(limit=limit * 3)
        results = []
        ql = q.lower()
        for t in rows:
            name = str(t.get("name") or "")
            gid = str(t.get("gid") or "")
            proj = str(t.get("project_name") or "")
            if ql in name.lower() or ql in proj.lower() or ql in gid:
                results.append({
                    "id": gid,
                    "title": name,
                    "channel": "asana",
                    "project": proj,
                    "assignee": t.get("assignee_name") or "",
                    "completed": bool(t.get("completed")),
                    "due_on": t.get("due_on") or "",
                })
                if len(results) >= limit:
                    break
        return results
    except Exception:
        return []


def _search_keepa_market(q: str, limit: int = 20) -> list[dict[str, Any]]:
    """Search local keepa query cache / live keepa lookup."""
    try:
        import keepa
        rows = keepa.search_keepa(q) if hasattr(keepa, "search_keepa") else []
        results = []
        for item in rows[:limit]:
            title = str(item.get("title") or item.get("asin") or "")
            results.append({
                "id": str(item.get("asin") or title),
                "title": title,
                "channel": "keepa",
                "asin": item.get("asin") or "",
                "brand": item.get("brand") or "",
                "price": item.get("price") or item.get("current_price"),
            })
        return results
    except Exception:
        return []


def _search_supabase_live(q: str, limit: int = 20) -> list[dict[str, Any]]:
    """Search Supabase product schema."""
    try:
        rows = data._supabase_rows("product", "products", limit=limit, q=q)
        results = []
        for r in rows:
            sku = str(r.get("sku") or r.get("id") or "")
            name = str(r.get("name") or r.get("title") or sku)
            results.append({
                "id": str(r.get("id") or sku),
                "title": name,
                "sku": sku,
                "channel": "supabase",
                "brand": r.get("brand") or "",
                "created_at": r.get("created_at") or "",
            })
        return results
    except Exception:
        return []


def compute_gap_analysis(all_results: list[dict[str, Any]]) -> dict[str, Any]:
    """Calculate cross-channel coverage and flag gaps across channels."""
    entities: dict[str, set[str]] = {}

    for item in all_results:
        key = (item.get("sku") or item.get("title") or item.get("id") or "").strip().lower()
        if not key:
            continue
        entities.setdefault(key, set()).add(item["channel"])

    all_channels = {"catalog", "asana", "keepa", "supabase"}
    gap_reports = []

    for key, channels in entities.items():
        missing = sorted(list(all_channels - channels))
        coverage_pct = round((len(channels) / len(all_channels)) * 100, 1)
        gap_reports.append({
            "key": key,
            "present_channels": sorted(list(channels)),
            "missing_channels": missing,
            "coverage_pct": coverage_pct,
            "has_gap": len(missing) > 0,
        })

    gap_reports.sort(key=lambda x: x["coverage_pct"])
    return {
        "total_unique_keys": len(entities),
        "items_with_gaps": sum(1 for g in gap_reports if g["has_gap"]),
        "channel_matrix": gap_reports[:20],
    }


@router.get("/global")
def global_search(q: str = Query(..., min_length=1), limit: int = Query(20, ge=1, le=100)):
    """Search across Catalog Products, Asana Tasks, Keepa, and Supabase in parallel."""
    results_by_channel = {"catalog": [], "asana": [], "keepa": [], "supabase": []}
    all_flat = []

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(_search_catalog_products, q, limit): "catalog",
            executor.submit(_search_asana_tasks, q, limit): "asana",
            executor.submit(_search_keepa_market, q, limit): "keepa",
            executor.submit(_search_supabase_live, q, limit): "supabase",
        }
        for future in as_completed(futures):
            ch = futures[future]
            try:
                res = future.result()
                results_by_channel[ch] = res
                all_flat.extend(res)
            except Exception:
                results_by_channel[ch] = []

    gap_analysis = compute_gap_analysis(all_flat)

    return {
        "query": q,
        "total_matches": len(all_flat),
        "results_by_channel": results_by_channel,
        "results_flat": all_flat,
        "gap_analysis": gap_analysis,
    }
