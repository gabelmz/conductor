"""Parker — Asana sync engine.

Pulls ALL of Asana (workspaces, users, teams, projects, custom fields,
tasks + custom fields, stories/comments, subtasks, attachments) into the
local SQLite store, using API patterns discovered from the Luminize Asana
sync scripts (Code.gs / asana-testing-04, sync_asana.py, .odc Power Query
connections):

  - Workspace GID      : 1161027935621444  (discovered, auto-detect fallback)
  - Portfolio GID      : 1210875219129229  (used when project_source=portfolio)
  - PAT identity       : 2/1205116828574744/1214636016249478:... (owner GID
                        1205116828574744 = Gabe; secret tail is stored in
                        Apps Script Properties / Power Query, not on disk)
  - Task opt_fields    : from Code.gs TASK_OPT_FIELDS (v4 catalog sync)
  - Weight rule        : /keepa/i tasks count 0.3, everything else 1.0

Credentials live in data/asana.json (alongside chat.json / compliance.db),
with ASANA_PAT env var as an override — so the installed desktop app works
without env vars.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Callable

from storage import DATA_DIR, now_iso

BASE_URL = "https://app.asana.com/api/1.0"

# --- Discovered defaults -----------------------------------------------------
DEFAULT_WORKSPACE_GID = "1161027935621444"
DEFAULT_PORTFOLIO_GID = "1210875219129229"

CONFIG_PATH = DATA_DIR / "asana.json"

BATCH_SIZE = 100
MAX_RETRIES = 5
RATE_LIMIT_MS = 0.45  # discovered pacing between project fetches

# --- Task opt_fields (discovered from Code.gs v4 TASK_OPT_FIELDS) ------------
TASK_OPT_FIELDS = (
    "gid,name,resource_type,created_at,completed_at,modified_at,completed,"
    "assignee.gid,assignee.name,assignee.email,due_on,start_on,notes,permalink_url,"
    "tags.name,followers.name,followers.email,parent.gid,parent.name,"
    "memberships.project.gid,memberships.project.name,memberships.section.name,"
    "dependencies.gid,dependents.gid,num_subtasks,"
    "custom_fields.gid,custom_fields.name,custom_fields.resource_subtype,"
    "custom_fields.display_value,custom_fields.enum_value.name,"
    "custom_fields.multi_enum_values.name,custom_fields.number_value,"
    "custom_fields.text_value,custom_fields.date_value.date,"
    "attachments.gid,attachments.name,attachments.host,"
    "attachments.download_url,attachments.view_url,attachments.permanent_url,"
    "attachments.created_at"
)

PROJECT_OPT_FIELDS = (
    "gid,name,archived,color,notes,created_at,modified_at,permalink_url,"
    "team.gid,team.name"
)

# --- Config ----------------------------------------------------------------
def _load_config() -> dict:
    cfg = {}
    if CONFIG_PATH.exists():
        try:
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            cfg = {}
    pat = cfg.get("pat") or os.environ.get("ASANA_PAT", "")
    pats = cfg.get("pats") or ([pat] if pat else [])
    pats = [p for p in pats if p]
    return {
        "pat": pat,
        "pats": pats,
        "workspace_gid": cfg.get("workspace_gid") or DEFAULT_WORKSPACE_GID,
        "portfolio_gid": cfg.get("portfolio_gid") or DEFAULT_PORTFOLIO_GID,
        "project_source": cfg.get("project_source") or "workspace",
        "last_sync": cfg.get("last_sync") or "",
    }


def _save_config(cfg: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def get_config() -> dict:
    cfg = _load_config()
    pat = cfg.get("pat") or ""
    pats = cfg.get("pats") or []
    return {
        "has_pat": bool(pat),
        "pat_masked": f"****{pat[-4:]}" if pat else "",
        "num_pats": len(pats),
        "workspace_gid": cfg.get("workspace_gid") or "",
        "portfolio_gid": cfg.get("portfolio_gid") or "",
        "project_source": cfg.get("project_source") or "workspace",
        "last_sync": cfg.get("last_sync") or "",
    }


def save_config(**kwargs) -> dict:
    cfg = _load_config()
    for k in ("pat", "workspace_gid", "portfolio_gid", "project_source"):
        if k in kwargs and kwargs[k] is not None:
            cfg[k] = str(kwargs[k]).strip()
    if "pat" in kwargs and kwargs["pat"]:
        # Keep primary PAT + any additional tokens in the rotation.
        new_pat = str(kwargs["pat"]).strip()
        pats = [p for p in (cfg.get("pats") or []) if p]
        if new_pat not in pats:
            pats.append(new_pat)
        cfg["pats"] = pats
    _save_config(cfg)
    return get_config()


def has_credentials() -> bool:
    return bool(_load_config().get("pats"))


# --- API client (multi-PAT round-robin + rate limiter) ----------------------
import threading

_req_lock = threading.Lock()
_req_count = 0
_last_use: list[float] = []
MIN_INTERVAL_S = 0.45  # ~2.2 req/s per token (Asana limit is 150/min = 2.5/s)


def _headers() -> dict:
    """Next PAT in the rotation, pacing per-token so we never trip 429s."""
    global _req_count, _last_use
    cfg = _load_config()
    pats = cfg.get("pats") or []
    if not pats:
        raise RuntimeError("Asana PAT not configured — add it in Settings → Asana (or set ASANA_PAT).")
    with _req_lock:
        if len(_last_use) != len(pats):
            _last_use = [0.0] * len(pats)
        idx = _req_count % len(pats)
        _req_count += 1
        now = time.monotonic()
        wait = MIN_INTERVAL_S - (now - _last_use[idx])
        if wait > 0:
            time.sleep(wait)
        _last_use[idx] = time.monotonic()
    return {"Authorization": f"Bearer {pats[idx]}", "Accept": "application/json"}


def api_get(headers: dict, path: str, params: dict | None = None) -> dict:
    """GET with 429/5xx retry — mirrors asanaGet() from the Apps Script."""
    url = f"{BASE_URL}{path}" if path.startswith("/") else path
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    for attempt in range(1, MAX_RETRIES + 1):
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                retry_after = int(e.headers.get("Retry-After", "5"))
                time.sleep(retry_after + attempt)
                continue
            if e.code >= 500:
                time.sleep(2 * attempt)
                continue
            body = e.read(300).decode("utf-8", errors="replace")
            raise RuntimeError(f"Asana API {e.code}: {body}")
        except urllib.error.URLError as e:
            time.sleep(2 * attempt)
            if attempt == MAX_RETRIES:
                raise RuntimeError(f"Asana API unreachable: {e}")
    raise RuntimeError(f"Exceeded {MAX_RETRIES} retries on 429/5xx for {url}")


def paginate(headers: dict, path: str, params: dict | None = None) -> list[dict]:
    """Paginate an Asana list endpoint (offset tokens), returning all items."""
    items: list[dict] = []
    p: dict = {"limit": BATCH_SIZE}
    if params:
        p.update(params)
    while True:
        data = api_get(headers, path, p)
        items.extend(data.get("data", []) or [])
        nxt = data.get("next_page") or {}
        if nxt.get("offset"):
            p["offset"] = nxt["offset"]
        else:
            break
    return items


# --- Weight rule (discovered: keepa tasks count 0.3) -------------------------
_KEEPA_RE = re.compile(r"keepa", re.IGNORECASE)


def task_weight(name: str) -> float:
    return 0.3 if _KEEPA_RE.search(name or "") else 1.0


def _cf_display(cf: dict) -> str:
    """Best display value for a custom field — mirrors taskCustomFieldMap()."""
    v = (
        cf.get("display_value")
        or (cf.get("enum_value") or {}).get("name")
        or ", ".join(x.get("name", "") for x in (cf.get("multi_enum_values") or []) if x.get("name"))
        or cf.get("text_value")
        or (str(cf["number_value"]) if cf.get("number_value") is not None else None)
        or (cf.get("date_value") or {}).get("date")
    )
    return v or ""


def _first_membership(task: dict) -> tuple[dict, dict]:
    """Return (primary membership, list of all memberships)."""
    memberships = task.get("memberships") or []
    primary = memberships[0] if memberships else {}
    return primary, memberships


# --- Sync orchestration ------------------------------------------------------
def sync_all(mode: str = "all", deep: bool = False,
             progress: Callable[[float, str], None] | None = None) -> dict:
    """Pull everything from Asana into SQLite.

    mode: 'all' (full refresh) | 'delta' (modified_since only).
    deep: also fetch stories/attachments/subtasks per task. For big orgs
    (e.g. 266k tasks) leave False — task details hydrate on demand when a
    task is opened.
    """
    import storage

    cfg = _load_config()
    headers = _headers()
    started = now_iso()
    counts = {"projects": 0, "tasks": 0, "stories": 0, "subtasks": 0,
              "attachments": 0, "users": 0, "teams": 0, "custom_fields": 0,
              "workspaces": 0}

    def report(pct: float, msg: str) -> None:
        if progress:
            progress(pct, msg)

    # 1) Workspaces
    report(1, "Fetching workspaces…")
    workspaces = paginate(headers, "/workspaces")
    for w in workspaces:
        storage.upsert_asana_workspace(gid=w["gid"], name=w.get("name", ""))
    counts["workspaces"] = len(workspaces)
    ws_gid = cfg.get("workspace_gid") or (workspaces[0]["gid"] if workspaces else "")
    if not ws_gid:
        raise RuntimeError("No Asana workspace found — set workspace_gid in Settings → Asana.")

    # 2) Users
    report(4, "Fetching users…")
    users = paginate(headers, f"/workspaces/{ws_gid}/users", {"opt_fields": "name,email"})
    for u in users:
        storage.upsert_asana_user(gid=u["gid"], name=u.get("name", ""), email=u.get("email", ""))
    counts["users"] = len(users)

    # 3) Teams (org endpoint, fallback derived from projects)
    report(6, "Fetching teams…")
    try:
        teams = paginate(headers, f"/organizations/{ws_gid}/teams",
                         {"opt_fields": "name,description"})
    except RuntimeError:
        teams = []
    for t in teams:
        storage.upsert_asana_team(gid=t["gid"], name=t.get("name", ""),
                                  description=t.get("description", ""))
    counts["teams"] = len(teams)

    # 4) Projects (workspace or portfolio source)
    report(8, "Fetching projects…")
    if cfg.get("project_source") == "portfolio":
        proj_gid = cfg.get("portfolio_gid") or DEFAULT_PORTFOLIO_GID
        projects = paginate(headers, f"/portfolios/{proj_gid}/items",
                            {"opt_fields": PROJECT_OPT_FIELDS})
    else:
        projects = paginate(headers, "/projects",
                            {"workspace": ws_gid, "opt_fields": PROJECT_OPT_FIELDS})
    active_projects = [p for p in projects if not p.get("archived")]
    for p in projects:
        team = p.get("team") or {}
        storage.upsert_asana_project(
            gid=p["gid"], name=p.get("name", ""), team_gid=team.get("gid", ""),
            team_name=team.get("name", ""), archived=1 if p.get("archived") else 0,
            color=p.get("color", ""), notes=p.get("notes", ""),
            created_at=p.get("created_at", ""), modified_at=p.get("modified_at", ""),
            permalink=p.get("permalink_url", ""),
        )
    counts["projects"] = len(projects)

    # 5) Custom field definitions — only in deep mode (bounded sample).
    #    Task rows already carry custom_fields name/value, so the catalog is
    #    a convenience; per-project settings = 1 call × every project, which
    #    is expensive in a 2,500-project workspace.
    report(10, "Fetching custom field definitions…")
    cf_seen: set[str] = set()
    if deep:
        for p in active_projects[:500]:
            try:
                settings = paginate(headers, f"/projects/{p['gid']}/custom_field_settings",
                                    {"opt_fields": "custom_field.gid,custom_field.name,"
                                                    "custom_field.resource_subtype,"
                                                    "custom_field.description,"
                                                    "custom_field.enum_options.name"})
            except RuntimeError:
                continue
            for s in settings:
                cf = s.get("custom_field") or {}
                gid = cf.get("gid")
                if not gid or gid in cf_seen:
                    continue
                cf_seen.add(gid)
                storage.upsert_asana_custom_field(
                    gid=gid, name=cf.get("name", ""),
                    type=cf.get("resource_subtype", ""),
                    description=cf.get("description", ""),
                    enum_options=[e.get("name", "") for e in (cf.get("enum_options") or [])],
                )
    counts["custom_fields"] = len(cf_seen)

    # 6) Tasks. 'all' = per-project full scan. 'delta' = workspace search over
    #    tasks changed since last sync. 'recent' = last 7 days. The windowed
    #    modes also pull stories/attachments/subtasks (bounded result set).
    proj_map = {p["gid"]: p for p in projects}
    fetched = 0
    window = None
    if mode == "recent":
        window = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    elif mode == "delta" and cfg.get("last_sync"):
        window = cfg["last_sync"]
    elif mode == "delta":
        window = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    if window:
        report(12, f"Fetching tasks changed since {window[:10]} — workspace search…")
        params_base: dict = {"opt_fields": TASK_OPT_FIELDS, "modified_since": window}
        for completed_flag in ("false", "true"):
            params = dict(params_base, completed=completed_flag)
            for task in paginate(headers, f"/workspaces/{ws_gid}/tasks/search", params):
                _store_task(storage, headers, task, proj_map, deep=True)
                fetched += 1
                counts["tasks"] += 1
    else:
        total_projects = max(len(active_projects), 1)
        report(12, f"Fetching tasks — {len(active_projects)} projects…")
        for idx, proj in enumerate(active_projects):
            params: dict = {"project": proj["gid"], "opt_fields": TASK_OPT_FIELDS}
            for task in paginate(headers, "/tasks", params):
                _store_task(storage, headers, task, proj_map, deep=deep)
                fetched += 1
                counts["tasks"] += 1
            if (idx + 1) % 25 == 0 or idx == total_projects - 1:
                report(min(95.0, 12 + (idx + 1) / total_projects * 83),
                       f"Fetching tasks — {idx + 1}/{len(active_projects)} projects, {fetched} tasks…")

    # 7) Done — record run + bump last_sync (report stored totals)
    final = storage.asana_counts()
    for k in ("projects", "tasks", "stories", "attachments", "subtasks",
              "users", "teams", "custom_fields"):
        if k in final:
            counts[k] = final[k]
    finished = now_iso()
    _save_config({**cfg, "last_sync": finished})
    storage.record_asana_run(mode=mode, status="done", started_at=started,
                             finished_at=finished, counts=counts, error="")
    report(100, f"Done — {counts['tasks']} tasks, {counts['stories']} comments, "
                f"{counts['attachments']} attachments, {counts['subtasks']} subtasks.")
    return counts


def _store_task(storage, headers: dict, task: dict, proj_map: dict,
                deep: bool = False) -> None:
    """Upsert one task; when deep=True also pull stories/attachments/subtasks.

    proj_map: {project_gid: project} — built from the workspace project list,
    used to attach team/name context from the task's memberships.
    """
    assignee = task.get("assignee") or {}
    parent = task.get("parent") or {}
    primary, memberships = _first_membership(task)
    section = (primary.get("section") or {}).get("name", "")
    proj_ref = primary.get("project") or {}
    project_gid = proj_ref.get("gid") or ""
    project_name = proj_ref.get("name") or ""
    proj = proj_map.get(project_gid) or {}
    team = proj.get("team") or {}
    if not project_name:
        project_name = proj.get("name", "")

    tags = [t.get("name", "") for t in (task.get("tags") or [])]
    followers = [f.get("name") or f.get("email", "") for f in (task.get("followers") or [])]
    deps = [d.get("gid", "") for d in (task.get("dependencies") or [])]
    dependents = [d.get("gid", "") for d in (task.get("dependents") or [])]

    custom_fields = []
    for cf in (task.get("custom_fields") or []):
        custom_fields.append({
            "gid": cf.get("gid", ""),
            "name": cf.get("name", ""),
            "type": cf.get("resource_subtype", ""),
            "value": _cf_display(cf),
        })

    storage.upsert_asana_task(
        gid=task["gid"], name=task.get("name", ""),
        resource_subtype=task.get("resource_type", ""),
        project_gid=project_gid, project_name=project_name,
        section=section, team_gid=team.get("gid", ""), team_name=team.get("name", ""),
        assignee_gid=assignee.get("gid", ""), assignee_name=assignee.get("name", ""),
        assignee_email=assignee.get("email", ""),
        due_on=task.get("due_on") or "", start_on=task.get("start_on") or "",
        completed=1 if task.get("completed") else 0,
        completed_at=task.get("completed_at") or "",
        created_at=task.get("created_at") or "",
        modified_at=task.get("modified_at") or "",
        permalink=task.get("permalink_url") or "",
        parent_gid=parent.get("gid", ""), parent_name=parent.get("name", ""),
        num_subtasks=int(task.get("num_subtasks") or 0),
        tags=tags, followers=followers, dependencies=deps, dependents=dependents,
        notes=task.get("notes") or "",
        custom_fields=custom_fields, memberships=memberships,
        weight=task_weight(task.get("name", "")),
    )

    # Stories / comments (deep sync only — lazy otherwise)
    if not deep:
        return
    try:
        stories = paginate(headers, f"/tasks/{task['gid']}/stories",
                           {"opt_fields": "gid,type,text,created_at,is_pinned,"
                                          "created_by.name,created_by.email"})
    except RuntimeError:
        stories = []
    for s in stories:
        author = s.get("created_by") or {}
        storage.upsert_asana_story(
            gid=s["gid"], task_gid=task["gid"], author=author.get("name", ""),
            author_email=author.get("email", ""),
            type="comment" if s.get("type") == "comment" else "system",
            text=s.get("text", ""), created_at=s.get("created_at", ""),
            is_pinned=1 if s.get("is_pinned") else 0,
        )
    # Attachments (inline from opt_fields)
    for a in (task.get("attachments") or []):
        storage.upsert_asana_attachment(
            gid=a["gid"], task_gid=task["gid"], name=a.get("name", ""),
            host=a.get("host", ""),
            url=a.get("download_url") or a.get("permanent_url") or "",
            view_url=a.get("view_url", ""), created_at=a.get("created_at", ""),
        )
    # Subtasks
    if task.get("num_subtasks"):
        try:
            subtasks = paginate(headers, f"/tasks/{task['gid']}/subtasks",
                                {"opt_fields": "gid,name,completed,completed_at,"
                                               "created_at,due_on,assignee.name,"
                                               "assignee.email,permalink_url"})
        except RuntimeError:
            subtasks = []
        for st in subtasks:
            st_assignee = st.get("assignee") or {}
            storage.upsert_asana_subtask(
                gid=st["gid"], parent_task_gid=task["gid"], name=st.get("name", ""),
                assignee_name=st_assignee.get("name", ""),
                assignee_email=st_assignee.get("email", ""),
                completed=1 if st.get("completed") else 0,
                completed_at=st.get("completed_at") or "",
                created_at=st.get("created_at") or "",
                due_on=st.get("due_on") or "",
                permalink=st.get("permalink_url") or "",
            )


def fetch_task_details(gid: str) -> dict:
    """Lazy-hydrate one task's stories/attachments/subtasks from Asana.

    Called on demand when a task detail is opened (deep sync is too slow
    for 266k tasks). Stores whatever it pulls, returns the fresh rows.
    """
    import storage

    headers = _headers()
    stories: list[dict] = []
    try:
        stories = paginate(headers, f"/tasks/{gid}/stories",
                           {"opt_fields": "gid,type,text,created_at,is_pinned,"
                                          "created_by.name,created_by.email"})
    except RuntimeError:
        pass
    for s in stories:
        author = s.get("created_by") or {}
        storage.upsert_asana_story(
            gid=s["gid"], task_gid=gid, author=author.get("name", ""),
            author_email=author.get("email", ""),
            type="comment" if s.get("type") == "comment" else "system",
            text=s.get("text", ""), created_at=s.get("created_at", ""),
            is_pinned=1 if s.get("is_pinned") else 0,
        )

    attachments: list[dict] = []
    try:
        attachments = paginate(headers, f"/tasks/{gid}/attachments",
                               {"opt_fields": "gid,name,host,download_url,"
                                              "view_url,permanent_url,created_at"})
    except RuntimeError:
        pass
    for a in attachments:
        storage.upsert_asana_attachment(
            gid=a["gid"], task_gid=gid, name=a.get("name", ""), host=a.get("host", ""),
            url=a.get("download_url") or a.get("permanent_url") or "",
            view_url=a.get("view_url", ""), created_at=a.get("created_at", ""),
        )

    subtasks: list[dict] = []
    task = storage.get_asana_task(gid)
    if task and task.get("num_subtasks"):
        try:
            subtasks = paginate(headers, f"/tasks/{gid}/subtasks",
                                {"opt_fields": "gid,name,completed,completed_at,"
                                               "created_at,due_on,assignee.name,"
                                               "assignee.email,permalink_url"})
        except RuntimeError:
            subtasks = []
        for st in subtasks:
            st_assignee = st.get("assignee") or {}
            storage.upsert_asana_subtask(
                gid=st["gid"], parent_task_gid=gid, name=st.get("name", ""),
                assignee_name=st_assignee.get("name", ""),
                assignee_email=st_assignee.get("email", ""),
                completed=1 if st.get("completed") else 0,
                completed_at=st.get("completed_at") or "",
                created_at=st.get("created_at") or "",
                due_on=st.get("due_on") or "",
                permalink=st.get("permalink_url") or "",
            )

    return {
        "stories": storage.list_asana_stories(gid),
        "attachments": storage.list_asana_attachments(gid),
        "subtasks": storage.list_asana_subtasks(gid),
    }
