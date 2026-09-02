"""Schema-flexible Conductor ↔ Supabase synchronization.

The module deliberately does not import Conductor's storage layer. Callers inject a
``LocalAdapter`` for each supported entity so the API can be wired without coupling
this transport to SQLite's current schema.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from uuid import uuid4

import requests
from fastapi import APIRouter, HTTPException

CONFIG_PATH = Path(__file__).resolve().parent.parent / "data" / "supabase.json"
SUPPORTED_ENTITIES = frozenset({"products", "asana_tasks"})
router = APIRouter(prefix="/api/supabase", tags=["supabase-sync"])


@dataclass(frozen=True)
class LocalAdapter:
    """Callbacks describing one local entity collection.

    ``list_records`` must return JSON-serializable mappings. ``upsert_record``
    applies one remote payload idempotently in local storage.
    """

    list_records: Callable[[], Iterable[dict[str, Any]]]
    upsert_record: Callable[[dict[str, Any]], Any]
    key_field: str
    updated_field: str | None = None


def _load_config() -> dict[str, str]:
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        raw = {}
    return {
        "url": str(raw.get("url") or "").strip().rstrip("/"),
        "service_key": str(raw.get("service_key") or "").strip(),
        "schema": str(raw.get("schema") or "public").strip() or "public",
    }


def get_status() -> dict[str, Any]:
    """Return connection configuration without exposing credentials."""
    cfg = _load_config()
    key = cfg["service_key"]
    return {
        "configured": bool(cfg["url"] and key),
        "url": cfg["url"],
        "has_service_key": bool(key),
        "service_key_masked": f"****{key[-4:]}" if key else "",
        "schema": cfg["schema"],
    }


def save_config(*, url: str, service_key: str, schema: str = "public") -> dict[str, Any]:
    """Persist Supabase REST credentials and return their redacted status."""
    schema = str(schema or "public").strip() or "public"
    if not schema.replace("_", "a").isalnum() or schema[0].isdigit():
        raise ValueError("schema must be a valid PostgreSQL identifier")
    cfg = {
        "url": str(url or "").strip().rstrip("/"),
        "service_key": str(service_key or "").strip(),
        "schema": schema,
    }
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return get_status()


def _headers(cfg: dict[str, str]) -> dict[str, str]:
    return {
        "apikey": cfg["service_key"],
        "Authorization": f"Bearer {cfg['service_key']}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _request(
    method: str,
    resource: str,
    *,
    session: Any,
    params: dict[str, Any] | None = None,
    json_body: Any = None,
    headers: dict[str, str] | None = None,
    config: dict[str, str] | None = None,
):
    cfg = config or _load_config()
    if not cfg["url"] or not cfg["service_key"]:
        raise RuntimeError("Supabase URL and service key are not configured")
    merged_headers = {**_headers(cfg), **(headers or {})}
    profile_header = "Accept-Profile" if method.upper() in {"GET", "HEAD"} else "Content-Profile"
    merged_headers[profile_header] = cfg.get("schema") or "public"
    response = session.request(
        method,
        f"{cfg['url']}/rest/v1/{resource}",
        params=params,
        json=json_body,
        headers=merged_headers,
        timeout=30,
    )
    response.raise_for_status()
    return response


def test_connection(*, session: Any = requests, config: dict[str, str] | None = None) -> dict[str, Any]:
    """Probe the mirror table, returning a credential-redacted result."""
    try:
        _request(
            "GET",
            "conductor_records",
            session=session,
            params={"select": "entity_type", "limit": 1},
            config=config,
        )
    except Exception as exc:
        return {"ok": False, "message": f"Supabase connection failed: {exc}"}
    return {"ok": True, "message": "Connected to Supabase"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _push_entity(
    entity_type: str, adapter: LocalAdapter, *, session: Any
) -> int:
    rows_by_key: dict[str, dict[str, Any]] = {}
    for record in adapter.list_records():
        key = record.get(adapter.key_field)
        if key is None or str(key).strip() == "":
            raise ValueError(
                f"{entity_type} record is missing key field {adapter.key_field!r}"
            )
        rows_by_key[str(key)] = {
            "entity_type": entity_type,
            "record_key": str(key),
            "payload": record,
            "source_updated_at": (
                record.get(adapter.updated_field) if adapter.updated_field else None
            ),
        }
    rows = list(rows_by_key.values())
    if rows:
        _request(
            "POST",
            "conductor_records",
            session=session,
            params={"on_conflict": "entity_type,record_key"},
            json_body=rows,
            headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
        )
    return len(rows)


def _timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _pull_entity(
    entity_type: str, adapter: LocalAdapter, *, conflict: str, session: Any
) -> tuple[int, int]:
    remote_rows: list[dict[str, Any]] = []
    page_size = 1000
    offset = 0
    while True:
        response = _request(
            "GET",
            "conductor_records",
            session=session,
            params={
                "entity_type": f"eq.{entity_type}",
                "select": "record_key,payload,source_updated_at",
                "order": "record_key.asc",
            },
            headers={"Range": f"{offset}-{offset + page_size - 1}"},
        )
        page = response.json() or []
        remote_rows.extend(page)
        if len(page) < page_size:
            break
        offset += page_size
    pulled = skipped = 0
    local_by_key = {
        str(record.get(adapter.key_field)): record
        for record in adapter.list_records()
        if record.get(adapter.key_field) is not None
    }
    for row in remote_rows:
        payload = row.get("payload") if isinstance(row, dict) else None
        if not isinstance(payload, dict):
            skipped += 1
            continue
        local = local_by_key.get(str(row.get("record_key")))
        if local is not None and conflict == "local":
            skipped += 1
            continue
        if local is not None and conflict == "newest" and adapter.updated_field:
            local_time = _timestamp(local.get(adapter.updated_field))
            remote_time = _timestamp(row.get("source_updated_at") or payload.get(adapter.updated_field))
            if local_time and remote_time and local_time > remote_time:
                skipped += 1
                continue
        adapter.upsert_record(payload)
        pulled += 1
    return pulled, skipped


def sync(
    *,
    direction: str,
    adapters: dict[str, LocalAdapter],
    conflict: str = "newest",
    session: Any = requests,
) -> dict[str, Any]:
    """Synchronize injected local collections with the Supabase JSONB mirror."""
    if direction not in {"push", "pull", "bidirectional"}:
        raise ValueError("direction must be push, pull, or bidirectional")
    if conflict not in {"newest", "local", "remote"}:
        raise ValueError("conflict must be newest, local, or remote")
    unknown = set(adapters) - SUPPORTED_ENTITIES
    if unknown:
        raise ValueError(f"unsupported entities: {', '.join(sorted(unknown))}")

    run_id = str(uuid4())
    started_at = _now()
    counts = {"pushed": 0, "pulled": 0, "skipped": 0}
    _request(
        "POST",
        "sync_runs",
        session=session,
        json_body={
            "id": run_id,
            "direction": direction,
            "conflict_policy": conflict,
            "status": "running",
            "started_at": started_at,
            "counts": counts,
        },
        headers={"Prefer": "return=minimal"},
    )
    try:
        if direction in {"pull", "bidirectional"}:
            for entity_type, adapter in adapters.items():
                pulled, skipped = _pull_entity(
                    entity_type, adapter, conflict=conflict, session=session
                )
                counts["pulled"] += pulled
                counts["skipped"] += skipped
        if direction in {"push", "bidirectional"}:
            for entity_type, adapter in adapters.items():
                counts["pushed"] += _push_entity(entity_type, adapter, session=session)
    except Exception as exc:
        try:
            _request(
                "PATCH", "sync_runs", session=session,
                params={"id": f"eq.{run_id}"},
                json_body={
                    "status": "error", "finished_at": _now(), "counts": counts,
                    "error": f"{type(exc).__name__}: {exc}"[:1000],
                },
                headers={"Prefer": "return=minimal"},
            )
        finally:
            raise
    _request(
        "PATCH",
        "sync_runs",
        session=session,
        params={"id": f"eq.{run_id}"},
        json_body={
            "status": "done",
            "finished_at": _now(),
            "counts": counts,
            "error": "",
        },
        headers={"Prefer": "return=minimal"},
    )
    return {
        "run_id": run_id,
        "direction": direction,
        "conflict_policy": conflict,
        "status": "done",
        "counts": counts,
    }


def _product_upsert(record: dict[str, Any]) -> None:
    import storage

    sku = str(record.get("sku") or "").strip()
    name = str(record.get("name") or "").strip()
    if not sku or not name:
        raise ValueError("Supabase product requires sku and name")
    existing = storage._conn().execute(
        "SELECT id FROM products WHERE sku=? ORDER BY id LIMIT 1", (sku,)
    ).fetchone()
    fields = {
        "sku": sku,
        "name": name,
        "category": str(record.get("category") or "general"),
        "market": str(record.get("market") or "US"),
        "attributes": record.get("attributes") if isinstance(record.get("attributes"), dict) else {},
        "source": str(record.get("source") or "supabase"),
        "file_id": record.get("file_id"),
    }
    if existing:
        storage.update_product(int(existing["id"]), **fields)
    else:
        storage.create_product(**fields)


def _asana_task_upsert(record: dict[str, Any]) -> None:
    import storage

    gid = str(record.get("gid") or "").strip()
    if not gid:
        raise ValueError("Supabase Asana task requires gid")
    allowed = {
        "gid", "name", "resource_subtype", "project_gid", "project_name", "section",
        "team_gid", "team_name", "assignee_gid", "assignee_name", "assignee_email",
        "due_on", "start_on", "completed", "completed_at", "created_at", "modified_at",
        "permalink", "parent_gid", "parent_name", "num_subtasks", "tags", "followers",
        "dependencies", "dependents", "notes", "custom_fields", "memberships", "weight",
    }
    payload = {key: value for key, value in record.items() if key in allowed}
    payload["gid"] = gid
    payload["synced_at"] = storage.now_iso()
    # merge_upsert (not _upsert/INSERT OR REPLACE): a Supabase-sourced record can omit
    # locally-only derived fields such as `weight` (computed by asana_sync.task_weight(),
    # never returned by Asana's own API) — a blanket REPLACE would silently zero those
    # columns out on every pull and corrupt KPI weighting. See storage.merge_upsert's
    # docstring for the full rationale.
    storage.merge_upsert("asana_tasks", "gid", payload)


def local_adapters(entity: str) -> dict[str, LocalAdapter]:
    import storage

    if entity == "products":
        return {"products": LocalAdapter(lambda: storage.list_products(100000), _product_upsert, "sku", "updated_at")}
    if entity in {"asana", "asana_tasks"}:
        return {"asana_tasks": LocalAdapter(lambda: storage.list_asana_tasks(limit=100000), _asana_task_upsert, "gid", "modified_at")}
    raise ValueError("dataset must be products or asana")


def read_entity(entity_type: str, *, limit: int = 500, session: Any = requests) -> list[dict[str, Any]]:
    """Read one entity's normalized rows back out of the Supabase mirror.

    This is the server-side read path: Conductor's frontend must read Asana (or any other
    synced entity) data through the FastAPI backend rather than calling Asana directly with a
    browser-held token. The backend alone holds the Supabase service-role key (via
    ``_load_config``/``CONFIG_PATH``) and the Asana PAT (via ``asana_sync``'s own config) —
    neither ever appears in a response body. ``conductor_records.payload`` already stores each
    entity's full record (see ``_push_entity``); this just unwraps that JSONB envelope back
    into plain dicts, newest first by ``source_updated_at``.
    """
    if entity_type not in SUPPORTED_ENTITIES:
        raise ValueError(f"unsupported entity: {entity_type}")
    response = _request(
        "GET",
        "conductor_records",
        session=session,
        params={
            "entity_type": f"eq.{entity_type}",
            "select": "record_key,payload,source_updated_at,synced_at",
            "order": "source_updated_at.desc.nullslast,record_key.asc",
            "limit": min(max(limit, 1), 5000),
        },
    )
    rows = response.json() or []
    return [row["payload"] for row in rows if isinstance(row, dict) and isinstance(row.get("payload"), dict)]


def list_runs(limit: int = 20, *, session: Any = requests) -> list[dict[str, Any]]:
    if not get_status()["configured"]:
        return []
    response = _request(
        "GET", "sync_runs", session=session,
        params={"select": "*", "order": "started_at.desc", "limit": min(max(limit, 1), 100)},
    )
    return response.json() or []


@router.get("/status")
def api_status() -> dict[str, Any]:
    return get_status()


@router.post("/config")
def api_config(body: dict[str, Any]) -> dict[str, Any]:
    current = _load_config()
    url = str(body.get("url") or current["url"]).strip().rstrip("/")
    supplied_key = str(body.get("service_key") or "").strip()
    if url != current["url"] and not supplied_key:
        raise HTTPException(400, "Changing the Supabase URL requires a new service-role key")
    key = supplied_key or current["service_key"]
    schema = str(body.get("schema") or current["schema"] or "public").strip()
    if not url or not key:
        raise HTTPException(400, "Supabase URL and service-role key are required")
    try:
        return save_config(url=url, service_key=key, schema=schema)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/test")
def api_test(body: dict[str, Any] | None = None) -> dict[str, Any]:
    current = _load_config()
    body = body or {}
    supplied_key = str(body.get("service_key") or "").strip()
    url = str(body.get("url") or current["url"]).strip().rstrip("/")
    if url != current["url"] and not supplied_key:
        raise HTTPException(400, "Testing a different Supabase URL requires its service-role key")
    config = {
        "url": url,
        "service_key": supplied_key or current["service_key"],
        "schema": str(body.get("schema") or current["schema"] or "public").strip(),
    }
    return test_connection(config=config)


@router.get("/runs")
def api_runs(limit: int = 20) -> list[dict[str, Any]]:
    try:
        return list_runs(limit)
    except Exception as exc:
        raise HTTPException(502, f"Supabase run history failed: {type(exc).__name__}") from exc


@router.get("/records/{entity}")
def api_read_records(entity: str, limit: int = 500) -> list[dict[str, Any]]:
    """Server-side normalized read path — see read_entity() docstring.

    Never returns credentials: the response is exactly the list of stored payload dicts.
    """
    try:
        return read_entity(entity, limit=limit)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, f"Supabase read failed: {type(exc).__name__}") from exc


@router.post("/sync/{dataset}/{direction}")
def api_sync(dataset: str, direction: str) -> dict[str, Any]:
    try:
        result = sync(direction=direction, adapters=local_adapters(dataset))
        total = result["counts"]["pushed"] + result["counts"]["pulled"]
        result.update(ok=True, count=total, dataset=dataset,
                      message=f"{direction.title()} synced {total} {dataset.replace('_', ' ')} records")
        return result
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, f"Supabase sync failed: {type(exc).__name__}: {exc}") from exc
