"""Feature Studio — turn a report into a reusable, runnable feature.

Pipeline:
  1. `derive`  — paste a report; AI extracts the rating's factors + scoring
                 logic + Asana action bands (STRICT JSON). No key? returns a
                 blank, editable template so users can build by hand.
  2. save/CRUD — store the feature spec (factors with executable rules).
  3. `run`     — apply the factors against live catalog data → per-listing score.
  4. `push-asana` — create Asana tasks for listings that fall in a band
                 (live with a PAT, simulated otherwise).
  5. `build`   — generate a Bernie workflow diagram (canvas) + an automation.

Router prefix: /api/features
"""
from __future__ import annotations

import json
import re

from fastapi import APIRouter, HTTPException

import storage
import automation

router = APIRouter(prefix="/api/features", tags=["features"])

FIELDS = ("name", "sku", "category", "market", "brand", "source")
TYPES = ("present", "min_length", "max_length", "contains", "in_values")


# --------------------------------------------------------------------------
# AI plumbing (mirrors ai_ingest)
# --------------------------------------------------------------------------
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


def _ai_json(system: str, user: str):
    ready = _provider_ready()
    if not ready:
        raise ValueError("No AI provider key configured — add one in Settings → AI Chat, or build the feature by hand.")
    provider, model, api_key = ready
    import providers
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    text = ""
    for ev in providers.stream_provider(provider, messages, model=model, api_key=api_key):
        if ev["type"] == "text":
            text += ev["text"]
        elif ev["type"] == "error":
            raise ValueError(f"Provider error: {ev.get('code')} {ev.get('message')}")
    parsed = _extract_json(text)
    if parsed is None:
        raise ValueError("AI returned unparseable output (expected JSON).")
    return parsed


DERIVE_SYSTEM = """You are the Feature Studio AI inside Conductor, a desktop app for an e-commerce
operator (Amazon/Walmart/TikTok/etc). You turn a human report about a NEW listing-quality
rating into a machine-runnable feature spec. Respond with STRICT JSON ONLY — a single object:

{
  "name": "<short feature name>",
  "description": "<1-2 sentence summary of what it evaluates>",
  "rating_label": "<the rating's name, e.g. 'Listing Quality Score (0-100)'>",
  "factors": [
    {"label": "<human description of the check>", "field": "<data field>",
     "type": "<rule type>", "args": {<rule args>}, "weight": <int>}
  ],
  "actions": [
    {"min_score": <int>, "max_score": <int>, "project": "<Asana project name>",
     "name_template": "Fix listing {sku}", "notes_template": "Score {score}/100. Failed: {failed_factors}"}
  ]
}

RULES:
- "field" MUST be one of: name, sku, category, market, brand, source — OR an attribute key
  the report implies lives on the product (e.g. "bullet_points", "images", "a_plus_content").
- "type" MUST be one of: present, min_length, max_length, contains, in_values.
  * present     → args: {}                       (field is non-empty)
  * min_length  → args: {"min": <int>}           (text length >= min)
  * max_length  → args: {"max": <int>}           (text length <= max)
  * contains    → args: {"text": "<substring>"}  (field contains text, case-insensitive)
  * in_values   → args: {"values": ["<a>","<b>"]} (field equals one of the values)
- weights should sum to ~100. Derive 4-10 factors.
- actions are score bands: a listing whose score is within [min_score, max_score) triggers an
  Asana task using the templates ({sku},{name},{score},{failed_factors} placeholders allowed).
  If the report doesn't specify bands, use [0,60) and [60,80) as a sensible default.
- Only output the JSON object — no prose, no markdown."""


def _blank_spec() -> dict:
    return {
        "name": "", "description": "", "rating_label": "Listing Quality Score (0-100)",
        "factors": [], "actions": [{"min_score": 0, "max_score": 60, "project": "Catalog Ops",
                                    "name_template": "Fix listing {sku} ({score}/100)",
                                    "notes_template": "Score {score}/100. Failed factors: {failed_factors}"}],
        "source_report": "",
    }


# --------------------------------------------------------------------------
# factor normalization + scoring
# --------------------------------------------------------------------------
def _brand(attrs: dict) -> str:
    for k in ("brand", "Brand", "BRAND", "manufacturer"):
        v = attrs.get(k)
        if v:
            return str(v).strip()
    return ""


def _field_value(p: dict, field: str) -> str:
    f = (field or "").strip()
    attrs = p.get("attributes") or {}
    if f in ("name", "sku", "category", "market", "source"):
        return str(p.get(f) or "").strip()
    if f == "brand":
        return _brand(attrs)
    for k, v in attrs.items():
        if k.lower() == f.lower():
            return str(v).strip()
    # any attribute whose key contains the field
    for k, v in attrs.items():
        if f.lower() in k.lower():
            return str(v).strip()
    return ""


def _normalize_factor(f: dict) -> dict:
    f = f if isinstance(f, dict) else {}
    field = str(f.get("field") or "name").strip()
    t = str(f.get("type") or "present").strip()
    if t not in TYPES:
        t = "present"
    args = f.get("args") if isinstance(f.get("args"), dict) else {}
    weight = int(f.get("weight") or 10)
    return {
        "key": re.sub(r"[^a-z0-9_]+", "_", str(f.get("label") or field).lower()).strip("_") or "factor",
        "label": str(f.get("label") or field).strip() or field,
        "field": field, "type": t,
        "args": {k: v for k, v in args.items() if k in ("min", "max", "text", "values")},
        "weight": max(1, min(100, weight)),
    }


def _evaluate(value: str, factor: dict) -> bool:
    t = factor.get("type") or "present"
    args = factor.get("args") or {}
    v = (value or "").strip()
    if t == "min_length":
        return len(v) >= int(args.get("min", 1))
    if t == "max_length":
        return len(v) <= int(args.get("max", 1000))
    if t == "contains":
        needle = str(args.get("text", "")).lower()
        return needle in v.lower() if needle else True
    if t == "in_values":
        vals = [str(x).lower() for x in (args.get("values") or [])]
        return v.lower() in vals if vals else True
    return bool(v)  # present


def _score_product(p: dict, factors: list[dict]) -> dict:
    earned = 0
    total = 0
    failed = []
    for f in factors:
        total += f["weight"]
        if _evaluate(_field_value(p, f["field"]), f):
            earned += f["weight"]
        else:
            failed.append(f["label"])
    score = round(earned / total * 100) if total else 0
    return {"product_id": p["id"], "sku": p.get("sku") or "", "name": p.get("name") or "",
            "category": p.get("category") or "", "score": score,
            "failed_factors": failed, "passed": not failed}


def _spec_row(r) -> dict:
    d = dict(r)
    d["spec"] = json.loads(d.get("spec") or "{}")
    return d


def _render(tpl: str, ctx: dict) -> str:
    out = str(tpl or "")
    for k, v in ctx.items():
        if isinstance(v, (str, int, float, bool)):
            out = out.replace("{" + k + "}", str(v))
    return out


# --------------------------------------------------------------------------
# routes
# --------------------------------------------------------------------------
@router.post("/derive")
def derive(body: dict):
    report = str(body.get("report") or "").strip()
    if not report:
        raise HTTPException(400, "report text is required")
    spec = _blank_spec()
    error = None
    ai = False
    try:
        parsed = _ai_json(DERIVE_SYSTEM, f"Report:\n\"\"\"{report[:12000]}\"\"\"")
        if isinstance(parsed, dict):
            ai = True
            spec["name"] = str(parsed.get("name") or "").strip()
            spec["description"] = str(parsed.get("description") or "").strip()
            spec["rating_label"] = str(parsed.get("rating_label") or spec["rating_label"]).strip()
            spec["factors"] = [_normalize_factor(f) for f in (parsed.get("factors") or [])]
            spec["factors"] = [f for f in spec["factors"] if f["field"]]
            acts = parsed.get("actions") or []
            if isinstance(acts, list) and acts:
                spec["actions"] = []
                for a in acts:
                    if not isinstance(a, dict):
                        continue
                    spec["actions"].append({
                        "min_score": int(a.get("min_score", 0)),
                        "max_score": int(a.get("max_score", 60)),
                        "project": str(a.get("project") or "Catalog Ops").strip(),
                        "name_template": str(a.get("name_template") or "Fix listing {sku}").strip(),
                        "notes_template": str(a.get("notes_template") or "").strip(),
                    })
    except Exception as exc:
        error = str(exc)
    spec["source_report"] = report
    return {"ai": ai, "error": error, "spec": spec}


@router.get("")
def list_features():
    rows = storage._conn().execute("SELECT * FROM features ORDER BY updated_at DESC").fetchall()
    out = []
    for r in rows:
        d = _spec_row(r)
        out.append({"id": d["id"], "name": d["name"], "description": d["description"],
                    "factor_count": len(d["spec"].get("factors") or []),
                    "action_count": len(d["spec"].get("actions") or []),
                    "rating_label": d["spec"].get("rating_label", ""),
                    "updated_at": d["updated_at"]})
    return out


@router.get("/{feature_id}")
def get_feature(feature_id: int):
    r = storage._conn().execute("SELECT * FROM features WHERE id=?", (feature_id,)).fetchone()
    if not r:
        raise HTTPException(404, "Feature not found")
    return _spec_row(r)


@router.post("", status_code=201)
def create_feature(body: dict):
    spec = body.get("spec") if isinstance(body.get("spec"), dict) else body
    name = str(spec.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "name is required")
    spec["factors"] = [_normalize_factor(f) for f in (spec.get("factors") or [])]
    spec["factors"] = [f for f in spec["factors"] if f["field"]]
    now = storage.now_iso()
    cur = storage._conn().execute(
        "INSERT INTO features (name, description, spec, created_at, updated_at) VALUES (?,?,?,?,?)",
        (name, str(spec.get("description") or "").strip(), json.dumps(spec), now, now),
    )
    storage._conn().commit()
    return get_feature(cur.lastrowid)


@router.put("/{feature_id}")
def update_feature(feature_id: int, body: dict):
    if not storage._conn().execute("SELECT id FROM features WHERE id=?", (feature_id,)).fetchone():
        raise HTTPException(404, "Feature not found")
    spec = body.get("spec") if isinstance(body.get("spec"), dict) else body
    name = str(spec.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "name is required")
    spec["factors"] = [_normalize_factor(f) for f in (spec.get("factors") or [])]
    spec["factors"] = [f for f in spec["factors"] if f["field"]]
    storage._conn().execute(
        "UPDATE features SET name=?, description=?, spec=?, updated_at=? WHERE id=?",
        (name, str(spec.get("description") or "").strip(), json.dumps(spec), storage.now_iso(), feature_id),
    )
    storage._conn().commit()
    return get_feature(feature_id)


@router.delete("/{feature_id}", status_code=204)
def delete_feature(feature_id: int):
    storage._conn().execute("DELETE FROM features WHERE id=?", (feature_id,))
    storage._conn().commit()
    return None


@router.post("/{feature_id}/run")
def run_feature(feature_id: int, body: dict | None = None):
    body = body or {}
    f = get_feature(feature_id)
    factors = f["spec"].get("factors") or []
    if not factors:
        raise HTTPException(400, "This feature has no factors — add some before running.")
    limit = int(body.get("limit") or 200)
    products = storage.list_products(limit=min(limit, 1000))
    results = [_score_product(p, factors) for p in products]
    results.sort(key=lambda r: r["score"])
    return {"feature": f, "factors": factors, "results": results, "total": len(results)}


@router.post("/{feature_id}/push-asana")
def push_asana(feature_id: int, body: dict | None = None):
    body = body or {}
    f = get_feature(feature_id)
    factors = f["spec"].get("factors") or []
    bands = f["spec"].get("actions") or []
    if not factors:
        raise HTTPException(400, "This feature has no factors.")
    limit = int(body.get("limit") or 200)
    products = storage.list_products(limit=min(limit, 1000))
    results = [_score_product(p, factors) for p in products]
    tasks = []
    for r in results:
        band = next((b for b in bands if r["score"] >= int(b.get("min_score", 0)) and r["score"] < int(b.get("max_score", 101))), None)
        if not band:
            continue
        ctx = {"sku": r["sku"], "name": r["name"], "category": r["category"], "score": r["score"],
               "failed_factors": ", ".join(r["failed_factors"]) or "none"}
        name = _render(band.get("name_template", "Fix listing {sku}"), ctx)
        notes = _render(band.get("notes_template", ""), ctx)
        res = automation.execute_action(
            {"type": "asana_create_task", "target": band.get("project") or "Catalog Ops",
             "payload": {"name": name, "notes": notes}}, ctx={})
        tasks.append({"sku": r["sku"], "score": r["score"], **res})
    live = sum(1 for t in tasks if t.get("executed") == "live")
    return {"feature_id": feature_id, "tasks": tasks, "live": live, "total": len(tasks),
            "results": results}


@router.post("/{feature_id}/build")
def build(feature_id: int):
    """Generate a Bernie workflow diagram (canvas) + an automation from the feature."""
    f = get_feature(feature_id)
    spec = f["spec"]
    factors = spec.get("factors") or []
    bands = spec.get("actions") or []
    name = f["name"]
    ts = storage.now_iso()

    # --- workflow diagram (Bernie canvas) ---
    factor_lines = "\n".join(f"- {x['label']} ({x['type']} on {x['field']}, weight {x['weight']})" for x in factors)
    script = (
        "// Auto-generated scoring for: " + name + "\n"
        "const factors = " + json.dumps(factors) + ";\n"
        "return { score: 0, failed: factors.map(f => f.label) };"
    )
    nodes = [
        {"id": "n1", "type": "trigger", "data": {"label": name}, "x": 80, "y": 40},
        {"id": "n2", "type": "text", "data": {"text": "Factors:\n" + factor_lines}, "x": 80, "y": 170},
        {"id": "n3", "type": "script", "data": {"script": script}, "x": 80, "y": 300},
        {"id": "n4", "type": "custom", "data": {"label": "Asana tasks (" + str(len(bands)) + " bands)"}, "x": 80, "y": 430},
        {"id": "n5", "type": "flush", "data": {}, "x": 80, "y": 560},
    ]
    edges = [
        {"source": "n1", "target": "n2"}, {"source": "n2", "target": "n3"},
        {"source": "n3", "target": "n4"}, {"source": "n4", "target": "n5"},
    ]
    cur = storage._conn().execute(
        "INSERT INTO bernie_canvases (name, nodes, edges, created_at, updated_at) VALUES (?,?,?,?,?)",
        (name + " — workflow", json.dumps(nodes), json.dumps(edges), ts, ts),
    )
    storage._conn().commit()
    canvas_id = cur.lastrowid

    # --- automation ---
    actions = []
    for b in bands:
        actions.append({
            "type": "asana_create_task", "target": b.get("project") or "Catalog Ops",
            "payload": {"name": b.get("name_template", "Fix listing {sku}"),
                        "notes": b.get("notes_template", "")},
        })
    actions.append({"type": "log_event"})
    cur2 = storage._conn().execute(
        "INSERT INTO automations (name, description, trigger_source, trigger_event, conditions, actions, enabled, created_at) "
        "VALUES (?,?,?,?,?,?,0,?)",
        (name + " (auto)", f"Auto-generated from feature '{name}'. Runs the listing-quality scoring and pushes banded results to Asana.",
         "manual", "feature_run:" + re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_"),
         json.dumps([]), json.dumps(actions), ts),
    )
    storage._conn().commit()
    automation_id = cur2.lastrowid
    return {"canvas_id": canvas_id, "automation_id": automation_id, "factors": len(factors), "actions": len(bands)}
