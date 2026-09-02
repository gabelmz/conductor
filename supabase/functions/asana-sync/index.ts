// supabase/functions/asana-sync/index.ts
//
// Hosted counterpart to backend/sync_runner.py's local-fallback runner: pulls changed Asana
// tasks and upserts them into public.conductor_records, using the SAME lease/checkpoint
// tables and the SAME idempotency convention as the Python side, so the two can never write
// the same records concurrently and neither can duplicate a batch.
//
// Secrets come ONLY from Deno.env (set via `supabase secrets set`, never hard-coded here):
//   SUPABASE_URL                - project URL
//   SUPABASE_SERVICE_ROLE_KEY   - service-role key (server-side only; never returned to a caller)
//   ASANA_PAT                   - Asana personal access token (read-only usage: GET only)
//   ASANA_WORKSPACE_GID         - Asana workspace gid (falls back to a default if unset)
//
// Idempotency key: the Asana task `gid`, written as conductor_records.record_key with
// entity_type='asana_tasks' — the SAME convention backend/supabase_sync.py already uses
// (local_adapters()/_push_entity), matched deliberately rather than inventing a second one.
//
// Concurrency safety: lease acquisition is a single atomic SQL statement
// (public.try_acquire_sync_lease, added by supabase/migrations/20260901_0001_asana_sync_spine
// .sql) rather than a check-then-write from this function — a naive read-then-write here
// would itself be a race under two concurrent invocations. If the lease can't be acquired,
// this function returns 200 {"status":"skipped","reason":"lease_held"} immediately and does
// no other work at all, so invoking it twice concurrently never duplicates a sync.
//
// UNVERIFIED WITHOUT A LIVE DEPLOY: this file has not been deployed or executed. It has not
// been type-checked by the Deno toolchain in this session, and no live Asana/Supabase call has
// been made from it. Review before deploying.
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const ENTITY = "asana_tasks";
const LEASE_TTL_S = 300; // 5 minutes — long enough for a full paced Asana pull

const ASANA_BASE_URL = "https://app.asana.com/api/1.0";
const DEFAULT_WORKSPACE_GID = "1161027935621444"; // matches backend/asana_sync.py's default

// Same TASK_OPT_FIELDS shape as backend/asana_sync.py:48 (kept in sync manually — there is no
// shared package between the Python backend and this Deno function to import it from).
const TASK_OPT_FIELDS = [
  "gid", "name", "resource_type", "created_at", "completed_at", "modified_at", "completed",
  "assignee.gid", "assignee.name", "assignee.email", "due_on", "start_on", "notes",
  "permalink_url", "tags.name", "followers.name", "followers.email", "parent.gid",
  "parent.name", "memberships.project.gid", "memberships.project.name",
  "memberships.section.name", "dependencies.gid", "dependents.gid", "num_subtasks",
  "custom_fields.gid", "custom_fields.name", "custom_fields.resource_subtype",
  "custom_fields.display_value",
].join(",");

const PROJECT_OPT_FIELDS = "gid,name,archived";

interface AsanaTask {
  gid: string;
  modified_at?: string;
  [key: string]: unknown;
}

function requireEnv(name: string): string {
  const value = Deno.env.get(name);
  if (!value) {
    // Never echo the name of a missing secret's *value* — only which env var was absent.
    throw new Error(`Missing required secret: ${name}`);
  }
  return value;
}

async function asanaGet(pat: string, path: string, params: Record<string, string> = {}): Promise<Record<string, unknown>> {
  const url = new URL(`${ASANA_BASE_URL}${path}`);
  for (const [k, v] of Object.entries(params)) url.searchParams.set(k, v);
  // Read-only by construction: this module only ever issues GET requests to Asana.
  const res = await fetch(url.toString(), {
    method: "GET",
    headers: { Authorization: `Bearer ${pat}`, Accept: "application/json" },
  });
  if (!res.ok) {
    const body = await res.text();
    // Never include the Authorization header/PAT in a thrown error message.
    throw new Error(`Asana API ${res.status} for ${path}: ${body.slice(0, 300)}`);
  }
  return await res.json();
}

async function asanaPaginate(pat: string, path: string, params: Record<string, string> = {}): Promise<AsanaTask[]> {
  const items: AsanaTask[] = [];
  let offset: string | undefined;
  // deno-lint-ignore no-constant-condition
  while (true) {
    const page = await asanaGet(pat, path, offset ? { ...params, offset } : params);
    const data = (page.data as AsanaTask[] | undefined) ?? [];
    items.push(...data);
    const next = page.next_page as { offset?: string } | null | undefined;
    if (next?.offset) {
      offset = next.offset;
    } else {
      break;
    }
  }
  return items;
}

async function fetchChangedTasks(pat: string, workspaceGid: string, cursor: string | null): Promise<{ items: AsanaTask[]; nextCursor: string }> {
  const startedAt = new Date().toISOString();
  const items: AsanaTask[] = [];
  if (cursor) {
    // Asana's workspace task-search endpoint filters on `modified_at.after` (ISO-8601
    // datetime) — NOT `modified_since` (that name only exists as `completed_since` on the
    // unrelated per-project /tasks listing endpoint). Same field backend/asana_sync.py's
    // mode="incremental" uses, kept identical deliberately. Confirmed against
    // developers.asana.com/reference/searchtasksforworkspace.
    for (const completed of ["false", "true"]) {
      const page = await asanaPaginate(pat, `/workspaces/${workspaceGid}/tasks/search`, {
        opt_fields: TASK_OPT_FIELDS,
        "modified_at.after": cursor,
        completed,
      });
      items.push(...page);
    }
  } else {
    // No checkpoint yet: bootstrap with a full per-project scan, same strategy as the local
    // fallback's mode="all"/mode="incremental" bootstrap, for guaranteed first-run coverage.
    const projects = await asanaPaginate(pat, "/projects", {
      workspace: workspaceGid,
      opt_fields: PROJECT_OPT_FIELDS,
    });
    for (const project of projects) {
      if (project.archived) continue;
      const page = await asanaPaginate(pat, "/tasks", {
        project: project.gid as string,
        opt_fields: TASK_OPT_FIELDS,
      });
      items.push(...page);
    }
  }
  return { items, nextCursor: startedAt };
}

Deno.serve(async (_req: Request) => {
  const startedAt = new Date().toISOString();
  const ownerId = `edge-function:${crypto.randomUUID()}`;

  let supabaseUrl: string, serviceRoleKey: string, asanaPat: string;
  try {
    supabaseUrl = requireEnv("SUPABASE_URL");
    serviceRoleKey = requireEnv("SUPABASE_SERVICE_ROLE_KEY");
    asanaPat = requireEnv("ASANA_PAT");
  } catch (err) {
    // Config error — nothing acquired yet, nothing to release. Never include secret values.
    return jsonResponse({ ok: false, status: "error", error: String(err) }, 500);
  }
  const workspaceGid = Deno.env.get("ASANA_WORKSPACE_GID") || DEFAULT_WORKSPACE_GID;

  const supabase = createClient(supabaseUrl, serviceRoleKey, {
    auth: { persistSession: false },
  });

  // Atomic acquire — see supabase/migrations/20260901_0001_asana_sync_spine.sql for why this
  // must be a single SQL statement (RPC) rather than a read-then-write from here.
  const { data: acquired, error: leaseErr } = await supabase.rpc("try_acquire_sync_lease", {
    p_name: ENTITY,
    p_owner: ownerId,
    p_ttl_s: LEASE_TTL_S,
  });
  if (leaseErr) {
    return jsonResponse({ ok: false, status: "error", error: leaseErr.message }, 502);
  }
  if (!acquired) {
    // Someone else (the other hosted invocation, or the local fallback) holds a live lease.
    // Exit cleanly, do nothing else — this is what makes two concurrent invocations safe.
    return jsonResponse({ ok: true, status: "skipped", reason: "lease_held", entity: ENTITY }, 200);
  }

  let cursorBefore: string | null = null;
  let cursorAfter: string | null = null;
  let rows = 0;
  const errors: string[] = [];

  try {
    const { data: cpRow } = await supabase
      .from("sync_checkpoints")
      .select("cursor")
      .eq("entity", ENTITY)
      .maybeSingle();
    cursorBefore = (cpRow?.cursor as string | undefined) ?? null;

    const { items, nextCursor } = await fetchChangedTasks(asanaPat, workspaceGid, cursorBefore);

    if (items.length > 0) {
      const upsertRows = items.map((task) => ({
        entity_type: ENTITY,
        record_key: task.gid,
        payload: task,
        source_updated_at: task.modified_at ?? null,
      }));
      const { error: upsertErr } = await supabase
        .from("conductor_records")
        .upsert(upsertRows, { onConflict: "entity_type,record_key" });
      if (upsertErr) {
        errors.push(`conductor_records upsert: ${upsertErr.message}`);
      } else {
        rows = items.length;
      }
    }

    if (errors.length === 0) {
      const { error: cpErr } = await supabase
        .from("sync_checkpoints")
        .upsert({ entity: ENTITY, cursor: nextCursor, updated_at: new Date().toISOString() }, { onConflict: "entity" });
      if (cpErr) {
        errors.push(`checkpoint advance: ${cpErr.message}`);
      } else {
        cursorAfter = nextCursor;
      }
    }
  } catch (err) {
    errors.push(String(err));
  } finally {
    // Always release, even on error, so an expired-lease steal isn't the only way to recover.
    await supabase.rpc("release_sync_lease", { p_name: ENTITY, p_owner: ownerId });
  }

  const finishedAt = new Date().toISOString();
  const status = errors.length > 0 ? "error" : "done";
  await supabase.from("sync_runs").insert({
    id: crypto.randomUUID(),
    direction: "pull",
    conflict_policy: "newest",
    status,
    started_at: startedAt,
    finished_at: finishedAt,
    counts: { rows, errors: errors.length },
    error: errors.join("; ").slice(0, 1000),
    entity: ENTITY,
    degraded: false, // the hosted path has no outbox fallback of its own — see module docstring
    lease_owner: ownerId,
    cursor_before: cursorBefore,
    cursor_after: cursorAfter,
  });

  return jsonResponse({ ok: errors.length === 0, status, entity: ENTITY, rows, errors }, errors.length === 0 ? 200 : 502);
});

function jsonResponse(body: unknown, status: number): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
