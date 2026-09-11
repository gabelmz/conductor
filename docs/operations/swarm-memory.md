# `.swarm` Memory Operations

Status: template for implementation documentation
Owner: TBD
Last reviewed: 2026-09-10

## Purpose

`.swarm/` is generated agent research and orchestration state. It is not application runtime state, a configuration store, a secret store, or a replacement for checked-in documentation.

## Inputs And Provenance

| Artifact | Use | Retention |
| --- | --- | --- |
| `repo-graph.json` | architecture/navigation evidence | retain latest reviewed version |
| `knowledge*.jsonl` | findings and application history | compact reviewed findings |
| `summaries/` | run summaries | retain reviewed summaries; archive stale runs |
| `evidence/` | tool evidence | retain only evidence supporting active claims |
| `runs/` | execution history | time-bounded archive |
| `telemetry.jsonl` | operational telemetry | exclude from canonical docs |
| `locks/` | transient coordination | do not index as knowledge |

Every promoted finding should include source path, timestamp, confidence, and verification status.

## Sensitive Data Exclusion

Exclude credentials, tokens, provider key files, databases, uploads, chat documents, build artifacts, and raw response bodies that may contain personal or business data. Redact before promotion.

## Memory Utilization Policy

1. Deduplicate findings by normalized claim and source.
2. Prefer the newest verified source when claims conflict.
3. Keep one canonical summary per active workstream.
4. Archive stale runs rather than repeatedly loading them into context.
5. Promote durable findings into `docs/` after review.
6. Maintain a short unresolved-assumptions register.

## Cleanup Contract

A future cleanup command should support dry-run, archive, restore, and report-only modes. It must show counts for removed duplicates, archived entries, redactions, and retained provenance before changing files.

## Review Checklist

- [ ] No secrets or runtime database contents are present.
- [ ] Each durable claim links to a source file or test.
- [ ] Verified, inferred, and unverified claims are labeled.
- [ ] Duplicate run summaries are compacted.
- [ ] Generated telemetry and locks remain outside canonical docs.
- [ ] Cleanup has a dry-run result and rollback path.
