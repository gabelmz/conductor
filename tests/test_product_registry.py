"""Tests for backend/productpipeline.py — Product Registry lifecycle, stages, transitions."""
from __future__ import annotations

import threading
import json

import pytest
from fastapi.testclient import TestClient

import storage
from main import app
from backend import productpipeline


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    """Standard test fixture: ephemeral DB in tmp_path."""
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "conductor.db")
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    storage._local = threading.local()
    storage.init_db()
    productpipeline.init_product_pipeline_db()


def _create_registry_item(name: str, file_type: str, stage: str = None) -> int:
    """Helper to create a product registry item."""
    now = storage.now_iso()
    conn = storage._conn()
    stage = stage or productpipeline.REGISTRY_DEFAULT_STAGE
    cur = conn.execute(
        "INSERT INTO product_registry_items "
        "(item_key, name, file_type, stage, asin_source, upload_id, upload_status, raw, parsed, validation, provenance, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (f"item-{name}", name, file_type, stage, "", "", "", "{}", "{}", "{}", "{}", now, now),
    )
    conn.commit()
    return cur.lastrowid


# ---------------------------------------------------------------------------
# Registry stages and types tests
# ---------------------------------------------------------------------------
def test_registry_stages_returns_all_seven_stages():
    """All seven lifecycle stages are defined and retrievable."""
    client = TestClient(app)
    response = client.get("/api/productpipeline/registry/stages")

    assert response.status_code == 200
    data = response.json()
    stages = data["stages"]
    assert len(stages) == 7
    stage_keys = [s["key"] for s in stages]
    assert stage_keys == ["suggested", "staging", "review", "analysis", "submitted", "live", "archive"]


def test_registry_stages_include_transitions():
    """Each stage specifies its legal next stages."""
    client = TestClient(app)
    response = client.get("/api/productpipeline/registry/stages")
    stages = response.json()["stages"]

    # Find the suggested stage
    suggested = next(s for s in stages if s["key"] == "suggested")
    assert suggested["transitions"] == ["staging", "archive"]

    # Archive should be terminal
    archive = next(s for s in stages if s["key"] == "archive")
    assert archive["transitions"] == []
    assert archive["terminal"] is True


def test_registry_types_returns_all_types():
    """All registry types are defined."""
    client = TestClient(app)
    response = client.get("/api/productpipeline/registry/types")

    assert response.status_code == 200
    types = response.json()["types"]
    assert "asin_list" in types
    assert "catalog_product" in types
    assert "keepa_export" in types
    assert "suggested_content" in types
    assert "compliance_document" in types
    assert "other" in types


# ---------------------------------------------------------------------------
# Registry transitions tests
# ---------------------------------------------------------------------------
def test_registry_legal_transition_suggested_to_staging():
    """Can transition suggested -> staging."""
    client = TestClient(app)
    item_id = _create_registry_item("item1", "asin_list", "suggested")

    response = client.post(f"/api/productpipeline/registry/items/{item_id}/transition", json={"to_stage": "staging"})

    assert response.status_code == 200
    data = response.json()
    assert data["stage"] == "staging"


def test_registry_legal_transition_staging_to_review():
    """Can transition staging -> review."""
    client = TestClient(app)
    item_id = _create_registry_item("item1", "asin_list", "staging")

    response = client.post(f"/api/productpipeline/registry/items/{item_id}/transition", json={"to_stage": "review"})

    assert response.status_code == 200
    assert response.json()["stage"] == "review"


def test_registry_legal_transition_review_back_to_staging():
    """Can transition review -> staging (loop back for rework)."""
    client = TestClient(app)
    item_id = _create_registry_item("item1", "asin_list", "review")

    response = client.post(f"/api/productpipeline/registry/items/{item_id}/transition", json={"to_stage": "staging"})

    assert response.status_code == 200
    assert response.json()["stage"] == "staging"


def test_registry_legal_transition_analysis_to_submitted():
    """Can transition analysis -> submitted."""
    client = TestClient(app)
    item_id = _create_registry_item("item1", "asin_list", "analysis")

    response = client.post(f"/api/productpipeline/registry/items/{item_id}/transition", json={"to_stage": "submitted"})

    assert response.status_code == 200
    assert response.json()["stage"] == "submitted"


def test_registry_legal_transition_submitted_to_live():
    """Can transition submitted -> live."""
    client = TestClient(app)
    item_id = _create_registry_item("item1", "asin_list", "submitted")

    response = client.post(f"/api/productpipeline/registry/items/{item_id}/transition", json={"to_stage": "live"})

    assert response.status_code == 200
    assert response.json()["stage"] == "live"


def test_registry_legal_transition_live_to_archive():
    """Can transition live -> archive (retirement)."""
    client = TestClient(app)
    item_id = _create_registry_item("item1", "asin_list", "live")

    response = client.post(f"/api/productpipeline/registry/items/{item_id}/transition", json={"to_stage": "archive"})

    assert response.status_code == 200
    assert response.json()["stage"] == "archive"


def test_registry_archive_is_terminal():
    """Archive stage has no outbound transitions."""
    client = TestClient(app)
    item_id = _create_registry_item("item1", "asin_list", "archive")

    # Try to transition out of archive
    response = client.post(f"/api/productpipeline/registry/items/{item_id}/transition", json={"to_stage": "live"})

    assert response.status_code == 409
    assert "Illegal transition" in response.json()["detail"]


def test_registry_illegal_transition_returns_409_with_allowed_stages():
    """Illegal transition returns 409 and names allowed next stages."""
    client = TestClient(app)
    item_id = _create_registry_item("item1", "asin_list", "suggested")

    # Try illegal transition: suggested -> review (not allowed, only staging and archive are)
    response = client.post(f"/api/productpipeline/registry/items/{item_id}/transition", json={"to_stage": "review"})

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "Illegal transition" in detail
    assert "suggested" in detail
    assert "review" in detail
    # Should name the allowed stages
    assert "staging" in detail or "Allowed" in detail


def test_registry_same_stage_transition_returns_409():
    """Transitioning to the same stage is rejected."""
    client = TestClient(app)
    item_id = _create_registry_item("item1", "asin_list", "staging")

    response = client.post(f"/api/productpipeline/registry/items/{item_id}/transition", json={"to_stage": "staging"})

    assert response.status_code == 409
    assert "already in stage" in response.json()["detail"]


def test_registry_transition_with_note_recorded():
    """Transition note is recorded in audit trail."""
    client = TestClient(app)
    item_id = _create_registry_item("item1", "asin_list", "suggested")

    response = client.post(f"/api/productpipeline/registry/items/{item_id}/transition", json={
        "to_stage": "staging",
        "note": "Ready for prep work"
    })

    assert response.status_code == 200

    # Verify note was recorded
    conn = storage._conn()
    record = conn.execute(
        "SELECT note FROM product_registry_transitions WHERE item_id=? ORDER BY id DESC LIMIT 1",
        (item_id,)
    ).fetchone()
    assert record["note"] == "Ready for prep work"


# ---------------------------------------------------------------------------
# Registry type/stage independence tests
# ---------------------------------------------------------------------------
def test_registry_type_and_stage_independent():
    """file_type and stage are independently settable."""
    client = TestClient(app)

    # Create with one type
    item_id = _create_registry_item("item1", "asin_list", "suggested")

    # Can transition through stages regardless of type
    client.post(f"/api/productpipeline/registry/items/{item_id}/transition", json={"to_stage": "staging"})
    client.post(f"/api/productpipeline/registry/items/{item_id}/transition", json={"to_stage": "review"})

    # Type should remain unchanged
    response = client.get(f"/api/productpipeline/registry/items/{item_id}")
    assert response.status_code == 200
    assert response.json()["file_type"] == "asin_list"

    # Can also have catalog_product in staging, live, etc.
    item_id2 = _create_registry_item("item2", "catalog_product", "live")
    response = client.get(f"/api/productpipeline/registry/items/{item_id2}")
    assert response.json()["file_type"] == "catalog_product"
    assert response.json()["stage"] == "live"


def test_registry_different_types_in_different_stages():
    """Multiple items can have different types at different stages simultaneously."""
    client = TestClient(app)

    # Create three items
    id1 = _create_registry_item("asin_in_suggested", "asin_list", "suggested")
    id2 = _create_registry_item("catalog_in_live", "catalog_product", "live")
    id3 = _create_registry_item("other_in_archive", "other", "archive")

    # List all and verify
    response = client.get("/api/productpipeline/registry/items")
    assert response.status_code == 200
    items = response.json()["items"]

    types_by_stage = {(i["file_type"], i["stage"]) for i in items}
    assert ("asin_list", "suggested") in types_by_stage
    assert ("catalog_product", "live") in types_by_stage
    assert ("other", "archive") in types_by_stage


# ---------------------------------------------------------------------------
# Registry canonical record tests
# ---------------------------------------------------------------------------
def test_registry_one_canonical_record_per_item_key():
    """Only one record exists per item_key even after transitions."""
    client = TestClient(app)
    item_id = _create_registry_item("unique_item", "asin_list", "suggested")

    # Transition through several stages
    client.post(f"/api/productpipeline/registry/items/{item_id}/transition", json={"to_stage": "staging"})
    client.post(f"/api/productpipeline/registry/items/{item_id}/transition", json={"to_stage": "review"})
    client.post(f"/api/productpipeline/registry/items/{item_id}/transition", json={"to_stage": "analysis"})

    # Query count of records with this item_key
    conn = storage._conn()
    count = conn.execute(
        "SELECT COUNT(*) as cnt FROM product_registry_items WHERE item_key=?",
        ("item-unique_item",)
    ).fetchone()["cnt"]

    assert count == 1

    # Final stage should be analysis
    response = client.get(f"/api/productpipeline/registry/items/{item_id}")
    assert response.json()["stage"] == "analysis"


def test_registry_counts_by_stage():
    """List response includes counts by stage across all items."""
    client = TestClient(app)

    # Create items at different stages
    _create_registry_item("item1", "asin_list", "suggested")
    _create_registry_item("item2", "asin_list", "suggested")
    _create_registry_item("item3", "catalog_product", "staging")
    _create_registry_item("item4", "other", "archive")

    response = client.get("/api/productpipeline/registry/items")

    assert response.status_code == 200
    counts = response.json()["counts_by_stage"]
    assert counts["suggested"] == 2
    assert counts["staging"] == 1
    assert counts["archive"] == 1


def test_registry_list_filter_by_stage():
    """Can filter registry items by stage."""
    client = TestClient(app)

    _create_registry_item("item1", "asin_list", "suggested")
    _create_registry_item("item2", "catalog_product", "suggested")
    _create_registry_item("item3", "other", "staging")

    response = client.get("/api/productpipeline/registry/items?stage=suggested")

    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 2
    assert all(i["stage"] == "suggested" for i in items)


def test_registry_list_filter_by_type():
    """Can filter registry items by file_type."""
    client = TestClient(app)

    _create_registry_item("item1", "asin_list", "suggested")
    _create_registry_item("item2", "asin_list", "staging")
    _create_registry_item("item3", "catalog_product", "staging")

    response = client.get("/api/productpipeline/registry/items?file_type=asin_list")

    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 2
    assert all(i["file_type"] == "asin_list" for i in items)


def test_registry_list_filter_by_stage_and_type():
    """Can filter by both stage and type simultaneously."""
    client = TestClient(app)

    _create_registry_item("item1", "asin_list", "suggested")
    _create_registry_item("item2", "asin_list", "staging")
    _create_registry_item("item3", "catalog_product", "staging")

    response = client.get("/api/productpipeline/registry/items?stage=staging&file_type=asin_list")

    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["file_type"] == "asin_list"
    assert items[0]["stage"] == "staging"


# ---------------------------------------------------------------------------
# Registry transition history tests
# ---------------------------------------------------------------------------
def test_registry_transition_history_recorded():
    """Transition history is recorded and visible."""
    client = TestClient(app)
    item_id = _create_registry_item("item1", "asin_list", "suggested")

    # Perform a transition
    client.post(f"/api/productpipeline/registry/items/{item_id}/transition", json={
        "to_stage": "staging",
        "note": "Moving to staging"
    })

    # Check that transition was recorded
    conn = storage._conn()
    transitions = conn.execute(
        "SELECT * FROM product_registry_transitions WHERE item_id=? ORDER BY id ASC",
        (item_id,)
    ).fetchall()

    # Should have at least the manual transition
    manual_transition = next((t for t in transitions if t["to_stage"] == "staging"), None)
    assert manual_transition is not None
    assert manual_transition["note"] == "Moving to staging"
