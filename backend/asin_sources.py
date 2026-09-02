"""Conductor — ASIN source resolution: connected / uploaded / recommended.

Exactly three explicitly selectable ASIN sources feed the Product Registry
and the Keepa/product-pipeline surfaces. They are never mixed and never
silently substituted for one another:

  - ``connected``   — ASINs already tracked via a live connection (today:
                      Keepa's cached/tracked product set — see
                      ``keepa.list_keepa_products``; no live Keepa API call
                      is made here, only a read of what's already cached).
  - ``uploaded``     — the most recently uploaded *ASIN list* file.
  - ``recommended``  — generated from the newest product-data upload that is
                      BOTH completed (parsing finished) AND passed
                      validation. If the true newest upload does not
                      qualify, an older qualifying upload is used, but this
                      is always surfaced via ``ResolvedAsinSet.stale`` /
                      ``stale_reason`` — never silently hidden.

If the requested source is unknown, unavailable, or empty, ``resolve()``
raises ``AsinSourceError`` — callers never fall back to a different source
on your behalf.

ASIN validation convention: this reuses the ASIN shape and tokenization
rules already established in ``backend/keepa.py`` rather than inventing a
second one:

  - shape: ``keepa.py``'s ``keepa_ai_query`` extracts ASINs from free text
    with ``re.findall(r"\\bB[0-9A-Z]{9}\\b", prompt)`` — the only ASIN-shape
    regex that existed in the codebase before this file. ``ASIN_RE`` below
    is that same pattern, anchored for whole-token validation.
  - tokenizing free-form text: ``keepa.py``'s ``_split_asins`` splits on
    ``[,\\s]+``, strips, and upper-cases each token. ``split_asin_tokens``
    below does the same (it does not also raise on empty/oversized input
    the way ``_split_asins`` does — HTTPException is a FastAPI-layer
    concern; this module stays framework-agnostic so it's mockable).

Note: as of this session, ``backend/keepa.py`` has no *format* validator at
all beyond that free-text extraction regex — ``_split_asins`` only
tokenizes and enforces a count limit, it never checks ASIN shape. So there
was no existing ASIN format validator to import, only a convention (the
regex shape + tokenization rules) to reuse. ``is_valid_asin`` below is the
first real validator, built from that convention rather than a new one.

Data access is injected (``AsinDataAccess``) so this module never talks to
the Keepa API, Supabase, or SQLite directly — callers (``productpipeline.py``
today) wire a concrete implementation; tests can inject a fake. No network
call happens anywhere in this file.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol, runtime_checkable

# Same ASIN shape as backend/keepa.py's `keepa_ai_query` extraction regex
# (`\bB[0-9A-Z]{9}\b`), anchored here for whole-token validation.
ASIN_RE = re.compile(r"^B[0-9A-Z]{9}$")

# The exactly-three selectable sources. Order matters only for display.
SOURCES: tuple[str, ...] = ("connected", "uploaded", "recommended")


class AsinSourceError(Exception):
    """The requested source is unknown, unavailable, or empty — or (for
    ``recommended``) no upload qualifies at all. Framework-agnostic on
    purpose: FastAPI callers translate this into an HTTPException (400 for
    an unknown/empty source, 409 for "nothing to recommend from" — the
    caller's call, not this module's)."""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def split_asin_tokens(raw: str) -> list[str]:
    """Tokenize free-form ASIN text the same way ``keepa.py``'s
    ``_split_asins`` does: split on commas/whitespace, strip, upper-case.
    Unlike ``_split_asins`` this never raises — an empty result is just an
    empty list, and callers decide what that means for their source."""
    return [t.strip().upper() for t in re.split(r"[,\s]+", raw or "") if t.strip()]


def is_valid_asin(value: object) -> bool:
    """True iff ``value`` matches the ASIN shape already used in
    ``keepa.py`` (``B`` + 9 alphanumerics, upper-cased)."""
    if value is None:
        return False
    return bool(ASIN_RE.match(str(value).strip().upper()))


@dataclass
class ResolvedAsinSet:
    """The result of resolving one ASIN source."""

    source: str
    resolved_at: str
    count: int
    asins: list[str] = field(default_factory=list)
    invalid: list[dict] = field(default_factory=list)      # [{"value","reason"}]
    duplicates: list[dict] = field(default_factory=list)   # [{"value","count"}]
    provenance: dict[str, dict] = field(default_factory=dict)  # asin -> provenance dict
    stale: bool = False
    stale_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "resolved_at": self.resolved_at,
            "count": self.count,
            "asins": self.asins,
            "invalid": self.invalid,
            "duplicates": self.duplicates,
            "provenance": self.provenance,
            "stale": self.stale,
            "stale_reason": self.stale_reason,
        }


@runtime_checkable
class AsinDataAccess(Protocol):
    """Injectable data-access boundary. Implement this (or just duck-type
    it — it's a ``Protocol``, not a base class) against real storage for
    production use, or against an in-memory fake for tests. No method here
    may perform a live Keepa/Supabase call."""

    def get_connected_asins(self) -> list[dict]:
        """Rows for the *connected* ASIN list:
        ``[{"asin": "...", "list_name": "...", "ingested_at": "..."}, ...]``
        or ``[]`` if nothing is connected."""
        ...

    def get_uploaded_asins(self) -> list[dict]:
        """Rows from the most recently uploaded *ASIN list* file:
        ``[{"asin": "...", "upload_id": "...", "row_number": N,
        "ingested_at": "..."}, ...]`` or ``[]`` if no ASIN list has ever
        been uploaded."""
        ...

    def get_uploads(self) -> list[dict]:
        """Every product-data upload, in any order (``resolve`` sorts by
        ``created_at`` itself), as ``[{"upload_id", "filename", "status",
        "validated", "created_at", ...}, ...]``. ``status`` should follow
        the existing ``files.status`` vocabulary (``uploading | ready |
        parsing | done | error`` — see ``storage.py``); ``validated`` is a
        bool that is only ``True`` once a validation pass has actually run
        and passed."""
        ...

    def get_upload_asin_rows(self, upload_id: str) -> list[dict]:
        """Parsed ASIN rows for one upload:
        ``[{"asin": "...", "row_number": N, "ingested_at": "..."}, ...]``."""
        ...


def _build(source: str, rows: list[dict]) -> ResolvedAsinSet:
    """Shared validation/dedupe/provenance pass for connected & uploaded
    sources (and for the rows of the chosen upload under ``recommended``)."""
    invalid: list[dict] = []
    occurrences: dict[str, int] = {}
    provenance: dict[str, dict] = {}
    ordered_valid: list[str] = []

    for row in rows:
        raw = row.get("asin")
        token = str(raw).strip().upper() if raw is not None else ""
        if not token:
            invalid.append({"value": raw, "reason": "empty ASIN value"})
            continue
        if not is_valid_asin(token):
            invalid.append({"value": raw, "reason": f"does not match ASIN shape {ASIN_RE.pattern!r}"})
            continue
        occurrences[token] = occurrences.get(token, 0) + 1
        if token not in provenance:
            provenance[token] = {
                "list_name": row.get("list_name"),
                "upload_id": row.get("upload_id"),
                "row_number": row.get("row_number"),
                "ingested_at": row.get("ingested_at"),
            }
        ordered_valid.append(token)

    duplicates = [{"value": a, "count": c} for a, c in occurrences.items() if c > 1]
    deduped = list(dict.fromkeys(ordered_valid))
    return ResolvedAsinSet(
        source=source,
        resolved_at=now_iso(),
        count=len(deduped),
        asins=deduped,
        invalid=invalid,
        duplicates=duplicates,
        provenance=provenance,
    )


def _sorted_newest_first(uploads: list[dict]) -> list[dict]:
    return sorted(uploads, key=lambda u: str(u.get("created_at") or ""), reverse=True)


def resolve(source: str, access: AsinDataAccess) -> ResolvedAsinSet:
    """Resolve one of the three explicit ASIN sources. Raises
    ``AsinSourceError`` rather than ever falling back to a different
    source or to stale data without saying so."""
    key = (source or "").strip().lower()
    if key not in SOURCES:
        raise AsinSourceError(
            f"Unknown ASIN source {source!r} — must be exactly one of {', '.join(SOURCES)}."
        )

    if key == "connected":
        rows = access.get_connected_asins()
        if not rows:
            raise AsinSourceError(
                "The connected ASIN source is unavailable or empty. Connect a source "
                "(e.g. track products via Keepa) before selecting it — 'uploaded' or "
                "'recommended' are not used as a silent fallback."
            )
        return _build(key, rows)

    if key == "uploaded":
        rows = access.get_uploaded_asins()
        if not rows:
            raise AsinSourceError(
                "No uploaded ASIN list is available. Upload an ASIN list before "
                "selecting this source — 'connected' or 'recommended' are not used "
                "as a silent fallback."
            )
        return _build(key, rows)

    # key == "recommended"
    uploads = access.get_uploads()
    if not uploads:
        raise AsinSourceError(
            "No product-data uploads exist yet — there is nothing to recommend from."
        )
    newest_first = _sorted_newest_first(uploads)
    qualified = [u for u in newest_first if u.get("status") == "done" and u.get("validated")]
    if not qualified:
        raise AsinSourceError(
            "No product-data upload is both completed and passed validation — "
            "nothing qualifies for 'recommended'. The most recent upload(s) are "
            "incomplete or invalid; this is not silently substituted with older or "
            "unvalidated data. Finish or fix an upload, or choose 'connected'/"
            "'uploaded' explicitly."
        )
    chosen = qualified[0]
    rows = access.get_upload_asin_rows(chosen["upload_id"])
    if not rows:
        raise AsinSourceError(
            f"Upload {chosen['upload_id']!r} is completed and passed validation but "
            "contains no ASIN rows."
        )
    result = _build(key, rows)

    truly_newest = newest_first[0]
    if truly_newest.get("upload_id") != chosen.get("upload_id"):
        result.stale = True
        result.stale_reason = (
            f"Newest upload {truly_newest.get('filename') or truly_newest.get('upload_id')!r} "
            f"(status={truly_newest.get('status')!r}, validated={bool(truly_newest.get('validated'))}) "
            "does not qualify (must be completed AND passed validation), so 'recommended' is "
            f"using the newest upload that does qualify: "
            f"{chosen.get('filename') or chosen.get('upload_id')!r} "
            f"(created_at={chosen.get('created_at')!r}). Not a silent fallback — surfaced here "
            "for the caller to decide whether to fix/re-run the newer upload instead."
        )
    return result
