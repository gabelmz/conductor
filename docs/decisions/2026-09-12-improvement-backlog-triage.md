# Decision: Adopt a prioritized P0/P1/P2 improvement backlog for Conductor

Status: decided
Date: 2026-09-12
Requested by: 5-agent review (Founder / SWE / Catalog-Compliance / Advertising-Brand / Supply-Chain) — triage + documentation pass

## Context

A five-agent review of the Conductor codebase (Electron + FastAPI + SQLite +
vanilla JS) surfaced **50 raw improvement items** across five lenses. The
findings are of very different character: some are silently-wrong code paths,
others are entire missing capabilities, and still others are maintainability and
security debt. Without a shared severity scheme, the list is unactionable — a
correctness bug with the same visibility as a "nice-to-have" module.

Two independent agents reported the **same** defect (the CDQ weight drift:
hardcoded `30/25/20/15/10` dashboard weights contradicting the scoring preset,
and the same drift reintroduced in `reports.py:generate_cdq`), confirming that
raw findings need deduplication before prioritization.

## Decision

1. **Triage every finding into one of three priorities** and record the result
   in a single consolidated backlog (`docs/improvement-backlog.md`):
   - **P0 — correctness bugs**: silently wrong output, dead code paths that
     return false/zero results, wrong weights or math, compliance flags that
     never fire.
   - **P1 — missing surfaces**: capabilities, entities, columns, or report types
     that do not exist at all (stubs, absent modules, un-surfaced data).
   - **P2 — hardening**: performance (unbounded queries), security (plaintext
     secrets, bundled tokens), deprecated APIs, concurrency, code quality.

2. **Dedupe cross-agent duplicates before counting.** The CDQ weight drift is
   one defect reported twice (Founder + Catalog/Compliance); it is merged into a
   single P0 item covering both the dashboard and `reports.py:generate_cdq`.

3. **Documentation only.** No source code is modified in this pass; the backlog
   and this record are the deliverables. Prioritization is by severity, not by
   the source lens that reported the item.

## Consequences

- The backlog becomes the single source of truth for the next engineering pass;
  each item carries its original file/line evidence so it can be acted on
  directly.
- P0 items are correctness bugs and should be fixed before any new surface is
  added — a feature built on the current CDQ/KPI/Prop-65/`asana_summary` logic
  would inherit silently-wrong results.
- P1 items are the product's growth surface (financial data, ads/brands,
  supply-chain entities). They are large; the backlog does not sequence them,
  only buckets them — sequencing is a follow-up planning decision.
- Cross-references (e.g. "no real financial data" ↔ "no product-performance
  metrics") are noted inline but deliberately kept as separate items, since
  different fix locations and owners are involved.
- Re-triage is expected: as P0s land, some P1 items (e.g. cost↔price conflation)
  may be promoted when their dependency on a missing surface is resolved.
