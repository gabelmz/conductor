"""Attribute Audit — Keepa + AI brand & identifier verification.

Implements the "Logic" tab from the operator's Keepa → GS1 attribute-audit
spreadsheet as a first-class Conductor view. The original sheets formulas:

    logic!A1  = FILTER(keepa!A:ZZ, "ASIN" | "Brand" | ^Product Codes: (not PartNumber))
                → pulls ASIN + Brand + every product-code column into one view.
    logic!F2  = first 6 digits of every product code (the GS1 company prefix),
                deduplicated and joined with ", ".
    logic!G2  = COUNTA(prefix list) — unique prefix count per product.
    logic!I2  = UNIQUE master list of every prefix across the whole dataset.
    logic!J2  = split each row's prefixes into adjacent columns.

Here the same pipeline runs deterministically over BOTH the catalog (`products`)
and the cached Keepa store (`keepa_products`), plus three things the sheets
can't do:

  1. **GS1 check-digit validation** — flags typo'd / bogus UPC/EAN/GTIN codes.
  2. **GS1 member-org resolution** — the 3-digit GS1 prefix maps to the country /
     member organisation that issued it (a small, freely-published range table).
  3. **AI brand verification** — reconciles each 6-digit company prefix against
     the brand(s) that claim it, normalises brand spellings, flags conflicts
     (two brands on one prefix = likely listing error or counterfeit signal),
     and writes recommendations.

Two endpoints:
    POST /api/attribute-audit/audit  → deterministic audit (no AI, no persistence).
    POST /api/attribute-audit/ai     → AI verification pass (hosted provider,
                                        graceful no-key; result persisted to
                                        `attribute_audit_runs`).

Router prefix: /api/attribute-audit
"""
from __future__ import annotations

import json
import re

from fastapi import APIRouter, HTTPException

import storage

router = APIRouter(prefix="/api/attribute-audit", tags=["attribute-audit"])


# ---------------------------------------------------------------------------
# schema
# ---------------------------------------------------------------------------
def init_attribute_audit_db() -> None:
    conn = storage._conn()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS attribute_audit_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,          -- 'ai'
            meta TEXT DEFAULT '{}',      -- summary JSON
            data TEXT DEFAULT '{}',      -- full result JSON
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


# ---------------------------------------------------------------------------
# GS1 member-organisation range table (3-digit prefix → issuer).
# Freely published by GS1; used only to label *where* a code was issued, not
# to resolve a company name (that is licensed GEPIR data the AI step infers
# from the brand the operator already has).
# ---------------------------------------------------------------------------
GS1_RANGES: list[tuple[int, int, str]] = [
    (0, 19, "GS1 US"), (20, 29, "Restricted distribution"), (30, 39, "GS1 US"),
    (40, 49, "Restricted distribution"), (50, 59, "GS1 US (coupons)"),
    (60, 139, "GS1 US"), (200, 299, "Restricted distribution"),
    (300, 379, "GS1 France"), (380, 380, "GS1 Bulgaria"), (383, 383, "GS1 Slovenia"),
    (385, 385, "GS1 Croatia"), (387, 387, "GS1 Bosnia & Herzegovina"),
    (389, 389, "GS1 Montenegro"), (400, 440, "GS1 Germany"), (450, 459, "GS1 Japan"),
    (460, 469, "GS1 Russia"), (470, 470, "GS1 Kyrgyzstan"), (471, 471, "GS1 Taiwan"),
    (474, 474, "GS1 Estonia"), (475, 475, "GS1 Latvia"), (476, 476, "GS1 Azerbaijan"),
    (477, 477, "GS1 Lithuania"), (478, 478, "GS1 Uzbekistan"), (479, 479, "GS1 Sri Lanka"),
    (480, 480, "GS1 Philippines"), (481, 481, "GS1 Belarus"), (482, 482, "GS1 Ukraine"),
    (484, 484, "GS1 Moldova"), (485, 485, "GS1 Armenia"), (486, 486, "GS1 Georgia"),
    (487, 487, "GS1 Kazakhstan"), (488, 488, "GS1 Tajikistan"), (489, 489, "GS1 Hong Kong"),
    (490, 499, "GS1 Japan"), (500, 509, "GS1 UK"), (520, 521, "GS1 Greece"),
    (528, 528, "GS1 Lebanon"), (529, 529, "GS1 Cyprus"), (530, 530, "GS1 Albania"),
    (531, 531, "GS1 North Macedonia"), (535, 535, "GS1 Malta"), (539, 539, "GS1 Ireland"),
    (540, 549, "GS1 Belgium & Luxembourg"), (560, 560, "GS1 Portugal"),
    (569, 569, "GS1 Iceland"), (570, 579, "GS1 Denmark"), (590, 590, "GS1 Poland"),
    (594, 594, "GS1 Romania"), (599, 599, "GS1 Hungary"), (600, 601, "GS1 South Africa"),
    (603, 603, "GS1 Ghana"), (604, 604, "GS1 Senegal"), (608, 608, "GS1 Bahrain"),
    (609, 609, "GS1 Mauritius"), (611, 611, "GS1 Morocco"), (613, 613, "GS1 Algeria"),
    (615, 615, "GS1 Nigeria"), (616, 616, "GS1 Kenya"), (618, 618, "GS1 Ivory Coast"),
    (619, 619, "GS1 Tunisia"), (620, 620, "GS1 Tanzania"), (621, 621, "GS1 Syria"),
    (622, 622, "GS1 Egypt"), (623, 623, "GS1 Brunei"), (624, 624, "GS1 Libya"),
    (625, 625, "GS1 Jordan"), (626, 626, "GS1 Iran"), (627, 627, "GS1 Kuwait"),
    (628, 628, "GS1 Saudi Arabia"), (629, 629, "GS1 United Arab Emirates"),
    (640, 649, "GS1 Finland"), (690, 699, "GS1 China"), (700, 709, "GS1 Norway"),
    (729, 729, "GS1 Israel"), (730, 739, "GS1 Sweden"), (740, 740, "GS1 Guatemala"),
    (741, 741, "GS1 El Salvador"), (742, 742, "GS1 Honduras"), (743, 743, "GS1 Nicaragua"),
    (744, 744, "GS1 Costa Rica"), (745, 745, "GS1 Panama"),
    (746, 746, "GS1 Dominican Republic"), (750, 750, "GS1 Mexico"),
    (754, 755, "GS1 Canada"), (759, 759, "GS1 Venezuela"),
    (760, 769, "GS1 Switzerland & Liechtenstein"), (770, 771, "GS1 Colombia"),
    (773, 773, "GS1 Uruguay"), (775, 775, "GS1 Peru"), (777, 777, "GS1 Bolivia"),
    (778, 779, "GS1 Argentina"), (780, 780, "GS1 Chile"), (784, 784, "GS1 Paraguay"),
    (786, 786, "GS1 Ecuador"), (789, 790, "GS1 Brazil"), (800, 839, "GS1 Italy"),
    (840, 849, "GS1 Spain"), (850, 850, "GS1 Cuba"), (858, 858, "GS1 Slovakia"),
    (859, 859, "GS1 Czech Republic"), (860, 860, "GS1 Serbia"), (865, 865, "GS1 Mongolia"),
    (867, 867, "GS1 North Korea"), (868, 869, "GS1 Turkey"), (870, 879, "GS1 Netherlands"),
    (880, 880, "GS1 South Korea"), (884, 884, "GS1 Cambodia"), (885, 885, "GS1 Thailand"),
    (888, 888, "GS1 Singapore"), (890, 890, "GS1 India"), (893, 893, "GS1 Vietnam"),
    (896, 896, "GS1 Pakistan"), (899, 899, "GS1 Indonesia"), (900, 919, "GS1 Austria"),
    (930, 939, "GS1 Australia"), (940, 949, "GS1 New Zealand"), (950, 950, "GS1 Global Office"),
    (951, 951, "GS1 Global Office (EPC)"), (952, 952, "GS1 Global Office (demo)"),
    (955, 955, "GS1 Malaysia"), (958, 958, "GS1 Macau"),
]


def _gs1_org(prefix3: str) -> str:
    """3-digit GS1 prefix → issuing member organisation (empty if unknown)."""
    try:
        n = int(prefix3)
    except (TypeError, ValueError):
        return ""
    if 977 <= n <= 979:
        return "ISBN/ISSN (books & serials)"
    if 980 <= n <= 984:
        return "GS1 refund/coupon"
    if 985 <= n <= 999:
        return "GS1 coupon"
    for lo, hi, org in GS1_RANGES:
        if lo <= n <= hi:
            return org
    return ""


# ---------------------------------------------------------------------------
# barcode / GTIN helpers
# ---------------------------------------------------------------------------
def _digits(raw) -> str:
    return re.sub(r"[^0-9]", "", str(raw or ""))


def _check_digit(code_without_check: str) -> int:
    """GS1 mod-10 check digit for the data portion (no check digit)."""
    total = 0
    for i, ch in enumerate(reversed(code_without_check)):
        total += int(ch) * (3 if i % 2 == 0 else 1)
    return (10 - (total % 10)) % 10


def _isbn10_check(code: str) -> bool:
    """Validate an ISBN-10 (last char may be X). Returns None when non-numeric."""
    body, check = code[:9], code[9:].upper()
    if not body.isdigit():
        return False
    weights = range(10, 1, -1)
    total = sum(int(d) * w for d, w in zip(body, weights))
    if check == "X":
        total += 10
    elif check.isdigit():
        total += int(check)
    else:
        return False
    return total % 11 == 0


def analyse_code(raw) -> dict:
    """Classify + validate one product code and extract its GS1 prefixes.

    `prefix6` is the 6-digit legacy GS1 company prefix (the sheets' F2). For a
    13-digit EAN-13 that is a zero-padded US UPC-A we skip the leading zero so
    the same physical code clusters under one prefix whether it arrived as a
    12- or 13-digit string (a deliberate improvement over the naive LEFT(…,6)).
    """
    digits = _digits(raw)
    out: dict = {"raw": (str(raw or "")).strip(), "code": digits, "type": "empty",
                 "valid": False, "check_digit": None, "prefix6": "", "gs1_3": "",
                 "country": "", "note": ""}
    n = len(digits)
    if n == 0:
        out["note"] = "no digits"
        return out

    if n == 14:  # GTIN-14
        out.update(type="GTIN-14", valid=int(digits[-1]) == _check_digit(digits[:13]),
                   check_digit=digits[-1], prefix6=digits[:6], gs1_3=digits[:3],
                   note="GTIN-14 (prefix includes packaging indicator)")
    elif n == 13:  # EAN-13 (or zero-padded UPC-A, or ISBN-13)
        valid = int(digits[-1]) == _check_digit(digits[:12])
        if digits.startswith("978") or digits.startswith("979"):
            out.update(type="ISBN-13", valid=valid, check_digit=digits[-1],
                       prefix6=digits[:6], gs1_3=digits[:3])
        elif digits.startswith("0"):  # zero-padded UPC-A from GS1 US
            out.update(type="EAN-13 (padded UPC-A)", valid=valid, check_digit=digits[-1],
                       prefix6=digits[1:7], gs1_3=digits[1:4])
        else:
            out.update(type="EAN-13", valid=valid, check_digit=digits[-1],
                       prefix6=digits[:6], gs1_3=digits[:3])
    elif n == 12:  # UPC-A
        out.update(type="UPC-A", valid=int(digits[-1]) == _check_digit(digits[:11]),
                   check_digit=digits[-1], prefix6=digits[:6], gs1_3=digits[:3])
    elif n == 11:  # UPC-A missing its check digit — compute + append
        cd = _check_digit(digits)
        out.update(type="UPC-A", valid=True, check_digit=str(cd), prefix6=digits[:6],
                   gs1_3=digits[:3], note=f"check digit {cd} computed")
    elif n == 8:  # EAN-8
        out.update(type="EAN-8", valid=int(digits[-1]) == _check_digit(digits[:7]),
                   check_digit=digits[-1], prefix6=digits[:6], gs1_3=digits[:3],
                   note="EAN-8 (compressed — no 6-digit company prefix)")
    elif n == 10:  # ISBN-10
        out.update(type="ISBN-10", valid=_isbn10_check(digits), check_digit=digits[-1],
                   prefix6=digits[:6], gs1_3="", note="ISBN-10 (no GS1 company prefix)")
    else:
        out.update(type="unknown", valid=False, note=f"unrecognised length {n}")

    out["country"] = _gs1_org(out["gs1_3"]) if out["gs1_3"] else ""
    return out


# ---------------------------------------------------------------------------
# source extraction (catalog products + cached Keepa, merged by SKU/ASIN)
# ---------------------------------------------------------------------------
def _norm_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(key or "").lower()).strip("_")


def _norm_brand(brand: str) -> str:
    """Lossy brand key for candidate-conflict detection (order-invariant)."""
    return "".join(sorted(re.sub(r"[^a-z0-9]", "", str(brand or "").lower())))


# attribute keys that are identifiers but NOT product codes (excluded, matching
# the sheets' `<>"Product Codes: PartNumber"`).
_CODE_EXCLUDE = {"asin", "keepa_asin", "sku", "part_number", "partnumber",
                 "product_codes_partnumber", "product_codes_part_number", "model"}


def _is_code_key(nk: str) -> bool:
    if nk in _CODE_EXCLUDE:
        return False
    if "partnumber" in nk or "part_number" in nk:
        return False
    return ("upc" in nk or "ean" in nk or "gtin" in nk or "product_code" in nk
            or "product_codes" in nk)


def _coerce_codes(val) -> list[str]:
    """Normalise a raw attribute value into a list of code strings."""
    if val is None:
        return []
    if isinstance(val, (list, tuple)):
        out = []
        for item in val:
            out.extend(_coerce_codes(item))
        return out
    s = str(val).strip()
    if not s:
        return []
    parts = [p.strip() for p in re.split(r"[;|\n]", s) if p.strip()]
    return parts or [s]


def _extract_codes_from_attributes(attrs: dict) -> list[str]:
    codes: list[str] = []
    for key, val in (attrs or {}).items():
        nk = _norm_key(key)
        if not _is_code_key(nk):
            continue
        codes.extend(_coerce_codes(val))
    return codes


def _extract_codes_from_keepa(data: dict) -> list[str]:
    codes: list[str] = []
    for key in ("upcs", "eans", "gtins", "gtin", "upc", "ean"):
        val = data.get(key)
        if val is not None:
            codes.extend(_coerce_codes(val))
    return codes


def _brand(attrs: dict) -> str:
    for k in ("brand", "Brand", "BRAND", "manufacturer"):
        v = (attrs or {}).get(k)
        if v:
            return str(v).strip()
    return ""


def _merged_sources() -> list[dict]:
    """Merge catalog + cached Keepa into one entry per SKU/ASIN (no double count)."""
    merged: dict[str, dict] = {}

    for p in storage.list_products(limit=5000):
        sku = (p.get("sku") or "").strip()
        if not sku:
            continue
        attrs = p.get("attributes") or {}
        entry = merged.setdefault(sku.lower(), {
            "sku": sku, "name": p.get("name") or "", "brand": _brand(attrs),
            "codes": [], "sources": [],
        })
        if entry["name"] == "" and p.get("name"):
            entry["name"] = p["name"]
        if entry["brand"] == "":
            entry["brand"] = _brand(attrs)
        entry["codes"].extend(_extract_codes_from_attributes(attrs))
        if "catalog" not in entry["sources"]:
            entry["sources"].append("catalog")

    try:
        import keepa
        for kp in keepa.list_keepa_products(limit=5000):
            d = kp.get("data") or {}
            sku = (d.get("asin") or kp.get("asin") or "").strip()
            if not sku:
                continue
            brand = d.get("brand") or d.get("manufacturer") or ""
            entry = merged.setdefault(sku.lower(), {
                "sku": sku, "name": d.get("title") or "", "brand": brand,
                "codes": [], "sources": [],
            })
            if entry["name"] == "" and d.get("title"):
                entry["name"] = d["title"]
            if entry["brand"] == "" and brand:
                entry["brand"] = brand
            entry["codes"].extend(_extract_codes_from_keepa(d))
            if "keepa" not in entry["sources"]:
                entry["sources"].append("keepa")
    except Exception:
        pass  # keepa module missing/errored → catalog-only audit still works

    return list(merged.values())


# ---------------------------------------------------------------------------
# deterministic audit
# ---------------------------------------------------------------------------
def run_audit() -> dict:
    entries = _merged_sources()
    rows: list[dict] = []
    prefix_map: dict[str, dict] = {}

    n_with_codes = n_valid = n_invalid = n_conflict = n_missing_brand = n_missing_codes = 0
    n_codes = 0

    for e in entries:
        seen_codes: list[str] = []
        code_details: list[dict] = []
        prefixes: list[str] = []
        flags: list[str] = []
        for raw in e["codes"]:
            if raw in seen_codes:
                continue
            seen_codes.append(raw)
            detail = analyse_code(raw)
            n_codes += 1
            if detail["valid"]:
                n_valid += 1
            else:
                n_invalid += 1
                if "invalid_barcode" not in flags:
                    flags.append("invalid_barcode")
            if detail["prefix6"] and detail["prefix6"] not in prefixes:
                prefixes.append(detail["prefix6"])
            code_details.append(detail)

        brand = e["brand"]
        if prefixes and not brand:
            flags.append("missing_brand")
        if brand and not prefixes:
            flags.append("missing_codes")
        if prefixes:
            n_with_codes += 1
        if "missing_brand" in flags:
            n_missing_brand += 1
        if "missing_codes" in flags:
            n_missing_codes += 1

        # fold into the prefix master map
        for pfx in prefixes:
            agg = prefix_map.setdefault(pfx, {
                "prefix": pfx, "gs1_3": "", "country": "", "products": 0,
                "codes": 0, "valid": 0, "invalid": 0, "brands": [], "_keys": [],
            })
            agg["products"] += 1
            nb = _norm_brand(brand)
            if brand and nb and nb not in agg["_keys"]:
                agg["_keys"].append(nb)
                agg["brands"].append(brand)
            if not agg["gs1_3"]:
                for d in code_details:
                    if d["prefix6"] == pfx and d["gs1_3"]:
                        agg["gs1_3"] = d["gs1_3"]
                        agg["country"] = d["country"]
                        break

        rows.append({
            "sku": e["sku"], "name": e["name"], "brand": brand,
            "sources": e["sources"], "codes": seen_codes, "code_details": code_details,
            "prefixes": prefixes, "prefix_count": len(prefixes), "flags": flags,
        })

    # finalise prefix master list (logic!I2)
    prefixes_out: list[dict] = []
    for pfx, agg in prefix_map.items():
        for row in rows:
            if pfx not in row["prefixes"]:
                continue
            for d in row["code_details"]:
                if d["prefix6"] != pfx:
                    continue
                agg["codes"] += 1
                if d["valid"]:
                    agg["valid"] += 1
                else:
                    agg["invalid"] += 1
        brand_labels = [b for b in agg["brands"]]
        conflict = len(brand_labels) > 1
        if conflict:
            n_conflict += 1
        prefixes_out.append({
            "prefix": pfx, "gs1_3": agg["gs1_3"], "country": agg["country"],
            "product_count": agg["products"], "code_count": agg["codes"],
            "valid": agg["valid"], "invalid": agg["invalid"],
            "brands": brand_labels, "brand_count": len(brand_labels),
            "conflict": conflict,
        })
    prefixes_out.sort(key=lambda p: (-p["product_count"], p["prefix"]))

    rows.sort(key=lambda r: (-r["prefix_count"], r["sku"].lower()))

    brands = sorted({r["brand"] for r in rows if r["brand"]}, key=str.lower)

    return {
        "summary": {
            "products": len(entries), "with_codes": n_with_codes,
            "codes": n_codes, "valid": n_valid, "invalid": n_invalid,
            "prefixes": len(prefixes_out), "conflicts": n_conflict,
            "missing_brand": n_missing_brand, "missing_codes": n_missing_codes,
            "brands": len(brands),
        },
        "brands": brands,
        "rows": rows,
        "prefixes": prefixes_out,
    }


# ---------------------------------------------------------------------------
# AI brand-verification pass (hosted provider; graceful no-key)
# ---------------------------------------------------------------------------
def _strip_code_fences(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    return text.strip()


def _extract_json(text: str):
    text = _strip_code_fences(text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except Exception:
        return None


def _provider_ready():
    try:
        from ai_ingest import _provider_ready as ready
        return ready()
    except Exception:
        return None


AI_SYSTEM = """You are a brand-verification analyst inside Conductor, a desktop app for an
e-commerce operator selling on Amazon/Walmart/TikTok. You audit product identifiers.

A "GS1 company prefix" is the first 6 digits of a UPC/EAN/GTIN. It identifies the
company that owns a block of barcodes. When the brand listed on a product does not
match the brand(s) that own its prefix, that is a red flag: a listing error, a
reseller listing under the wrong brand, or a possible counterfeit.

You are given a JSON object with:
  - "prefixes": a list of {prefix, country (GS1 member org), brands[], product_count, conflict}
  - "brands": the distinct brand strings found in the catalog
  - "summary": the deterministic audit counts

Respond with STRICT JSON ONLY — a single object:
{
  "summary": "<2-3 sentence overall assessment of brand/prefix hygiene>",
  "verdicts": [
    {"prefix": "<6-digit prefix>", "country": "<member org or ''>",
     "brands": ["<as listed>"],
     "status": "consistent|conflict|unknown",
     "normalized_brand": "<the single canonical brand you infer, or ''>",
     "reasoning": "<1-2 sentences>"
    }
  ],
  "findings": [
    {"severity": "blocker|warning|info", "kind": "brand_conflict|invalid_barcode|missing_brand|missing_codes|suspicious",
     "message": "<specific, actionable>"}
  ],
  "recommendations": ["<short strings>"]
}

RULES:
- Only judge what the data shows; do not invent company names. For a prefix whose
  owner you cannot determine from the brands present, set status "unknown".
- Treat near-identical brand spellings (case, punctuation, "Inc/LLC/Ltd", spacing)
  as the SAME brand — set normalized_brand to the cleanest form.
- A "conflict" means two genuinely different brands share one prefix.
- Cap findings to the 15 most important; recommendations to the 10 most actionable.
- Only output the JSON object — no prose, no markdown."""


def _ai_payload(audit: dict, max_prefixes: int = 80) -> dict:
    prefixes = audit.get("prefixes") or []
    # Prioritise conflicts + highest product-count prefixes for the model.
    ordered = sorted(prefixes, key=lambda p: (not p.get("conflict"), -p.get("product_count", 0)))
    return {
        "summary": audit.get("summary") or {},
        "brands": (audit.get("brands") or [])[:200],
        "prefixes": [
            {"prefix": p["prefix"], "country": p.get("country") or "",
             "brands": p.get("brands") or [], "product_count": p.get("product_count", 0),
             "conflict": p.get("conflict", False)}
            for p in ordered[:max_prefixes]
        ],
    }


def _save_ai_run(meta: dict, data: dict) -> int:
    conn = storage._conn()
    cur = conn.execute(
        "INSERT INTO attribute_audit_runs (kind, meta, data, created_at) VALUES (?,?,?,?)",
        ("ai", json.dumps(meta), json.dumps(data), storage.now_iso()),
    )
    conn.commit()
    return cur.lastrowid


def list_ai_runs(limit: int = 10) -> list[dict]:
    rows = storage._conn().execute(
        "SELECT * FROM attribute_audit_runs ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["meta"] = json.loads(d.get("meta") or "{}")
        d["data"] = json.loads(d.get("data") or "{}")
        out.append(d)
    return out


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------
@router.get("/status")
def status():
    ready = _provider_ready()
    return {
        "ai_ready": bool(ready),
        "ai_provider": (ready[0] if ready else ""),
        "products": storage.count_products(),
        "runs": len(list_ai_runs(limit=100)),
    }


@router.post("/audit")
def audit(body: dict | None = None):
    """Run the deterministic GS1-prefix audit (no AI, no persistence)."""
    try:
        return run_audit()
    except Exception as exc:
        raise HTTPException(500, f"Audit failed: {exc}")


@router.get("/runs")
def runs(limit: int = 10):
    return {"runs": list_ai_runs(min(limit, 50))}


@router.post("/ai")
def ai_verify(body: dict | None = None):
    """Run the AI brand-verification pass over the current audit snapshot."""
    ready = _provider_ready()
    if not ready:
        return {"ai": False, "error": "No AI provider key configured — add one in Settings → AI Chat, then retry."}

    audit = run_audit()
    payload = _ai_payload(audit)
    provider, model, api_key = ready

    import providers
    messages = [
        {"role": "system", "content": AI_SYSTEM},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    try:
        text = ""
        for ev in providers.stream_provider(provider, messages, model=model, api_key=api_key):
            if ev["type"] == "text":
                text += ev["text"]
            elif ev["type"] == "error":
                raise ValueError(f"Provider error: {ev.get('code')} {ev.get('message')}")
        parsed = _extract_json(text)
        if not isinstance(parsed, dict):
            raise ValueError("AI returned unparseable output (expected a JSON object).")

        summary = str(parsed.get("summary") or "").strip()
        verdicts = parsed.get("verdicts") or []
        findings = parsed.get("findings") or []
        recommendations = parsed.get("recommendations") or []

        run_id = _save_ai_run(
            meta={"summary": summary, "prefixes": len(verdicts),
                  "findings": len(findings), "recommendations": len(recommendations)},
            data={"audit_summary": audit.get("summary") or {},
                  "ai": {"summary": summary, "verdicts": verdicts,
                         "findings": findings, "recommendations": recommendations}},
        )
        return {"ai": True, "run_id": run_id, "summary": summary, "verdicts": verdicts,
                "findings": findings, "recommendations": recommendations}
    except Exception as exc:
        return {"ai": False, "error": str(exc)}
