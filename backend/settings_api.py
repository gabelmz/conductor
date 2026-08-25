"""HTTP surface for the generic settings store (``settings.py``).

GET    /api/settings             -> merged resolve() view (for editors)
GET    /api/settings/{key}       -> {"key", "value"}
PUT    /api/settings/{key}       -> {"key", "value"}   body: {"value": ...}
DELETE /api/settings/{key}       -> {"key", "value"}   reset to baseline

Router prefix: /api/settings
"""
from __future__ import annotations

from fastapi import APIRouter

import settings

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("")
def get_all():
    return {"settings": settings.resolve()}


@router.get("/{key}")
def get_one(key: str):
    return {"key": key, "value": settings.get(key)}


@router.put("/{key}")
def put(key: str, body: dict):
    value = settings.set(key, body.get("value"))
    return {"key": key, "value": value}


@router.delete("/{key}")
def delete(key: str):
    value = settings.reset(key)
    return {"key": key, "value": value}
