"""Tests for backend/asin_sources.py — resolve(), ResolvedAsinSet, validation."""
from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import dataclass

import pytest

from backend import asin_sources


# Mock AsinDataAccess implementation for testing
@dataclass
class FakeAsinAccess:
    """A duck-typed AsinDataAccess for testing."""

    connected: list = None
    uploaded: list = None
    uploads: list = None
    upload_asins: dict = None

    def __post_init__(self):
        if self.connected is None:
            self.connected = []
        if self.uploaded is None:
            self.uploaded = []
        if self.uploads is None:
            self.uploads = []
        if self.upload_asins is None:
            self.upload_asins = {}

    def get_connected_asins(self):
        return self.connected

    def get_uploaded_asins(self):
        return self.uploaded

    def get_uploads(self):
        return self.uploads

    def get_upload_asin_rows(self, upload_id):
        return self.upload_asins.get(upload_id, [])


# ---------------------------------------------------------------------------
# ASIN validation tests
# ---------------------------------------------------------------------------
def test_is_valid_asin_accepts_correct_format():
    """Valid ASIN is B + 9 alphanumerics."""
    assert asin_sources.is_valid_asin("B012345678") is True
    assert asin_sources.is_valid_asin("B123ABCDEF") is True


def test_is_valid_asin_rejects_wrong_format():
    """Invalid ASINs rejected."""
    assert asin_sources.is_valid_asin("A012345678") is False  # starts with A
    assert asin_sources.is_valid_asin("B01234567") is False   # too short (8 chars)
    assert asin_sources.is_valid_asin("B0123456789") is False  # too long (10 chars)
    assert asin_sources.is_valid_asin("") is False
    assert asin_sources.is_valid_asin(None) is False
    assert asin_sources.is_valid_asin("INVALID") is False


def test_split_asin_tokens_splits_on_whitespace_and_commas():
    """split_asin_tokens tokenizes like keepa.py's _split_asins."""
    tokens = asin_sources.split_asin_tokens("B001, B002  B003")
    assert tokens == ["B001", "B002", "B003"]


def test_split_asin_tokens_uppercases():
    """split_asin_tokens upper-cases everything."""
    tokens = asin_sources.split_asin_tokens("b001, b002")
    assert tokens == ["B001", "B002"]


def test_split_asin_tokens_strips_whitespace():
    """split_asin_tokens strips surrounding whitespace."""
    tokens = asin_sources.split_asin_tokens("  B001  ,  B002  ")
    assert tokens == ["B001", "B002"]


def test_split_asin_tokens_empty_input_returns_empty():
    """Empty input returns empty list (unlike keepa._split_asins, no raise)."""
    assert asin_sources.split_asin_tokens("") == []
    assert asin_sources.split_asin_tokens("   ") == []


# ---------------------------------------------------------------------------
# ResolvedAsinSet tests
# ---------------------------------------------------------------------------
def test_resolved_asin_set_to_dict_roundtrips():
    """to_dict() serializes all fields correctly."""
    result = asin_sources.ResolvedAsinSet(
        source="test_source",
        resolved_at="2026-08-20T10:00:00Z",
        count=2,
        asins=["B001", "B002"],
        invalid=[{"value": "bad", "reason": "wrong format"}],
        duplicates=[{"value": "B003", "count": 2}],
        provenance={"B001": {"list_name": "my_list"}},
        stale=True,
        stale_reason="newer upload pending",
    )
    d = result.to_dict()
    assert d["source"] == "test_source"
    assert d["count"] == 2
    assert d["asins"] == ["B001", "B002"]
    assert len(d["invalid"]) == 1
    assert d["stale"] is True


# ---------------------------------------------------------------------------
# Connected source tests
# ---------------------------------------------------------------------------
def test_resolve_connected_returns_valid_asins():
    """resolve('connected') returns connected ASIN rows."""
    access = FakeAsinAccess(connected=[
        {"asin": "B000000001", "list_name": "keepa", "ingested_at": "2026-08-20T10:00:00Z"},
        {"asin": "B000000002", "list_name": "keepa", "ingested_at": "2026-08-20T10:00:00Z"},
    ])

    result = asin_sources.resolve("connected", access)

    assert result.source == "connected"
    assert result.count == 2
    assert set(result.asins) == {"B000000001", "B000000002"}
    assert result.stale is False


def test_resolve_connected_empty_raises():
    """resolve('connected') with no connected ASINs raises AsinSourceError."""
    access = FakeAsinAccess(connected=[])

    with pytest.raises(asin_sources.AsinSourceError) as exc_info:
        asin_sources.resolve("connected", access)

    assert "unavailable or empty" in str(exc_info.value)
    assert "connect" in str(exc_info.value).lower()


def test_resolve_connected_reports_invalid_asins():
    """connected source reports invalid ASIN values."""
    access = FakeAsinAccess(connected=[
        {"asin": "B000000001", "list_name": "keepa", "ingested_at": "2026-08-20T10:00:00Z"},
        {"asin": "INVALID", "list_name": "keepa", "ingested_at": "2026-08-20T10:00:00Z"},
        {"asin": "", "list_name": "keepa", "ingested_at": "2026-08-20T10:00:00Z"},
    ])

    result = asin_sources.resolve("connected", access)

    assert len(result.invalid) == 2
    assert any(inv["value"] == "INVALID" for inv in result.invalid)
    assert any(inv["value"] == "" for inv in result.invalid)
    assert result.count == 1  # only valid count


def test_resolve_connected_reports_duplicates():
    """connected source reports duplicate ASINs."""
    access = FakeAsinAccess(connected=[
        {"asin": "B000000001", "list_name": "keepa", "ingested_at": "2026-08-20T10:00:00Z"},
        {"asin": "B000000001", "list_name": "keepa", "ingested_at": "2026-08-20T10:00:00Z"},
        {"asin": "B000000002", "list_name": "keepa", "ingested_at": "2026-08-20T10:00:00Z"},
        {"asin": "B000000002", "list_name": "keepa", "ingested_at": "2026-08-20T10:00:00Z"},
        {"asin": "B000000002", "list_name": "keepa", "ingested_at": "2026-08-20T10:00:00Z"},
    ])

    result = asin_sources.resolve("connected", access)

    assert len(result.duplicates) == 2
    dups = {d["value"]: d["count"] for d in result.duplicates}
    assert dups["B000000001"] == 2
    assert dups["B000000002"] == 3


def test_resolve_connected_provenance_per_asin():
    """connected source includes provenance (list_name, ingested_at) per ASIN."""
    access = FakeAsinAccess(connected=[
        {"asin": "B000000001", "list_name": "keepa_list_1", "ingested_at": "2026-08-20T10:00:00Z"},
        {"asin": "B000000002", "list_name": "keepa_list_2", "ingested_at": "2026-08-21T10:00:00Z"},
    ])

    result = asin_sources.resolve("connected", access)

    assert result.provenance["B000000001"]["list_name"] == "keepa_list_1"
    assert result.provenance["B000000002"]["list_name"] == "keepa_list_2"


# ---------------------------------------------------------------------------
# Uploaded source tests
# ---------------------------------------------------------------------------
def test_resolve_uploaded_returns_valid_asins():
    """resolve('uploaded') returns ASIN list file rows."""
    access = FakeAsinAccess(uploaded=[
        {"asin": "B000000101", "upload_id": "upload-1", "row_number": 1, "ingested_at": "2026-08-20T10:00:00Z"},
        {"asin": "B000000102", "upload_id": "upload-1", "row_number": 2, "ingested_at": "2026-08-20T10:00:00Z"},
    ])

    result = asin_sources.resolve("uploaded", access)

    assert result.source == "uploaded"
    assert result.count == 2
    assert set(result.asins) == {"B000000101", "B000000102"}


def test_resolve_uploaded_empty_raises():
    """resolve('uploaded') with no uploaded ASIN list raises."""
    access = FakeAsinAccess(uploaded=[])

    with pytest.raises(asin_sources.AsinSourceError) as exc_info:
        asin_sources.resolve("uploaded", access)

    assert "No uploaded ASIN list" in str(exc_info.value)


def test_resolve_uploaded_reports_invalid_asins():
    """uploaded source reports invalid ASIN values and still returns valid count."""
    access = FakeAsinAccess(uploaded=[
        {"asin": "B000000101", "upload_id": "upload-1", "row_number": 1, "ingested_at": "2026-08-20T10:00:00Z"},
        {"asin": "INVALID", "upload_id": "upload-1", "row_number": 2, "ingested_at": "2026-08-20T10:00:00Z"},
    ])

    result = asin_sources.resolve("uploaded", access)

    assert result.count == 1
    assert len(result.invalid) == 1


# ---------------------------------------------------------------------------
# Recommended source tests
# ---------------------------------------------------------------------------
def test_resolve_recommended_uses_newest_completed_and_validated():
    """resolve('recommended') uses the newest upload that is completed AND validated."""
    now = "2026-08-20T10:00:00Z"
    older = "2026-08-19T10:00:00Z"

    access = FakeAsinAccess(
        uploads=[
            # Newest but not validated
            {"upload_id": "u1", "filename": "newest.csv", "status": "done", "validated": False, "created_at": now},
            # Newest and validated
            {"upload_id": "u2", "filename": "valid.csv", "status": "done", "validated": True, "created_at": older},
            # Older and validated
            {"upload_id": "u3", "filename": "old.csv", "status": "done", "validated": True, "created_at": "2026-08-18T10:00:00Z"},
        ],
        upload_asins={
            "u2": [{"asin": "B000000201", "row_number": 1, "ingested_at": now}],
        },
    )

    result = asin_sources.resolve("recommended", access)

    # Should use u2 (newest that qualifies), and mark stale since u1 is newer but doesn't qualify
    assert result.source == "recommended"
    assert result.stale is True
    assert "newest upload" in result.stale_reason.lower()
    assert "does not qualify" in result.stale_reason.lower()


def test_resolve_recommended_not_stale_if_newest_qualifies():
    """recommended is not stale if the newest upload itself qualifies."""
    now = "2026-08-20T10:00:00Z"

    access = FakeAsinAccess(
        uploads=[
            {"upload_id": "u1", "filename": "newest.csv", "status": "done", "validated": True, "created_at": now},
        ],
        upload_asins={
            "u1": [{"asin": "B000000301", "row_number": 1, "ingested_at": now}],
        },
    )

    result = asin_sources.resolve("recommended", access)

    assert result.stale is False
    assert result.stale_reason == ""


def test_resolve_recommended_no_qualifying_upload_raises():
    """If no upload is completed AND validated, raise without fallback."""
    access = FakeAsinAccess(uploads=[
        {"upload_id": "u1", "filename": "incomplete.csv", "status": "parsing", "validated": False, "created_at": "2026-08-20T10:00:00Z"},
    ])

    with pytest.raises(asin_sources.AsinSourceError) as exc_info:
        asin_sources.resolve("recommended", access)

    assert "completed and passed validation" in str(exc_info.value)
    assert "not silently substituted" in str(exc_info.value)


def test_resolve_recommended_no_uploads_raises():
    """If no product-data uploads exist, raise."""
    access = FakeAsinAccess(uploads=[])

    with pytest.raises(asin_sources.AsinSourceError) as exc_info:
        asin_sources.resolve("recommended", access)

    assert "No product-data uploads" in str(exc_info.value)


def test_resolve_recommended_no_rows_in_qualifying_upload_raises():
    """If the qualifying upload has no ASIN rows, raise."""
    access = FakeAsinAccess(
        uploads=[
            {"upload_id": "u1", "filename": "empty.csv", "status": "done", "validated": True, "created_at": "2026-08-20T10:00:00Z"},
        ],
        upload_asins={"u1": []},  # empty!
    )

    with pytest.raises(asin_sources.AsinSourceError) as exc_info:
        asin_sources.resolve("recommended", access)

    assert "contains no ASIN rows" in str(exc_info.value)


def test_resolve_recommended_stale_reason_captures_newest_status():
    """Stale reason includes newest upload's status and validated flag."""
    now = "2026-08-20T10:00:00Z"
    older = "2026-08-19T10:00:00Z"

    access = FakeAsinAccess(
        uploads=[
            {"upload_id": "u1", "filename": "incomplete.csv", "status": "parsing", "validated": False, "created_at": now},
            {"upload_id": "u2", "filename": "good.csv", "status": "done", "validated": True, "created_at": older},
        ],
        upload_asins={
            "u2": [{"asin": "B000000401", "row_number": 1, "ingested_at": older}],
        },
    )

    result = asin_sources.resolve("recommended", access)

    assert result.stale is True
    assert "parsing" in result.stale_reason
    assert "incomplete.csv" in result.stale_reason


# ---------------------------------------------------------------------------
# Unknown source tests
# ---------------------------------------------------------------------------
def test_resolve_unknown_source_raises():
    """Unknown source name raises AsinSourceError."""
    access = FakeAsinAccess()

    with pytest.raises(asin_sources.AsinSourceError) as exc_info:
        asin_sources.resolve("unknown", access)

    assert "Unknown ASIN source" in str(exc_info.value)
    assert "must be exactly one of" in str(exc_info.value)


def test_resolve_case_insensitive_source_names():
    """Source names are case-insensitive."""
    access = FakeAsinAccess(connected=[
        {"asin": "B000000501", "list_name": "test", "ingested_at": "2026-08-20T10:00:00Z"},
    ])

    # Should work with different cases
    result = asin_sources.resolve("CONNECTED", access)
    assert result.source == "connected"

    result = asin_sources.resolve("Connected", access)
    assert result.source == "connected"


# ---------------------------------------------------------------------------
# Integration: all three sources available
# ---------------------------------------------------------------------------
def test_resolve_three_sources_never_mixed():
    """Three sources never mix; each returns its own data."""
    access = FakeAsinAccess(
        connected=[{"asin": "B000001000", "list_name": "connected_source", "ingested_at": "2026-08-20T10:00:00Z"}],
        uploaded=[{"asin": "B000002000", "upload_id": "u1", "row_number": 1, "ingested_at": "2026-08-20T10:00:00Z"}],
        uploads=[
            {"upload_id": "u2", "filename": "rec.csv", "status": "done", "validated": True, "created_at": "2026-08-20T10:00:00Z"},
        ],
        upload_asins={"u2": [{"asin": "B000003000", "row_number": 1, "ingested_at": "2026-08-20T10:00:00Z"}]},
    )

    connected_result = asin_sources.resolve("connected", access)
    uploaded_result = asin_sources.resolve("uploaded", access)
    recommended_result = asin_sources.resolve("recommended", access)

    assert connected_result.asins == ["B000001000"]
    assert uploaded_result.asins == ["B000002000"]
    assert recommended_result.asins == ["B000003000"]

    # No mixing
    assert "B000002000" not in connected_result.asins
    assert "B000001000" not in uploaded_result.asins
    assert "B000001000" not in recommended_result.asins
