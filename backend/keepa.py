"""Conductor — Keepa live product data source.

Pulls live Amazon product data (title, brand, manufacturer, price, sales rank,
rating, review count, images, dimensions, category nodes, EAN/UPC…) from the
Keepa product API and caches it locally so repeated lookups don't burn tokens
(Keepa refills tokens at a fixed rate and charges one token per unique product
request).

API reference — https://keepa.com/#!api

    GET https://api.keepa.com/product?key=<KEY>&domain=<DOMAIN>&asin=<ASIN1,ASIN2>

Key contract points implemented here (per Keepa's documented product object):

- `asin` requests take a comma-separated list (up to 100 per call); the response
  `products` array is returned in request order, with `null` for not-found ASINs.
- Prices are integers in the smallest currency unit (cents): $19.99 → `1999`.
- Ratings are integers scaled ×10: 4.5 stars → `45`.
- Sales rank is a plain integer (lower = better); `salesRanks` is a list of
  `[rank, categoryNodeId]` pairs — we surface the best (lowest) rank.
- `stats.current` holds the latest value of every tracked metric; `avg30/avg90/
  avg180` hold rolling averages. We keep `stats` raw and only convert the
  well-documented `current` scalars — no inference beyond that contract.

Router prefix: /api/keepa
"""
from __future__ import annotations

import json
import gzip
import os
import re
import urllib.error
import urllib.parse
import urllib.request

from fastapi import APIRouter, HTTPException

import storage

router = APIRouter(prefix="/api/keepa", tags=["keepa"])

BASE_URL = "https://api.keepa.com/product"
CONFIG_PATH = storage.DATA_DIR / "keepa.json"
DEFAULT_STATS_DAYS = 180

# Keepa domain ids → market code (documented locale table).
DOMAINS = {
    1: "US", 2: "UK", 3: "DE", 4: "FR", 5: "JP", 6: "CA",
    7: "IT", 8: "ES", 9: "IN", 10: "MX", 11: "AU",
}


# ---------------------------------------------------------------------------
# schema
# ---------------------------------------------------------------------------
def init_keepa_db() -> None:
    conn = storage._conn()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS keepa_products (
            asin TEXT NOT NULL,
            domain INTEGER NOT NULL,
            data TEXT NOT NULL,          -- parsed product JSON (title/price/rank/…)
            fetched_at TEXT NOT NULL,
            PRIMARY KEY (asin, domain)
        )
        """
    )
    conn.commit()


# ---------------------------------------------------------------------------
# config (data/keepa.json + KEEPA_API_KEY env override)
# ---------------------------------------------------------------------------
def _load_config() -> dict:
    cfg = {}
    if CONFIG_PATH.exists():
        try:
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            cfg = {}
    key = cfg.get("api_key") or os.environ.get("KEEPA_API_KEY", "")
    try:
        domain = int(cfg.get("domain") or 1)
    except (TypeError, ValueError):
        domain = 1
    if domain not in DOMAINS:
        domain = 1
    return {"api_key": str(key).strip(), "domain": domain}


def _save_config(cfg: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def get_config() -> dict:
    cfg = _load_config()
    key = cfg["api_key"]
    return {
        "has_key": bool(key),
        "key_masked": (f"****{key[-4:]}" if len(key) >= 4 else "****") if key else "",
        "domain": cfg["domain"],
        "domains": [{"id": k, "code": v} for k, v in sorted(DOMAINS.items())],
    }


# ---------------------------------------------------------------------------
# storage cache
# ---------------------------------------------------------------------------
def save_keepa_product(asin: str, domain: int, data: dict) -> None:
    conn = storage._conn()
    conn.execute(
        "INSERT INTO keepa_products (asin, domain, data, fetched_at) VALUES (?,?,?,?) "
        "ON CONFLICT(asin, domain) DO UPDATE SET data=excluded.data, fetched_at=excluded.fetched_at",
        (asin, domain, json.dumps(data), storage.now_iso()),
    )
    conn.commit()


def get_keepa_product(asin: str, domain: int) -> dict | None:
    row = storage._conn().execute(
        "SELECT * FROM keepa_products WHERE asin=? AND domain=?", (asin, domain)
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["data"] = json.loads(d.get("data") or "{}")
    return d


def list_keepa_products(limit: int = 200) -> list[dict]:
    rows = storage._conn().execute(
        "SELECT * FROM keepa_products ORDER BY fetched_at DESC LIMIT ?", (limit,)
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["data"] = json.loads(d.get("data") or "{}")
        out.append(d)
    return out


def delete_keepa_product(asin: str, domain: int) -> bool:
    conn = storage._conn()
    cur = conn.execute(
        "DELETE FROM keepa_products WHERE asin=? AND domain=?", (asin, domain)
    )
    conn.commit()
    return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Keepa API client + parsing
# ---------------------------------------------------------------------------
def _read_body(data: bytes) -> bytes:
    """Keepa gzips its responses; decompress when the magic bytes are present."""
    if data[:2] == b"\x1f\x8b":
        try:
            return gzip.decompress(data)
        except Exception:
            pass
    return data


def _fetch(asins: list[str], domain: int, api_key: str, stats: int) -> dict:
    params = {
        "key": api_key,
        "domain": str(domain),
        "asin": ",".join(asins),
        "stats": str(stats),
    }
    url = BASE_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url, headers={"User-Agent": "Conductor/1.1", "Accept-Encoding": "gzip"}
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            return json.loads(_read_body(resp.read()).decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = _read_body(exc.read()).decode("utf-8", errors="replace")[:300]
        raise HTTPException(502, f"Keepa API error {exc.code}: {detail}")
    except urllib.error.URLError as exc:
        raise HTTPException(502, f"Keepa API unreachable: {exc.reason}")


def _cents(value) -> float | None:
    """Keepa prices are int cents ($19.99 → 1999)."""
    if value is None or value < 0:
        return None
    try:
        return round(float(value) / 100.0, 2)
    except (TypeError, ValueError):
        return None


def _rating(value) -> float | None:
    """Keepa ratings are int ×10 (4.5 → 45)."""
    if value is None or value < 0:
        return None
    try:
        return round(float(value) / 10.0, 1)
    except (TypeError, ValueError):
        return None


def _best_sales_rank(sales_ranks) -> int | None:
    if not sales_ranks:
        return None
    best = None
    for entry in sales_ranks:
        rank = entry[0] if isinstance(entry, (list, tuple)) else entry
        try:
            rank = int(rank)
        except (TypeError, ValueError):
            continue
        if rank <= 0:
            continue
        if best is None or rank < best:
            best = rank
    return best


def parse_product(p: dict) -> dict:
    """Map a raw Keepa product object to a clean, UI-friendly dict. `stats` is
    retained raw; only the documented `current` scalars are converted."""
    stats = p.get("stats") or {}
    current = stats.get("current") or {}
    images_csv = p.get("imagesCSV") or ""
    images = [u for u in images_csv.split(",") if u.strip()] if images_csv else []

    # Current price: Buy Box first, then new, then list, then used — the number
    # a shopper actually sees first.
    price = None
    for k in ("buyBoxPrice", "newPrice", "listPrice", "buyBoxUsedPrice"):
        if current.get(k) not in (None, -1, 0):
            price = _cents(current.get(k))
            break

    domain_id = p.get("domainId")
    return {
        "asin": p.get("asin") or "",
        "domainId": domain_id,
        "domain": DOMAINS.get(domain_id, str(domain_id or "")),
        "title": p.get("title") or "",
        "brand": p.get("brand") or "",
        "manufacturer": p.get("manufacturer") or "",
        "productGroup": p.get("productGroup") or "",
        "partNumber": p.get("partNumber") or "",
        "model": p.get("model") or "",
        "color": p.get("color") or "",
        "size": p.get("size") or "",
        "binding": p.get("binding") or "",
        "author": p.get("author") or "",
        "parentAsin": p.get("parentAsin") or "",
        "rootCategory": p.get("rootCategory"),
        "categories": p.get("categories") or [],
        "features": p.get("features") or [],
        "images": images,
        "eans": p.get("eanList") or [],
        "upcs": p.get("upcList") or [],
        "current": {
            "price": price,
            "listPrice": _cents(current.get("listPrice")),
            "buyBoxPrice": _cents(current.get("buyBoxPrice")),
            "newPrice": _cents(current.get("newPrice")),
            "usedPrice": _cents(current.get("usedPrice")),
            "salesRank": _best_sales_rank(p.get("salesRanks")),
            "rating": _rating(current.get("rating")),
            "reviewsCount": current.get("count"),
            "isPrime": bool(p.get("isEligibleForPrime")),
            "availabilityAmazon": p.get("availabilityAmazon"),
            "isAdultProduct": bool(p.get("isAdultProduct")),
            "newPriceIsMAP": bool(p.get("newPriceIsMAP")),
        },
        "lastUpdate": p.get("lastUpdate"),
        "lastPriceChange": p.get("lastPriceChange"),
        "lastRatingUpdate": p.get("lastRatingUpdate"),
        "trackingSince": p.get("trackingSince"),
        "csvPoints": len(p.get("csv") or []),
        "stats": stats,
    }


def _split_asins(raw: str) -> list[str]:
    asins = [a.strip().upper() for a in re.split(r"[,\s]+", raw) if a.strip()]
    if not asins:
        raise HTTPException(400, "Provide at least one ASIN.")
    if len(asins) > 100:
        raise HTTPException(400, "Keepa allows up to 100 ASINs per request.")
    return asins


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------
@router.get("/status")
def status():
    return get_config()


@router.post("/config")
def config(body: dict):
    """Persist the API key + default domain to data/keepa.json."""
    cfg = _load_config()
    if body.get("api_key") is not None:
        cfg["api_key"] = str(body["api_key"]).strip()
    if body.get("domain") is not None:
        try:
            d = int(body["domain"])
        except (TypeError, ValueError):
            raise HTTPException(400, "domain must be an integer locale id (1-11)")
        if d not in DOMAINS:
            raise HTTPException(400, "domain must be one of 1-11")
        cfg["domain"] = d
    _save_config({"api_key": cfg["api_key"], "domain": cfg["domain"]})
    return get_config()


@router.post("/lookup")
def lookup(body: dict):
    """Look up live product data for a list of ASINs (cache-aware, token-safe)."""
    cfg = _load_config()
    if not cfg["api_key"]:
        raise HTTPException(400, "Keepa API key not configured — add it in the Keepa view (or set KEEPA_API_KEY).")
    domain = int(body.get("domain") or cfg["domain"])
    if domain not in DOMAINS:
        raise HTTPException(400, "domain must be one of 1-11")
    stats = int(body.get("stats") or DEFAULT_STATS_DAYS)
    refresh = bool(body.get("refresh"))
    asins = _split_asins(str(body.get("asins") or ""))

    cached, to_fetch = [], []
    for a in asins:
        if not refresh:
            hit = get_keepa_product(a, domain)
            if hit:
                cached.append(hit["data"])
                continue
        to_fetch.append(a)

    fetched, meta, not_found = [], {}, []
    if to_fetch:
        payload = _fetch(to_fetch, domain, cfg["api_key"], stats)
        meta = {
            "tokensLeft": payload.get("tokensLeft"),
            "refillRate": payload.get("refillRate"),
            "refillIn": payload.get("refillIn"),
            "tokensConsumed": payload.get("tokensConsumed"),
            "timestamp": payload.get("timestamp"),
        }
        products = payload.get("products") or []
        for idx, asin in enumerate(to_fetch):
            p = products[idx] if idx < len(products) else None
            if not p or not p.get("asin"):
                not_found.append(asin)
                continue
            parsed = parse_product(p)
            parsed["asin"] = parsed["asin"] or asin
            save_keepa_product(asin, domain, parsed)
            fetched.append(parsed)

    results = cached + fetched
    order = {a: i for i, a in enumerate(asins)}
    results.sort(key=lambda r: order.get(r.get("asin"), 10**9))
    not_found.sort(key=lambda a: order.get(a, 10**9))

    return {
        "domain": domain,
        "domain_code": DOMAINS[domain],
        "count": len(results),
        "notFound": not_found,
        "fromCache": len(cached),
        "meta": meta,
        "products": results,
    }


@router.get("/products")
def products(limit: int = 200):
    rows = list_keepa_products(min(limit, 1000))
    return {"count": len(rows), "products": [r["data"] for r in rows]}


@router.delete("/products/{asin}", status_code=204)
def product_delete(asin: str, domain: int = 1):
    if not delete_keepa_product(asin.upper(), domain):
        raise HTTPException(404, "ASIN not cached")
    return None


@router.post("/import")
def import_products(body: dict):
    """Save cached Keepa products into the catalog (`source='keepa'`)."""
    cfg = _load_config()
    domain = int(body.get("domain") or cfg["domain"])
    asins = _split_asins(str(body.get("asins") or ""))

    imported, updated = [], []
    for asin in asins:
        hit = get_keepa_product(asin, domain)
        if not hit:
            continue  # only import what's already been looked up (cached)
        d = hit["data"]
        cur = d.get("current") or {}
        attr = {
            "keepa_asin": asin,
            "brand": d.get("brand"),
            "manufacturer": d.get("manufacturer"),
            "product_group": d.get("productGroup"),
            "part_number": d.get("partNumber"),
            "model": d.get("model"),
            "color": d.get("color"),
            "size": d.get("size"),
            "binding": d.get("binding"),
            "ean": (d.get("eans") or [None])[0],
            "upc": (d.get("upcs") or [None])[0],
            "keepa_price": cur.get("price"),
            "keepa_rank": cur.get("salesRank"),
            "keepa_rating": cur.get("rating"),
            "keepa_reviews": cur.get("reviewsCount"),
            "image": (d.get("images") or [None])[0],
            "keepa_last_update": d.get("lastUpdate"),
        }
        existing = storage._conn().execute(
            "SELECT id, attributes FROM products WHERE sku=?", (asin,)
        ).fetchone()
        if existing:
            merged = {**(json.loads(existing["attributes"] or "{}")), **attr}
            storage.update_product(existing["id"], attributes=merged)
            updated.append(asin)
        else:
            storage.create_product(
                sku=asin,
                name=d.get("title") or asin,
                category=d.get("productGroup") or "general",
                market=d.get("domain") or "US",
                attributes=attr,
                source="keepa",
            )
            imported.append(asin)
    return {
        "imported": imported,
        "updated": updated,
        "missing": [a for a in asins if a not in imported and a not in updated],
    }
