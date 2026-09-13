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
# Scoring presets
#
# A preset is the SINGLE source of truth for CDQ scoring: the same component
# list produces the per-product score *and* the component breakdown the
# dashboard renders. Before presets these were two independent hardcoded
# formulas (computed 30/20/20/30 vs displayed 30/25/20/15/10) which silently
# drifted apart — the bars and the score disagreed. Reading both from one
# preset makes that drift structurally impossible.
#
# The built-in "default" preset ships the *computed* weights, so the score and
# every grade downstream are unchanged when no custom preset is configured.
# --------------------------------------------------------------------------
SCORING_SCOPE = "scoring"
PRESETS_CONFIG_KEY = "presets"
TIERS_CONFIG_KEY = "tiers"
DEFAULT_PRESET_KEY = "default"

#: Rules a component may use. Each maps a product to 0..weight points.
#:   min_length     — text field length gate (all-or-nothing)
#:   non_default    — field is set and not a placeholder value (all-or-nothing)
#:   min_count      — mapping/collection has at least `min` entries (all-or-nothing)
#:   checks_average — continuous: mean compliance-check score scaled to weight,
#:                    `unknown_credit` * weight when the product has no checks
SCORING_RULES = ("min_length", "non_default", "min_count", "checks_average")

DEFAULT_GRADE_CUTOFFS = [
    {"grade": "A", "min": 85},
    {"grade": "B", "min": 70},
    {"grade": "C", "min": 55},
    {"grade": "D", "min": 40},
    {"grade": "U", "min": 0},
]

BUILTIN_PRESETS: dict[str, dict] = {
    DEFAULT_PRESET_KEY: {
        "key": DEFAULT_PRESET_KEY,
        "label": "Default CDQ",
        "description": "Shipped catalog-quality weighting: title 30, category 20, "
                       "structured attributes 20, compliance 30.",
        "components": [
            {"key": "title", "name": "Title Quality", "weight": 30,
             "rule": "min_length", "field": "name", "min": 3,
             "issue": "Missing or empty title"},
            {"key": "category", "name": "Category Coverage", "weight": 20,
             "rule": "non_default", "field": "category", "excludes": ["general"],
             "issue": "Missing category — assign a category"},
            {"key": "attributes", "name": "Structured Attributes", "weight": 20,
             "rule": "min_count", "field": "attributes", "min": 2,
             "issue": "Low structured attributes — fill material/size/color/etc."},
            {"key": "compliance", "name": "Compliance", "weight": 30,
             "rule": "checks_average", "unknown_credit": 0.5, "display_threshold": 70,
             "issue": "Low compliance score — review attributes against regulations"},
        ],
        "grades": DEFAULT_GRADE_CUTOFFS,
    },
}


# --------------------------------------------------------------------------
# Tier normalization
#
# Reports carry four unreconciled vocabularies (CDQ grades, action priorities,
# finding tones, compliance severities). Each maps into one normalized tier so
# a single tier filter can span all of them. The stored vocabularies are never
# rewritten — `tier` is an additive derived field.
# --------------------------------------------------------------------------
DEFAULT_TIER_DEFINITIONS = [
    {"key": "critical", "label": "Critical", "rank": 0, "color_token": "--t-function-danger"},
    {"key": "high", "label": "High", "rank": 1, "color_token": "--t-function-danger"},
    {"key": "warning", "label": "Warning", "rank": 2, "color_token": "--yellow"},
    {"key": "info", "label": "Info", "rank": 3, "color_token": "--t-function-primary"},
    {"key": "ok", "label": "OK", "rank": 4, "color_token": "--t-function-success"},
]

DEFAULT_TIER_VOCABULARIES = {
    "cdq_grade": {"U": "critical", "D": "high", "C": "warning", "B": "info", "A": "ok"},
    "action_priority": {"P0": "critical", "P1": "high", "P2": "warning", "P3": "info"},
    "finding_tone": {"critical": "critical", "warn": "warning", "warning": "warning",
                     "info": "info", "good": "ok"},
    "compliance_severity": {"blocker": "critical", "warning": "warning",
                            "info": "info", "ok": "ok"},
}


def _spine_read(scope: str, key: str, default: dict) -> dict:
    """Read a spine user-config value, tolerating an un-initialised spine."""
    try:
        from spine import user_config
        value = user_config.read_configuration_value(scope, key, default)
    except Exception:  # spine unavailable / table missing → shipped defaults
        return dict(default)
    return value if isinstance(value, dict) else dict(default)


def _spine_write(scope: str, key: str, value: dict) -> None:
    from spine.schema import init_tables
    from spine import user_config

    init_tables()  # idempotent; the mapping/scoring pages may run before startup seeding
    user_config.put_configuration(scope, key, {"value": value})


def tier_catalog() -> dict:
    """Tier definitions + vocabulary mapping, as data the UI can render filters from."""
    override = _spine_read(SCORING_SCOPE, TIERS_CONFIG_KEY, {})
    definitions = override.get("definitions")
    if not isinstance(definitions, list) or not definitions:
        definitions = [dict(d) for d in DEFAULT_TIER_DEFINITIONS]
    else:
        definitions = [dict(d) for d in definitions if isinstance(d, dict) and d.get("key")]
    vocabularies = {name: dict(mapping) for name, mapping in DEFAULT_TIER_VOCABULARIES.items()}
    for name, mapping in (override.get("vocabularies") or {}).items():
        if isinstance(mapping, dict):
            vocabularies.setdefault(name, {}).update({str(k): str(v) for k, v in mapping.items()})
    return {
        "definitions": definitions,
        "vocabularies": vocabularies,
        "options": [{"value": d["key"], "label": d.get("label") or d["key"],
                     "rank": d.get("rank", 99)} for d in definitions],
    }


def tier_for(vocabulary: str, value: object, default: str = "") -> str:
    """Normalize one vocabulary value (a grade, priority, tone, severity) to a tier."""
    mapping = tier_catalog()["vocabularies"].get(vocabulary) or {}
    raw = str(value or "")
    return mapping.get(raw) or mapping.get(raw.lower()) or mapping.get(raw.upper()) or default


def _tier_rank(catalog: dict) -> dict[str, int]:
    return {d["key"]: d.get("rank", 99) for d in catalog["definitions"]}


# --------------------------------------------------------------------------
# Preset resolution
# --------------------------------------------------------------------------
def _int_like(value: float) -> float | int:
    return int(value) if float(value).is_integer() else round(float(value), 4)


def _normalise_preset(raw: object) -> dict:
    if not isinstance(raw, dict):
        raise HTTPException(400, "preset must be an object")
    raw_components = raw.get("components")
    if not isinstance(raw_components, list) or not raw_components:
        raise HTTPException(400, "preset.components must be a non-empty list")
    components: list[dict] = []
    for index, entry in enumerate(raw_components, 1):
        if not isinstance(entry, dict):
            raise HTTPException(400, "preset.components entries must be objects")
        rule = str(entry.get("rule") or "")
        if rule not in SCORING_RULES:
            raise HTTPException(400, f"Unknown scoring rule '{rule}'")
        try:
            weight = float(entry.get("weight"))
        except (TypeError, ValueError):
            raise HTTPException(400, "preset.components[].weight must be a number")
        if weight < 0:
            raise HTTPException(400, "preset.components[].weight cannot be negative")
        key = str(entry.get("key") or f"component_{index}")
        components.append({**entry, "key": key,
                           "name": str(entry.get("name") or key.replace("_", " ").title()),
                           "weight": _int_like(weight), "rule": rule})
    keys = [c["key"] for c in components]
    if len(set(keys)) != len(keys):
        raise HTTPException(400, "preset.components[].key must be unique")
    total = sum(float(c["weight"]) for c in components)
    if round(total, 6) != 100.0:
        raise HTTPException(400, f"preset component weights must total 100 (got {_int_like(total)})")

    raw_grades = raw.get("grades") or DEFAULT_GRADE_CUTOFFS
    if not isinstance(raw_grades, list) or not raw_grades:
        raise HTTPException(400, "preset.grades must be a non-empty list")
    grades: list[dict] = []
    for entry in raw_grades:
        if not isinstance(entry, dict) or not entry.get("grade"):
            raise HTTPException(400, "preset.grades entries need a 'grade'")
        try:
            minimum = float(entry.get("min", 0))
        except (TypeError, ValueError):
            raise HTTPException(400, "preset.grades[].min must be a number")
        grades.append({"grade": str(entry["grade"]), "min": _int_like(minimum)})
    grades.sort(key=lambda g: float(g["min"]), reverse=True)

    key = str(raw.get("key") or DEFAULT_PRESET_KEY)
    return {
        "key": key,
        "label": str(raw.get("label") or key.replace("_", " ").title()),
        "description": str(raw.get("description") or ""),
        "builtin": key in BUILTIN_PRESETS,
        "components": components,
        "grades": grades,
    }


def stored_presets() -> dict[str, dict]:
    """Custom presets persisted through spine.user_config (scope 'scoring')."""
    value = _spine_read(SCORING_SCOPE, PRESETS_CONFIG_KEY, {})
    return {str(k): v for k, v in value.items() if isinstance(v, dict)}


def load_preset(preset: str | dict | None = None) -> dict:
    """Resolve a preset key (or an inline preset body) to a validated preset."""
    if isinstance(preset, dict):
        return _normalise_preset(preset)
    key = str(preset or DEFAULT_PRESET_KEY).strip() or DEFAULT_PRESET_KEY
    custom = stored_presets()
    if key in custom:
        return _normalise_preset({**custom[key], "key": key})
    if key in BUILTIN_PRESETS:
        return _normalise_preset(BUILTIN_PRESETS[key])
    raise HTTPException(404, f"Unknown scoring preset '{key}'")


def list_presets() -> list[dict]:
    custom = stored_presets()
    out = [_normalise_preset(BUILTIN_PRESETS[k]) for k in BUILTIN_PRESETS if k not in custom]
    for key, body in custom.items():
        out.append(_normalise_preset({**body, "key": key}))
    return sorted(out, key=lambda p: (not p["builtin"], p["key"]))


def save_preset(key: str, body: dict) -> dict:
    key = str(key or "").strip()
    if not key:
        raise HTTPException(400, "preset key is required")
    preset = _normalise_preset({**body, "key": key})
    presets = stored_presets()
    presets[key] = {k: v for k, v in preset.items() if k != "builtin"}
    _spine_write(SCORING_SCOPE, PRESETS_CONFIG_KEY, presets)
    return preset


def delete_preset(key: str) -> dict:
    presets = stored_presets()
    if key not in presets:
        raise HTTPException(404, f"Unknown scoring preset '{key}'")
    presets.pop(key)
    _spine_write(SCORING_SCOPE, PRESETS_CONFIG_KEY, presets)
    return {"ok": True, "key": key}


# --------------------------------------------------------------------------
# CDQ computation (live data)
# --------------------------------------------------------------------------
def _brand(attrs: dict) -> str:
    for k in ("brand", "Brand", "BRAND", "manufacturer"):
        v = attrs.get(k)
        if v:
            return str(v).strip()
    return ""


def _component_points(component: dict, *, name: str, category: str, attrs: dict,
                      checks: list[dict]) -> float:
    """Points this component awards one product — 0..component weight."""
    rule = component["rule"]
    weight = component["weight"]
    if rule == "min_length":
        return float(weight) if len(name) >= int(component.get("min", 1)) else 0.0
    if rule == "non_default":
        excludes = {str(x).lower() for x in (component.get("excludes") or ())}
        return float(weight) if category and category.lower() not in excludes else 0.0
    if rule == "min_count":
        return float(weight) if len(attrs) >= int(component.get("min", 1)) else 0.0
    if rule == "checks_average":
        if checks:
            return (sum(c.get("score") or 0 for c in checks) / len(checks)) * (weight / 100.0)
        return weight * float(component.get("unknown_credit", 0.5))
    raise HTTPException(400, f"Unknown scoring rule '{rule}'")


def _grade_for(score: float, cutoffs: list[dict]) -> str:
    for cutoff in cutoffs:
        if score >= float(cutoff["min"]):
            return cutoff["grade"]
    return cutoffs[-1]["grade"]


def _quality(products: list[dict], checks_by_product: dict[int, list[dict]],
             preset: dict | None = None) -> list[dict]:
    """Score each product 0-100 and assign a CDQ grade, driven by `preset`."""
    resolved = preset or load_preset()
    components = resolved["components"]
    cutoffs = resolved["grades"]
    out = []
    for p in products:
        name = (p.get("name") or "").strip()
        category = (p.get("category") or "general").strip()
        attrs = p.get("attributes") or {}
        checks = checks_by_product.get(p["id"], [])
        score = 0.0
        points: dict[str, float] = {}
        for component in components:
            earned = _component_points(component, name=name, category=category,
                                       attrs=attrs, checks=checks)
            points[component["key"]] = earned
            score += earned
        score = round(min(100.0, score), 1)
        out.append({"id": p["id"], "sku": p.get("sku", ""), "name": name,
                    "category": category, "brand": _brand(attrs), "score": score,
                    "grade": _grade_for(score, cutoffs), "n_attrs": len(attrs),
                    "component_points": points})
    return out


def generate_cdq(preset: str | dict | None = None) -> dict:
    resolved = load_preset(preset)
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
def _report_parameters(value: object) -> dict:
    """Keep report filters explicit and reject ambiguous or inverted ranges."""
    if value is None:
        params = {}
    elif not isinstance(value, dict):
        raise HTTPException(400, "parameters must be an object")
    else:
        params = value
    allowed = {"date", "dateFrom", "dateTo", "latestOnly", "dataType", "sourceId", "reportKind"}
    clean = {key: params[key] for key in allowed if key in params and params[key] is not None}
    if "latestOnly" in clean and not isinstance(clean["latestOnly"], bool):
        raise HTTPException(400, "parameters.latestOnly must be a boolean")
    if clean.get("dateFrom") and clean.get("dateTo") and str(clean["dateFrom"]) > str(clean["dateTo"]):
        raise HTTPException(400, "parameters.dateFrom cannot be after parameters.dateTo")
    return clean


def _row_to_report(row) -> dict:
    d = dict(row)
    d["data"] = json.loads(d.get("data") or "{}")
    d["meta"] = json.loads(d.get("meta") or "{}")
    meta = d["meta"]
    source_kind = meta.get("source") or "stored"
    parameters = meta.get("parameters") if isinstance(meta.get("parameters"), dict) else {}
    d.update({
        "schemaVersion": 1,
        "type": d["kind"],
        "createdAt": d["created_at"],
        "updatedAt": meta.get("updated_at") or d["created_at"],
        "source": {"kind": source_kind, "system": "sqlite", "dataset": meta.get("dataset") or "products"},
        "parameters": parameters,
        "summary": d["data"].get("kpis", {}) if isinstance(d["data"], dict) else {},
        "renderHints": meta.get("render_hints") or {},
        "actions": ["view", "refresh", "replace", "delete", "rerun"],
    })
    return d


@router.get("")
def list_reports(
    kind: str | None = None,
    source: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    latest_only: bool = False,
):
    rows = storage._conn().execute(
        "SELECT id, kind, title, meta, data, created_at FROM reports ORDER BY id DESC LIMIT 100"
    ).fetchall()
    out = []
    for r in rows:
        report = _row_to_report(r)
        if kind and report["type"] != kind:
            continue
        if source and report["source"]["kind"] != source:
            continue
        if date_from and report["createdAt"] < date_from:
            continue
        if date_to and report["createdAt"] > date_to:
            continue
        out.append(report)
    if latest_only:
        seen: set[tuple[str, str]] = set()
        latest = []
        for report in out:
            key = (report["type"], report["source"]["kind"])
            if key not in seen:
                latest.append(report)
                seen.add(key)
        out = latest
    return {"reports": out}


@router.get("/{report_id}")
def get_report(report_id: int):
    row = storage._conn().execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Report not found")
    return {"report": _row_to_report(row)}


def _generate_report(kind: str, title: str, parameters: dict, lineage: dict | None = None) -> dict:
    if kind != "cdq":
        raise HTTPException(400, f"Unknown report kind '{kind}'; only 'cdq' is available")
    data = generate_cdq()
    stamp = storage.now_iso()
    meta = {
        "generated_at": stamp,
        "updated_at": stamp,
        "source": "live",
        "kind": kind,
        "dataset": "products",
        "parameters": parameters,
        "asin_count": data["kpis"]["total_asins"],
        "brand_count": data["kpis"]["brands"],
    }
    if lineage:
        meta.update(lineage)
    conn = storage._conn()
    cur = conn.execute(
        "INSERT INTO reports (kind, title, meta, data, created_at) VALUES (?,?,?,?,?)",
        (kind, title, json.dumps(meta), json.dumps(data), stamp),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM reports WHERE id=?", (cur.lastrowid,)).fetchone()
    return {"report": _row_to_report(row)}


@router.post("/generate")
def generate_report(body: dict):
    kind = str(body.get("kind") or "cdq")
    title = str(body.get("title") or "").strip() or "CDQ Analysis"
    return _generate_report(kind, title, _report_parameters(body.get("parameters")))


@router.post("/{report_id}/rerun")
def rerun_report(report_id: int, body: dict | None = None):
    row = storage._conn().execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Report not found")
    report = _row_to_report(row)
    body = body or {}
    parameters = {**report["parameters"], **_report_parameters(body.get("parameters"))}
    title = str(body.get("title") or report["title"]).strip() or report["title"]
    return _generate_report(report["type"], title, parameters, {"rerun_of": report_id})


@router.post("/{report_id}/replace")
def replace_report(report_id: int, body: dict | None = None):
    row = storage._conn().execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Report not found")
    report = _row_to_report(row)
    body = body or {}
    parameters = {**report["parameters"], **_report_parameters(body.get("parameters"))}
    title = str(body.get("title") or report["title"]).strip() or report["title"]
    result = _generate_report(report["type"], title, parameters, {"replaces": report_id})
    meta = {**report["meta"], "replaced_by": result["report"]["id"], "updated_at": storage.now_iso()}
    conn = storage._conn()
    conn.execute("UPDATE reports SET meta=? WHERE id=?", (json.dumps(meta), report_id))
    conn.commit()
    return result


@router.delete("/{report_id}")
def delete_report(report_id: int):
    conn = storage._conn()
    conn.execute("DELETE FROM reports WHERE id=?", (report_id,))
    conn.commit()
    return {"ok": True}
