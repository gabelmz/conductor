"""Preset Agent Gallery — agents derived from the user's real workspace artifacts.

Sources:
  * Eternal buckets  — every `.eb-frontmatter.yaml` directory index (tags/depth/files)
  * Mempalace        — mempalace.yaml room definitions
  * Obsidian tasks   — Daily Triage notes, products/action SKILL.md, vault agent defs
  * Vault agents     — lux-reports agent definitions (catalog_scoring, etc.)

Each agent has a "quick action": a runnable probe that reads the real
artifact and returns a structured report, so the gallery is not just
decorative — launching an agent actually does something.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

DEV_ROOT = Path(os.environ.get("PARKER_DEV_ROOT", r"C:\Users\GabeMaher\Documents\Development"))


# --------------------------------------------------------------------------
# Artifact scanners
# --------------------------------------------------------------------------
def _safe_walk(root: Path):
    """os.walk with broken-symlink tolerance (Windows node_modules/.git junctions)."""
    for dirpath, dirnames, filenames in os.walk(root, onerror=lambda e: None):
        dirnames[:] = [d for d in dirnames if d not in ("node_modules", ".git", ".venv")]
        yield Path(dirpath), filenames


def scan_eternal_buckets(root: Path = DEV_ROOT) -> list[dict]:
    """Read every .eb-frontmatter.yaml in the tree (bounded)."""
    buckets = []
    count = 0
    for dirpath, filenames in _safe_walk(root):
        if ".eb-frontmatter.yaml" in filenames:
            path = dirpath / ".eb-frontmatter.yaml"
            try:
                txt = path.read_text(encoding="utf-8", errors="replace")
                data = {"path": str(path.relative_to(root)).replace("\\", "/")}
                for line in txt.splitlines():
                    line = line.strip()
                    if line.startswith("name:"):
                        data["name"] = line.split(":", 1)[1].strip().strip('"')
                    elif line.startswith("depth:"):
                        data["depth"] = line.split(":", 1)[1].strip()
                    elif line.startswith("subdirs:"):
                        data["subdirs"] = line.split(":", 1)[1].strip()
                    elif line.startswith("files:"):
                        data["files"] = line.split(":", 1)[1].strip()
                    elif line.startswith("tags:") and "tags" not in data:
                        data["tags"] = []
                # tags are the lines after 'tags:'
                in_tags = False
                for line in txt.splitlines():
                    s = line.strip()
                    if s == "tags:":
                        in_tags = True
                        continue
                    if in_tags:
                        if s.startswith("- "):
                            data.setdefault("tags", []).append(s[2:].strip())
                        else:
                            in_tags = False
                buckets.append(data)
                count += 1
                if count >= 400:
                    return buckets
            except Exception:
                continue
    return buckets


def load_mempalace(root: Path = DEV_ROOT) -> dict | None:
    for candidate in (root / "mempalace.yaml", root / "mempalace.yml"):
        if candidate.exists():
            try:
                txt = candidate.read_text(encoding="utf-8", errors="replace")
                return {"path": str(candidate.relative_to(root)), "raw": txt[:4000]}
            except Exception:
                return None
    return None


def parse_mempalace_rooms(raw: str) -> list[dict]:
    rooms = []
    current = None
    for line in raw.splitlines():
        s = line.strip()
        if s.startswith("rooms:") or s.startswith("- name:"):
            if current and current.get("name"):
                rooms.append(current)
            if s.startswith("- name:"):
                current = {"name": s.split(":", 1)[1].strip()}
            else:
                current = None
        elif current is not None and s.startswith("description:"):
            current["description"] = s.split(":", 1)[1].strip()
        elif current is not None and s.startswith("keywords:"):
            current["keywords"] = []
        elif current is not None and "keywords" in current and s.startswith("- "):
            current["keywords"].append(s[2:].strip().strip('"'))
    if current and current.get("name"):
        rooms.append(current)
    return rooms


def scan_obsidian_tasks(root: Path = DEV_ROOT) -> list[dict]:
    """Find daily triage notes and extract P0/P1 task lines with correct section tracking."""
    base = root / "Vaults" / "luminize-vault"
    triage_dir = base / "Daily" / "Daily Triage"
    files = []
    if triage_dir.exists():
        files = sorted(triage_dir.glob("*.md"))
    daily = base / "Daily"
    if daily.exists():
        files += [p for p in daily.glob("*.md") if "triage" in p.name.lower() or "priority" in p.name.lower()]
    files = sorted(set(files))[-8:]
    tasks = []
    for path in files:
        try:
            txt = path.read_text(encoding="utf-8", errors="replace")
            current_priority = "P2"
            lines = txt.splitlines()
            for i, line in enumerate(lines):
                s = line.strip()
                if re.search(r"\*\*P0\*\*|^#+.*\bP0\b|^P0\b", s, re.I):
                    current_priority = "P0"
                    continue
                if re.search(r"\*\*P1\*\*|^#+.*\bP1\b|^P1\b", s, re.I):
                    current_priority = "P1"
                    continue
                if re.search(r"\*\*P2\*\*|^#+.*\bP2\b|^P2\b", s, re.I):
                    current_priority = "P2"
                    continue
                if re.match(r"^[-*]\s*\[", s):
                    tasks.append({
                        "source": str(path.relative_to(root)).replace("\\", "/"),
                        "task": s[:300],
                        "priority": current_priority,
                    })
        except Exception:
            continue
    return tasks


def scan_vault_agents(root: Path = DEV_ROOT) -> list[dict]:
    """Discover agent definitions in the vault (agents/*.md with Role sections)."""
    base = root / "Vaults" / "luminize-vault"
    agents = []
    for dirpath, filenames in _safe_walk(base):
        if dirpath.name != "agents":
            continue
        for fn in filenames:
            if not (fn.endswith(".md") and (fn.startswith("agent") or fn.startswith("AGENT") or fn.endswith("_agent.md"))):
                continue
            path = dirpath / fn
            try:
                txt = path.read_text(encoding="utf-8", errors="replace")
                role = ""
                m = re.search(r"## Role\s*\n\s*(.+)", txt)
                if m:
                    role = m.group(1).strip()[:200]
                agents.append({
                    "name": path.stem,
                    "path": str(path.relative_to(root)).replace("\\", "/"),
                    "role": role,
                })
            except Exception:
                continue
    return agents


def scan_compliance_products() -> list[dict]:
    """Products already in the compliance DB (for the Compliance agent quick action)."""
    try:
        import storage
        return storage.list_products(100)
    except Exception:
        return []


def scan_bucket_tree(root: Path = DEV_ROOT, max_depth: int = 3) -> list[dict]:
    """Deep-dive the eternal bucket index grouped by depth and tag."""
    buckets = scan_eternal_buckets(root)
    by_depth: dict[str, int] = {}
    tag_rows: dict[str, int] = {}
    for b in buckets:
        d = b.get("depth", "?")
        by_depth[d] = by_depth.get(d, 0) + 1
        for t in b.get("tags", []):
            tag_rows[t] = tag_rows.get(t, 0) + 1
    return {
        "total": len(buckets),
        "by_depth": sorted(by_depth.items(), key=lambda kv: kv[0]),
        "top_tags": sorted(tag_rows.items(), key=lambda kv: -kv[1])[:15],
    }


def scan_vault_structure(root: Path = DEV_ROOT) -> list[dict]:
    """Map the Obsidian vault top-level + key subdirs."""
    base = root / "Vaults" / "luminize-vault"
    out = []
    if not base.exists():
        return out
    for child in sorted(base.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        n_md = 0
        n_sub = 0
        for dirpath, filenames in _safe_walk(child):
            n_md += sum(1 for fn in filenames if fn.endswith(".md"))
            n_sub += 1
        out.append({"name": child.name, "subdirs": max(n_sub - 1, 0), "notes": n_md})
    return out


# --------------------------------------------------------------------------
# Agent definitions
# --------------------------------------------------------------------------
AGENT_DEFS = [
    {
        "id": "kpi-architect",
        "name": "NLP to KPI Architect",
        "tagline": "Convert prompts to KPI metrics & math formulas",
        "description": "Translates natural language requests into structured KPI definitions, target thresholds, and calculation rules. Integrates with the KPI Studio and DataWrangler.",
        "color": "#8b5cf6",
        "icon": "zap",
        "source": "kpi: nlp_engine",
        "tools": ["nlp-parser", "kpi-builder", "formula-engine"],
        "quick_action": "kpi_architect",
        "prompt_hint": "Create a metric for internal SLA target 95% for Gabe",
    },
    {
        "id": "performance-evaluator",
        "name": "Employee Performance Evaluator",
        "tagline": "Scorecards, % to goal & employee reviews",
        "description": "Evaluates employee metrics across departments (Catalog, Cases, OmniChannel, FBA), calculates % to goal, and generates AI performance review reports.",
        "color": "#ec4899",
        "icon": "graph",
        "source": "kpi: global_kpis.xlsx",
        "tools": ["scorecard-evaluator", "performance-report", "goal-tracker"],
        "quick_action": "performance_evaluator",
        "prompt_hint": "Generate employee performance review for Gabe",
    },
    {
        "id": "asana-kpi-harvester",
        "name": "Asana KPI Harvester",
        "tagline": "Derive KPIs from Asana tasks & sync data",
        "description": "Connects local Asana task sync data (overdue ratios, task completion counts, cycle times) to employee KPI metrics.",
        "color": "#10b981",
        "icon": "checklist",
        "source": "asana: sync_engine",
        "tools": ["asana-query", "cycle-time-calc", "overdue-aggregator"],
        "quick_action": "asana_kpi_harvester",
        "prompt_hint": "Harvest task completion rate & overdue % from Asana",
    },
    {
        "id": "parker",
        "name": "Parker",
        "tagline": "EU/US/UK product compliance checks",
        "description": "Evaluates products against CE, FCC, RoHS, REACH, GPSR, Prop 65, CPSIA, UKCA, Battery, Textile, Food Contact and Cosmetics regulations. Drop a catalog file (Keepa export, CDQ report, CSV) and it scores every ASIN with evidence requirements.",
        "color": "#0053FD",
        "icon": "shield",
        "source": "built-in",
        "tools": ["ingest", "rules-engine", "http-api", "webhook"],
        "quick_action": "products",
        "prompt_hint": "Drop a catalog file or paste product JSON to run a compliance sweep.",
    },
    {
        "id": "keepa-intel",
        "name": "Keepa Intelligence",
        "tagline": "Sales rank, price and signal triage",
        "description": "Orchestrates Keepa product data into prioritized actions: assess sales-rank/price signals, classify severity, build action plans. Modeled on the keepa-to-asana agent: assess → process → push → learn.",
        "color": "#6F9BA6",
        "icon": "trend",
        "source": "vault: keepa-to-asana",
        "tools": ["keepa-export", "signal-scoring", "asana-push"],
        "quick_action": "keepa",
        "prompt_hint": "Paste a Keepa export path or ASIN list to triage signals.",
    },
    {
        "id": "cdq-triage",
        "name": "CDQ Triage",
        "tagline": "Catalog quality defect review",
        "description": "Reads CDQ (Catalog Data Quality) reports — grades, policy compliance, defects — and surfaces the worst offenders by priority. Derived from the CDQ_Report.xlsx pipeline and task_review_agent.",
        "color": "#C9A24B",
        "icon": "filter",
        "source": "catalog: CDQ_Report.xlsx",
        "tools": ["cdq-report", "grade-scoring", "defect-queue"],
        "quick_action": "cdq",
        "prompt_hint": "Point me at a CDQ_Report.xlsx to triage grades and defects.",
    },
    {
        "id": "bucket-scout",
        "name": "Eternal Bucket Scout",
        "tagline": "Map the workspace via eb-frontmatter",
        "description": "Reads every .eb-frontmatter.yaml directory index — tags, depth, subdirs, file counts — to map the eternal buckets that organise the workspace. Use it to find where data lives.",
        "color": "#55A583",
        "icon": "map",
        "source": "eternal buckets (.eb-frontmatter.yaml)",
        "tools": ["bucket-index", "tag-search"],
        "quick_action": "buckets",
        "prompt_hint": "Scan the workspace and show me the eternal bucket map.",
    },
    {
        "id": "mempalace",
        "name": "Mempalace Librarian",
        "tagline": "Rooms, keywords and memory retrieval",
        "description": "Navigates mempalace.yaml rooms — named memory buckets with keyword routing — to find where past knowledge and files live, and which room a new artifact should be filed into.",
        "color": "#9E94D5",
        "icon": "vault",
        "source": "mempalace.yaml",
        "tools": ["room-index", "keyword-routing"],
        "quick_action": "mempalace",
        "prompt_hint": "List the mempalace rooms and their keywords.",
    },
    {
        "id": "obsidian-tasks",
        "name": "Obsidian Task Triager",
        "tagline": "P0/P1 triage from Daily notes",
        "description": "Extracts actionable tasks from Daily Triage notes, classifies by priority bucket, and groups by owner/channel. Mirrors task_review_agent's Eisenhower-style triage flow.",
        "color": "#DB704B",
        "icon": "checklist",
        "source": "vault: Daily Triage",
        "tools": ["triage-parse", "priority-classify"],
        "quick_action": "tasks",
        "prompt_hint": "Show me today's P0 triage items from the vault.",
    },
    {
        "id": "catalog-scoring",
        "name": "Catalog Scoring",
        "tagline": "Keepa completeness scoring sheets",
        "description": "Builds and validates catalog completeness scoring sheets from Keepa exports — maps keepa_label values to export headers, builds scoring rows and first-column formulas. Cloned from the lux-reports catalog_scoring_agent.",
        "color": "#1540B1",
        "icon": "table",
        "source": "vault: lux-reports/agents",
        "tools": ["keepa-map", "scoring-formulas", "google-sheets"],
        "quick_action": "vault_agents",
        "prompt_hint": "Score a catalog export for completeness.",
    },
    {
        "id": "spreadsheet-quality",
        "name": "Spreadsheet Quality",
        "tagline": "Clean, normalise, format tables",
        "description": "Cleans and normalises spreadsheet data in place: duplicate detection, type cleanup, visual formatting. Cloned from the lux-reports spreadsheet_quality_agent.",
        "color": "#1F8A65",
        "icon": "sparkle",
        "source": "vault: lux-reports/agents",
        "tools": ["dupe-scan", "type-cleanup", "format"],
        "quick_action": "vault_agents",
        "prompt_hint": "Clean and format a messy export.",
    },
    {
        "id": "report-ingestion",
        "name": "Report Ingestion",
        "tagline": "CSV/TSV/XLSX → Obsidian notes",
        "description": "Converts tabular report exports into Obsidian markdown notes, one note per row. Cloned from the lux-reports report_ingestion_agent.",
        "color": "#4C7F8C",
        "icon": "import",
        "source": "vault: lux-reports/agents",
        "tools": ["csv-parse", "markdown-split", "obsidian-vault"],
        "quick_action": "vault_agents",
        "prompt_hint": "Ingest this report into the vault as markdown.",
    },
    {
        "id": "bucket-navigator",
        "name": "Bucket Navigator",
        "tagline": "Eternal bucket tree by depth & tag",
        "description": "Deep-dives the .eb-frontmatter index: bucket counts per depth, top tags, and where data actually lives. Use it to find which bucket holds a given tag or file type.",
        "color": "#3E8E7E",
        "icon": "tree",
        "source": "eternal buckets (.eb-frontmatter.yaml)",
        "tools": ["bucket-index", "depth-map", "tag-search"],
        "quick_action": "bucket_tree",
        "prompt_hint": "Map the bucket tree — depth counts and top tags.",
    },
    {
        "id": "room-router",
        "name": "Room Router",
        "tagline": "Route artifacts to the right mempalace room",
        "description": "Uses mempalace.yaml keyword routing to decide which room a new artifact, note, or project should be filed into — and which rooms already hold related knowledge.",
        "color": "#8B80E8",
        "icon": "route",
        "source": "mempalace.yaml",
        "tools": ["room-index", "keyword-routing"],
        "quick_action": "mempalace",
        "prompt_hint": "Where should this artifact live? Show the room keywords.",
    },
    {
        "id": "vault-indexer",
        "name": "Vault Indexer",
        "tagline": "Map the Obsidian vault structure",
        "description": "Maps the luminize-vault: top-level folders, subdirectory counts, and note density — so you know where products, ops, AI components, and daily notes live.",
        "color": "#C0843A",
        "icon": "vault",
        "source": "obsidian: luminize-vault",
        "tools": ["vault-map", "note-count", "folder-index"],
        "quick_action": "vault_structure",
        "prompt_hint": "Show me the vault structure and note density.",
    },
]


def run_quick_action(agent_id: str) -> dict:
    """Execute the agent's quick action against real artifacts."""
    # Resolve the agent def to its quick_action key (agent ids may differ)
    action = agent_id
    for a in AGENT_DEFS:
        if a["id"] == agent_id:
            action = a.get("quick_action", agent_id)
            break
    if action == "kpi_architect":
        from kpi import list_kpis
        kpis = list_kpis()
        return {
            "title": "NLP to KPI Architect — Active Metrics",
            "summary": f"{len(kpis)} active KPI metrics defined in storage.",
            "rows": [{"department": k["department"], "owner": k["owner"], "kpi": k["kpi_name"], "target": f"{k.get('expected_value') or 'N/A'} {k.get('metric_type') or ''}"} for k in kpis[:20]],
        }
    if action == "performance_evaluator":
        from kpi import evaluate_employees
        ev = evaluate_employees()
        scorecards = ev.get("scorecards", [])
        return {
            "title": "Employee Performance Evaluator — Scorecards",
            "summary": f"Evaluated performance scorecards across {len(scorecards)} employee owners.",
            "rows": [{"owner": s["owner"], "rating": s["performance_rating"], "score": f"{s['composite_score']}%", "kpis": s["total_kpis"]} for s in scorecards],
        }
    if action == "asana_kpi_harvester":
        import storage
        counts = storage.asana_counts()
        tasks = storage.list_asana_tasks(limit=10)
        return {
            "title": "Asana KPI Harvester — Sync Pipeline",
            "summary": f"{counts.get('tasks', 0)} Asana tasks synced ({counts.get('open', 0)} open, {counts.get('overdue', 0)} overdue).",
            "rows": [{"task": t["name"], "assignee": t.get("assignee_name") or "—", "due": t.get("due_on") or "—"} for t in tasks],
        }
    if action in ("parker", "products"):
        products = scan_compliance_products()
        return {
            "title": "Parker — product sweep",
            "summary": f"{len(products)} products evaluated in the compliance store.",
            "rows": [{"sku": p["sku"], "name": p["name"][:60], "category": p["category"], "market": p["market"]} for p in products[:20]],
        }
    if action == "keepa":
        keepa_files = []
        for dirpath, filenames in _safe_walk(DEV_ROOT):
            for fn in filenames:
                if fn.lower().endswith(".xlsx") and "keepa" in fn.lower():
                    keepa_files.append(str((dirpath / fn).relative_to(DEV_ROOT)))
        return {
            "title": "Keepa Intelligence — data sources",
            "summary": f"Found {len(keepa_files)} Keepa export(s) in the workspace.",
            "rows": [{"path": p} for p in keepa_files[:15]],
        }
    if action == "cdq":
        cdq_files = []
        for dirpath, filenames in _safe_walk(DEV_ROOT):
            for fn in filenames:
                if fn.lower() == "cdq_report.xlsx":
                    cdq_files.append(str((dirpath / fn).relative_to(DEV_ROOT)))
        return {
            "title": "CDQ Triage — report inventory",
            "summary": f"Found {len(cdq_files)} CDQ report(s). Drop one into the composer to triage grades.",
            "rows": [{"path": p} for p in cdq_files[:15]],
        }
    if action == "buckets":
        buckets = scan_eternal_buckets()
        tags = {}
        for b in buckets:
            for t in b.get("tags", []):
                tags[t] = tags.get(t, 0) + 1
        top = sorted(tags.items(), key=lambda kv: -kv[1])[:12]
        return {
            "title": "Eternal Bucket Scout — workspace map",
            "summary": f"{len(buckets)} eternal buckets indexed (tag counts below).",
            "rows": [{"tag": k, "count": v} for k, v in top],
            "buckets": buckets[:25],
        }
    if action == "bucket_tree":
        tree = scan_bucket_tree()
        rows = [{"depth": d, "buckets": n} for d, n in tree["by_depth"]] + \
               [{"depth": f"tag:{t}", "buckets": n} for t, n in tree["top_tags"]]
        return {
            "title": "Bucket Navigator — eternal bucket tree",
            "summary": f"{tree['total']} buckets indexed · depth distribution + top tags.",
            "rows": rows[:30],
        }
    if action == "vault_structure":
        structure = scan_vault_structure()
        return {
            "title": "Vault Indexer — luminize-vault map",
            "summary": f"{len(structure)} top-level folders mapped (subdirs · markdown notes).",
            "rows": [{"folder": s["name"], "subdirs": s["subdirs"], "notes": s["notes"]} for s in structure[:25]],
        }
    if action == "mempalace":
        mp = load_mempalace()
        if not mp:
            return {"title": "Mempalace", "summary": "No mempalace.yaml found.", "rows": []}
        rooms = parse_mempalace_rooms(mp["raw"])
        return {
            "title": "Mempalace Librarian — rooms",
            "summary": f"{len(rooms)} rooms defined in {mp['path']}.",
            "rows": [{"room": r.get("name", ""), "description": r.get("description", "")[:80], "keywords": ", ".join(r.get("keywords", [])[:4])} for r in rooms],
        }
    if action in ("obsidian-tasks", "tasks"):
        tasks = scan_obsidian_tasks()
        p0 = sum(1 for t in tasks if t["priority"] == "P0")
        p1 = sum(1 for t in tasks if t["priority"] == "P1")
        # Also import into the action queue so tasks become actionable in-app
        try:
            import storage as _storage
            inserted = _storage.import_tasks(tasks)
            queue_total = len(_storage.list_tasks())
        except Exception:
            inserted, queue_total = 0, 0
        return {
            "title": "Obsidian Task Triager — recent triage",
            "summary": f"{len(tasks)} tasks extracted · {p0} P0 · {p1} P1 · {inserted} added to Action Queue ({queue_total} total).",
            "rows": [{"priority": t["priority"], "task": t["task"][:110]} for t in tasks[:25]],
        }
    if action in ("vault_agents", "catalog-scoring", "spreadsheet-quality", "report-ingestion"):
        agents = scan_vault_agents()
        return {
            "title": "Vault Agents — discovery",
            "summary": f"{len(agents)} agent definitions found in the vault.",
            "rows": [{"name": a["name"], "role": a["role"][:80], "path": a["path"]} for a in agents[:20]],
        }
    return {"title": agent_id, "summary": "No quick action.", "rows": []}


def list_agents() -> list[dict]:
    return AGENT_DEFS
