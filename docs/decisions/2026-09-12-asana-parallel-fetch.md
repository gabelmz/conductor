# Decision: Asana parallel fetch — NOT YET. Instrument first.

Status: decided
Date: 2026-09-12
Requested by: owner brief ("Parallel setup: evaluate for multi-key leverage. Decide + log rationale.")

## Decision

**Do not parallelize Asana fetching in this pass.** Ship telemetry, concurrency
control, and backoff hardening first. Re-evaluate against measured data.

## Rationale (evidence, not preference)

1. **There is no empirical rate-limit evidence in this repository.**
   The only number anywhere is an unsourced code comment at
   `backend/asana_sync.py:135` (`~2.2 req/s per token, Asana limit is 150/min`).
   `docs/sync-architecture.md` explicitly marks that same figure UNVERIFIED,
   noting it was inferred from the comment's own arithmetic rather than
   confirmed against a live API response. `data/backend.log` contains zero
   occurrences of `429`, `rate limit`, or `Retry-After`.

2. **We cannot measure what we do not record.**
   `api_get`'s 429 branch (`asana_sync.py:169-172`) sleeps and retries
   *silently* — no log line, no counter, no metric. `storage.record_asana_run`
   persists entity counts only: no request count, no 429 count, no per-call
   duration. Tuning concurrency against this is guesswork.

3. **Parallelism would be a no-op until the lock is fixed.**
   `_headers()` calls `time.sleep(wait)` while holding `_req_lock`
   (`asana_sync.py:145-154`). Under a worker pool every thread serializes on
   that lock, collapsing the per-token pacing benefit that multi-key rotation
   is supposed to buy. The lock must release before sleeping.

4. **The real 429 exposure today is uncontrolled concurrency, not insufficient
   parallelism.** `sync_all` takes no lease (`backend/main.py:571-604`) while
   three independent schedulers can fire at it:
   - desktop background loop every 300 s (`sync_runner.py:598-623`)
   - hosted pg_cron every 15 min (`supabase/migrations/20260901_0001_*.sql:177-193`)
   - manual/hook pull (`main.py:607-644`)
   All three share one PAT with no shared request budget. Adding keys 2-4 on
   top of that increases collision surface rather than throughput.

## Sequence before re-evaluating

1. Record request count, 429 count, and Retry-After values per sync run.
2. Take a lease in `sync_all` so the three schedulers cannot overlap.
3. Release `_req_lock` before sleeping in `_headers()`.
4. Jittered exponential backoff (currently linear and unjittered).
5. Re-open this decision with a week of real numbers.

## Config floors (owner brief: "prior config = floor, not target")

Read as minimums to meet or exceed, not values to set:

| Constant | Floor | Current | Action |
|---|---|---|---|
| `WORKSPACE_GID` | 1161027935621444 | same (`asana_sync.py:38`) | unchanged |
| `BATCH_SIZE` | 100 | 100 (`:43`) | unchanged, now configurable |
| `RATE_LIMIT_MS` | 200 | 450 ms (`MIN_INTERVAL_S`, `:135`) | **keep 450** — exceeds the floor |
| `RETRY_LIMIT` | 3 | 5 (`MAX_RETRIES`, `:44`) | **keep 5** — exceeds the floor |
| `TIMEOUT_BUFFER` | 300000 ms | did not exist | **introduced at 300000 ms** |

Lowering retries to 3 or pacing to 200 ms would be a regression against a
floor, so current values stand. `RATE_LIMIT_MS` in `asana_sync.py:45` was dead
code whose name (ms) contradicted its value (seconds); it is removed in favour
of the `MIN_INTERVAL_S` pacer that is actually used.
