"""Spine FastAPI routes — local-first snapshot/glossary/models/nodes/filters/config."""
from __future__ import annotations

from fastapi import APIRouter

import storage
from spine import active, preferred, user_config
from spine.user_config import _decode

router = APIRouter(prefix="/api/spine", tags=["spine"])


@router.get("/snapshot")
def snapshot() -> dict:
    """Single local-first payload for glossary, model picker and global filters."""
    conn = storage._conn()
    return {
        "registry": [_decode(r, ("capabilities", "metadata")) for r in conn.execute("SELECT * FROM spine_registry ORDER BY kind,label")],
        "statuses": [_decode(r, ("metadata",)) for r in conn.execute("SELECT * FROM spine_status_definitions ORDER BY sort_order")],
        "lifecycles": [_decode(r, ("transitions", "metadata")) for r in conn.execute("SELECT * FROM spine_lifecycle_definitions ORDER BY sort_order")],
        "file_types": [_decode(r, ("mime_types", "metadata")) for r in conn.execute("SELECT * FROM spine_file_type_definitions ORDER BY category,label")],
        "models": [_decode(r, ("capabilities", "input_modalities", "output_modalities", "metadata")) for r in conn.execute("SELECT * FROM spine_model_catalog WHERE is_active=1 ORDER BY provider_id,model_id")],
        "model_presets": [_decode(r, ("parameters", "metadata")) for r in conn.execute("SELECT * FROM spine_model_presets WHERE enabled=1 ORDER BY label")],
        "nodes": [_decode(r, ("input_schema", "output_schema", "config_schema", "metadata")) for r in conn.execute("SELECT * FROM spine_node_library WHERE enabled=1 ORDER BY category,label")],
        "datasets": [_decode(r, ("schema_definition", "source_config", "metadata")) for r in conn.execute("SELECT * FROM spine_datasets ORDER BY label")],
        "filters": [_decode(r, ("options_source", "default_value", "metadata")) for r in conn.execute("SELECT * FROM spine_global_filter_definitions WHERE enabled=1 ORDER BY sort_order")],
    }


@router.get("/glossary")
def glossary(q: str = "", kind: str = "") -> dict:
    query = q.strip().lower()
    items = snapshot()["registry"]
    if kind:
        items = [x for x in items if x["kind"] == kind]
    if query:
        items = [x for x in items if query in (x["label"] + " " + x["description"] + " " + x["registry_key"]).lower()]
    return {"count": len(items), "items": items}


@router.get("/models")
def models() -> dict:
    data = snapshot()
    return {"models": data["models"], "presets": data["model_presets"]}


@router.get("/models/preferred")
def get_preferred_model() -> dict:
    return preferred.get_preferred()


@router.put("/models/preferred")
def put_preferred_model(body: dict) -> dict:
    return preferred.set_preferred(body)


@router.delete("/models/preferred")
def delete_preferred_model() -> dict:
    return preferred.clear_preferred()


@router.get("/models/active")
def get_active_model() -> dict:
    return active.resolve_active_chat_target()


@router.get("/nodes")
def nodes() -> dict:
    return {"nodes": snapshot()["nodes"]}


@router.get("/filters")
def filters() -> dict:
    return {"filters": snapshot()["filters"]}


@router.put("/config/{scope}/{key}")
def put_configuration(scope: str, key: str, body: dict) -> dict:
    return user_config.put_configuration(scope, key, body)


@router.get("/config/{scope}/{key}")
def get_configuration(scope: str, key: str) -> dict:
    return user_config.get_configuration(scope, key)


@router.post("/sync/push")
def sync_push() -> dict:
    """Manually push the spine's default/user-config state to the
    conductor.* Supabase mirror (backend/spine_sync.py). Push-only — the
    spine's local SQLite tables are always authoritative; this never reads
    anything back. Returns {"status": "skipped", "reason": "supabase_not_configured"}
    when no Supabase credentials are saved (Settings -> Integrations -> Supabase)."""
    import spine_sync

    return spine_sync.push_all()
