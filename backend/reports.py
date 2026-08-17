"""Report management + CDQ (Catalog Data Quality) analysis.

Reports are stored in the `reports` table as JSON blobs. The flagship report
kind is `cdq` — generated live from the products + compliance-check tables so
the dashboard reflects real catalog state (not a hardcoded snapshot).

Router prefix: /api/reports
"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

import storage

router = APIRouter(prefix="/api/reports", tags=["reports"])

# --------------------------------------------------------------------------
# CDQ computation (live data)
# --------------------------------------------------------------------------
def _brand(attrs: dict) -> str:
    for k in ("brand", "Brand", "BRAND", "manufacturer"):
        v = attrs.get(k)
        if v:
            return str(v).strip()
    return ""


def _quality(products: list[dict], checks_by_product: dict[int, list[dict]]) -> list[dict]:
    """Score each product 0-100 and assign a CDQ grade."""
    out = []
    for p in products:
        name = (p.get("name") or "").strip()
        category = (p.get("category") or "general").strip()
        attrs = p.get("attributes") or {}
        score = 0.0
        if len(name) >= 3:
            score += 30
        if category and category.lower() != "general":
            score += 20
        if len(attrs) >= 2:
            score += 20
        checks = checks_by_product.get(p["id"], [])
        if checks:
            score += (sum(c.get("score") or 0 for c in checks) / len(checks)) * 0.30
        else:
            score += 15  # unknown compliance → partial credit
        score = round(min(100.0, score), 1)
        if score >= 85:
            grade = "A"
        elif score >= 70:
            grade = "B"
        elif score >= 55:
            grade = "C"
        elif score >= 40:
            grade = "D"
        else:
            grade = "U"
        out.append({"id": p["id"], "sku": p.get("sku", ""), "name": name,
                    "category": category, "brand": _brand(attrs), "score": score,
                    "grade": grade, "n_attrs": len(attrs)})
    return out


def generate_cdq() -> dict:
    products = storage.list_products(limit=5000)
    checks = storage.list_checks(limit=20000)
    cbp: dict[int, list[dict]] = {}
    for c in checks:
        cbp.setdefault(c["product_id"], []).append(c)

    rows = _quality(products, cbp)
    total = len(rows) or 1
    scored = sorted(rows, key=lambda r: r["score"])

    grades = {"A": 0, "B": 0, "C": 0, "D": 0, "U": 0}
    for r in rows:
        grades[r["grade"]] += 1
    grade_a = grades["A"]
    priority = grades["D"] + grades["U"]
    brands = sorted({r["brand"] for r in rows if r["brand"]})

    def pct(n: int) -> float:
        return round(n / total * 100, 1)

    cdq_score = round(sum(r["score"] for r in rows) / total, 1)
    struct_attr = pct(sum(1 for r in rows if r["n_attrs"] >= 2))
    title_q = pct(sum(1 for r in rows if len(r["name"]) >= 3))
    cat_cov = pct(sum(1 for r in rows if r["category"] and r["category"].lower() != "general"))
    compliance = round(sum(1 for r in rows if r["score"] >= 70) / total * 100, 1)

    low_struct = sum(1 for r in rows if r["n_attrs"] < 2)
    missing_cat = sum(1 for r in rows if not r["category"] or r["category"].lower() == "general")
    low_compliance = sum(1 for r in rows if r["score"] < 55)

    top_fixes = []
    for rank, r in enumerate(scored[:5], 1):
        if len(r["name"]) < 3:
            issue = "Missing or empty title"
        elif not r["category"] or r["category"].lower() == "general":
            issue = "Missing category — assign a category"
        elif r["n_attrs"] < 2:
            issue = "Low structured attributes — fill material/size/color/etc."
        else:
            issue = "Low compliance score — review attributes against regulations"
        top_fixes.append({"rank": rank, "sku": r["sku"], "brand": r["brand"] or "—",
                          "grade": r["grade"], "issue": issue})

    action_plan = []
    if grades["U"]:
        action_plan.append({"priority": "P0", "issue": "Policy / Grade U listings",
                            "asins": grades["U"], "pct": pct(grades["U"]),
                            "action": "Fix critical defects (titles, images, unit counts)"})
    if grades["D"]:
        action_plan.append({"priority": "P1", "issue": "Egregious defects (Grade D)",
                            "asins": grades["D"], "pct": pct(grades["D"]),
                            "action": "Fix incorrect attributes, dimensions, missing images"})
    if low_struct:
        action_plan.append({"priority": "P1", "issue": "Low structured attributes (<2 fields)",
                            "asins": low_struct, "pct": pct(low_struct),
                            "action": "Fill missing product attributes"})
    if missing_cat:
        action_plan.append({"priority": "P1", "issue": "Missing category",
                            "asins": missing_cat, "pct": pct(missing_cat),
                            "action": "Assign a category to unclassified products"})
    if grades["C"]:
        action_plan.append({"priority": "P2", "issue": "Grade C (below target)",
                            "asins": grades["C"], "pct": pct(grades["C"]),
                            "action": "Improve attribute coverage to reach Grade B"})
    if low_compliance:
        action_plan.append({"priority": "P2", "issue": "Compliance risk",
                            "asins": low_compliance, "pct": pct(low_compliance),
                            "action": "Run the compliance engine and fix flagged issues"})

    findings = [
        {"tone": "good",
         "title": "Baseline",
         "body": f"Catalog quality score {cdq_score}% with {grade_a} Grade-A products "
                 f"({pct(grade_a)}%). Title quality {title_q}% and category coverage "
                 f"{cat_cov}%."},
        {"tone": "critical" if priority else "good",
         "title": "Priority backlog",
         "body": f"{priority} products fall in Grade D/U. Fixing these lifts the overall "
                 f"score fastest."},
        {"tone": "info",
         "title": "Biggest lever",
         "body": f"{low_struct} products ({pct(low_struct)}%) have fewer than 2 structured "
                 f"attributes. Fill material / size / color / weight via flat file to move the "
                 f"weighted 'Structured Attributes' component ({struct_attr}%)."},
    ]

    return {
        "kpis": {
            "total_asins": total if products else 0,
            "cdq_score": cdq_score,
            "grade_a_pct": pct(grade_a),
            "priority_asins": priority,
            "brands": len(brands),
        },
        "grades": [{"grade": g, "count": grades[g]} for g in ("A", "B", "C", "D", "U")],
        "components": [
            {"name": "Structured Attributes", "weight": 30, "score": struct_attr},
            {"name": "Title Quality", "weight": 25, "score": title_q},
            {"name": "Category Coverage", "weight": 20, "score": cat_cov},
            {"name": "Compliance", "weight": 15, "score": compliance},
            {"name": "Data Completeness", "weight": 10, "score": round(100 - pct(low_struct), 1)},
        ],
        "action_plan": action_plan,
        "top_fixes": top_fixes,
        "findings": findings,
    }


# --------------------------------------------------------------------------
# CRUD
# --------------------------------------------------------------------------
def _row_to_report(row) -> dict:
    d = dict(row)
    d["data"] = json.loads(d.get("data") or "{}")
    d["meta"] = json.loads(d.get("meta") or "{}")
    return d


@router.get("")
def list_reports():
    rows = storage._conn().execute(
        "SELECT id, kind, title, meta, created_at FROM reports ORDER BY id DESC LIMIT 100"
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["meta"] = json.loads(d.get("meta") or "{}")
        out.append(d)
    return {"reports": out}


@router.get("/{report_id}")
def get_report(report_id: int):
    row = storage._conn().execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Report not found")
    return {"report": _row_to_report(row)}


@router.post("/generate")
def generate_report(body: dict):
    kind = str(body.get("kind") or "cdq")
    if kind != "cdq":
        raise HTTPException(400, f"Unknown report kind '{kind}' — only 'cdq' is available")
    title = str(body.get("title") or "").strip() or "CDQ Analysis"
    data = generate_cdq()
    meta = {"generated_at": storage.now_iso(), "source": "live", "kind": kind,
            "asin_count": data["kpis"]["total_asins"],
            "brand_count": data["kpis"]["brands"]}
    conn = storage._conn()
    cur = conn.execute(
        "INSERT INTO reports (kind, title, meta, data, created_at) VALUES (?,?,?,?,?)",
        (kind, title, json.dumps(meta), json.dumps(data), storage.now_iso()),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM reports WHERE id=?", (cur.lastrowid,)).fetchone()
    return {"report": _row_to_report(row)}


@router.delete("/{report_id}")
def delete_report(report_id: int):
    conn = storage._conn()
    conn.execute("DELETE FROM reports WHERE id=?", (report_id,))
    conn.commit()
    return {"ok": True}
