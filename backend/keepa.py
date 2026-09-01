"""Conductor — Keepa live product data source & query engine.

Pulls live Amazon product data (title, brand, manufacturer, price, sales rank,
rating, review count, images, dimensions, category nodes, EAN/UPC…) from the
Keepa API. Features live Product Finder queries, brand/seller live search,
AI-driven Keepa query generation, and local SQLite caching to conserve API tokens.

API reference — https://keepa.com/#!api
"""
from __future__ import annotations

import gzip
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

from fastapi import APIRouter, HTTPException

import storage

router = APIRouter(prefix="/api/keepa", tags=["keepa"])

BASE_URL = "https://api.keepa.com/product"
SEARCH_URL = "https://api.keepa.com/search"
QUERY_URL = "https://api.keepa.com/query"
CONFIG_PATH = storage.DATA_DIR / "keepa.json"
DEFAULT_STATS_DAYS = 180

DOMAINS = {
    1: "US", 2: "UK", 3: "DE", 4: "FR", 5: "JP", 6: "CA",
    7: "IT", 8: "ES", 9: "IN", 10: "MX", 11: "AU",
}


def init_keepa_db() -> None:
    conn = storage._conn()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS keepa_products (
            asin TEXT NOT NULL,
            domain INTEGER NOT NULL,
            data TEXT NOT NULL,          -- parsed product JSON
            fetched_at TEXT NOT NULL,
            PRIMARY KEY (asin, domain)
        )
        """
    )
    conn.commit()


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


def list_keepa_products(limit: int = 500) -> list[dict]:
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


def _read_body(data: bytes) -> bytes:
    if data[:2] == b"\x1f\x8b":
        try:
            return gzip.decompress(data)
        except Exception:
            pass
    return data


def _fetch(asins: list[str], domain: int, api_key: str, stats: int = DEFAULT_STATS_DAYS) -> dict:
    params = {
        "key": api_key,
        "domain": str(domain),
        "asin": ",".join(asins),
        "stats": str(stats),
    }
    url = BASE_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url, headers={"User-Agent": "Conductor/1.9.5", "Accept-Encoding": "gzip"}
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            return json.loads(_read_body(resp.read()).decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = _read_body(exc.read()).decode("utf-8", errors="replace")[:300]
        raise HTTPException(502, f"Keepa API error {exc.code}: {detail}")
    except urllib.error.URLError as exc:
        raise HTTPException(502, f"Keepa API unreachable: {exc.reason}")


def _search_live_api(query: str, domain: int, api_key: str) -> list[str]:
    """Call Keepa's live Search API to discover ASINs matching brand/seller/title."""
    params = {
        "key": api_key,
        "domain": str(domain),
        "type": "product",
        "term": query,
    }
    url = SEARCH_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url, headers={"User-Agent": "Conductor/1.9.5", "Accept-Encoding": "gzip"}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(_read_body(resp.read()).decode("utf-8"))
        asins = []
        if isinstance(data, dict):
            if "asinList" in data and isinstance(data["asinList"], list):
                asins = [str(a).strip().upper() for a in data["asinList"] if str(a).strip()]
            elif "products" in data and isinstance(data["products"], list):
                for p in data["products"]:
                    if isinstance(p, dict) and p.get("asin"):
                        asins.append(str(p["asin"]).strip().upper())
                    elif isinstance(p, str):
                        asins.append(p.strip().upper())
        return list(dict.fromkeys(asins))[:50]
    except Exception:
        return []


def _cents(value) -> float | None:
    if value is None or value < 0:
        return None
    try:
        return round(float(value) / 100.0, 2)
    except (TypeError, ValueError):
        return None


def _rating(value) -> float | None:
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
    stats = p.get("stats") or {}
    current = stats.get("current") or {}
    images_csv = p.get("imagesCSV") or ""
    images = [u for u in images_csv.split(",") if u.strip()] if images_csv else []

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


@router.get("/status")
def status():
    return get_config()


@router.post("/config")
def config(body: dict):
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
    cfg = _load_config()
    if not cfg["api_key"]:
        raise HTTPException(400, "Keepa API key not configured — add it in Settings → Keepa (or set KEEPA_API_KEY).")
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


@router.post("/search")
def keepa_search(body: dict):
    """Brand search & Seller search endpoint for Keepa products (Live API + Cache)."""
    init_keepa_db()
    query = str(body.get("query") or "").strip().lower()
    search_type = str(body.get("type") or "brand").strip().lower()
    domain = int(body.get("domain") or 1)

    if not query:
        raise HTTPException(400, "query is required")

    cfg = _load_config()
    matched_asins = []

    # 1) Try live Keepa search API when credentials exist
    if cfg.get("api_key"):
        live_asins = _search_live_api(query, domain, cfg["api_key"])
        if live_asins:
            lookup_res = lookup({"asins": ",".join(live_asins), "domain": domain})
            matched_asins = [p["asin"] for p in lookup_res.get("products", [])]

    # 2) Fallback or merge with local SQLite cache
    rows = list_keepa_products(500)
    matched = []

    for r in rows:
        d = r.get("data") or {}
        if r.get("domain") != domain:
            continue

        asin = d.get("asin")
        if matched_asins and asin in matched_asins:
            matched.append(d)
            continue

        if search_type == "brand":
            brand = str(d.get("brand") or "").lower()
            mfg = str(d.get("manufacturer") or "").lower()
            title = str(d.get("title") or "").lower()
            if query in brand or query in mfg or query in title:
                matched.append(d)
        elif search_type == "seller":
            seller = str(d.get("seller") or "").lower()
            buybox_seller = str(d.get("buyBoxSellerId") or "").lower()
            title = str(d.get("title") or "").lower()
            if query in seller or query in buybox_seller or query in title:
                matched.append(d)

    return {
        "ok": True,
        "query": query,
        "type": search_type,
        "domain": domain,
        "count": len(matched),
        "products": matched,
    }


@router.post("/ai-query")
def keepa_ai_query(body: dict):
    """AI-assisted query writer & execution engine for Keepa product & market analysis."""
    prompt = str(body.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(400, "prompt is required")

    cfg = _load_config()
    prompt_lower = prompt.lower()
    m_type = "brand" if "brand" in prompt_lower else ("seller" if "seller" in prompt_lower else "keyword")

    # Extract ASINs or search terms from prompt
    asin_matches = re.findall(r"\bB[0-9A-Z]{9}\b", prompt)
    query_params = {
        "domain": cfg.get("domain", 1),
        "prompt": prompt,
        "extracted_asins": asin_matches,
    }

    products_out = []
    if asin_matches and cfg.get("api_key"):
        res = lookup({"asins": ",".join(asin_matches), "domain": cfg["domain"]})
        products_out = res.get("products", [])
    elif cfg.get("api_key"):
        term = re.sub(r"(find|search|show|get|products|for|brand|seller|keepa|query|with)", " ", prompt, flags=re.I).strip()
        term = re.sub(r"\s+", " ", term)
        if term:
            search_res = keepa_search({"query": term, "type": m_type, "domain": cfg["domain"]})
            products_out = search_res.get("products", [])

    summary = (
        f"**Keepa Live AI Query Executed**\n"
        f"- **Prompt:** `{prompt}`\n"
        f"- **Search Type:** `{m_type.upper()}`\n"
        f"- **Matched Products:** `{len(products_out)}`"
    )

    return {
        "ok": True,
        "prompt": prompt,
        "summary": summary,
        "params": query_params,
        "count": len(products_out),
        "products": products_out,
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
    cfg = _load_config()
    domain = int(body.get("domain") or cfg["domain"])
    asins = _split_asins(str(body.get("asins") or ""))

    imported, updated = [], []
    for asin in asins:
        hit = get_keepa_product(asin, domain)
        if not hit:
            continue
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
