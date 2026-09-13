# Conductor — Consolidated Improvement Backlog

Source: 5-agent codebase review (Founder / SWE / Catalog-Compliance /
Advertising-Brand / Supply-Chain). Date: 2026-09-12.

**50 raw findings → 49 unique items** after deduplication. See the companion
decision record `docs/decisions/2026-09-12-improvement-backlog-triage.md` for the
triage rationale.

## Priorities

- **P0 — correctness bugs**: silently wrong output, dead code paths returning
  false/zero results, wrong weights/math, compliance flags that never fire.
  Fix before building anything on top.
- **P1 — missing surfaces**: capabilities, entities, columns, report types that
  do not exist at all (stubs, absent modules, un-surfaced data).
- **P2 — hardening**: performance, security, deprecated APIs, concurrency, code
  quality.

## Dedupe note

- **CDQ weight drift** was reported by both **Founder** ("CDQ dashboard hardcodes
  30/25/20/15/10 weights contradicting the scoring preset") and
  **Catalog/Compliance** ("CDQ weight drift reintroduced in reports.py
  generate_cdq"). Merged into **P0-1** (two code sites, one root cause).
- Related-but-distinct findings are cross-referenced inline (e.g. "no real
  financial data" ↔ "no product-performance metrics") and kept as separate items
  because their fix locations differ.

---

## P0 — Correctness bugs

| ID | Item | Lens | Evidence / location |
|---|---|---|---|
| P0-1 | **CDQ weight drift.** Dashboard hardcodes `30/25/20/15/10` weights that contradict the scoring preset; the same drift is reintroduced in `reports.py:generate_cdq`. *(Dedupe of two findings.)* | Founder + Catalog/Compliance | CDQ dashboard; `reports.py:generate_cdq` |
| P0-2 | `kpi.py` averages %-to-goal **unweighted**, ignoring the weight column — wrong KPI scores. | Founder | `kpi.py` |
| P0-3 | Hardcoded **machine-specific KPI seed path** `C:\Users\GabeMaher\...\Global KPIs (1).xlsx` — breaks on any other machine. | Founder | KPI seed path |
| P0-4 | Missing `import urllib.request` — **update check silently dead**. | SWE | `main.py:124` |
| P0-5 | Missing `import re` — `asana_summary` **silently returns zeros**. | SWE | `storage.py:1164` |
| P0-6 | Prop 65 `markets=['US-CA']` never matches the default `'US'` — **flag never fires**. | Catalog/Compliance | Prop 65 market mapping |
| P0-7 | N/A + pass regulations **dilute the compliance score**. | Catalog/Compliance | compliance scoring |
| P0-8 | `Finding.evidence_required` **never rendered** in `complianceReportHTML`. | Catalog/Compliance | compliance report render |
| P0-9 | **cost→price conflation** in mapping — financial fields are conflated. | Supply Chain | mapping layer |

## P1 — Missing surfaces

### Founder

| ID | Item |
|---|---|
| P1-1 | No real financial data anywhere (revenue / margin / COGS). |
| P1-2 | `brand_onboarding.py` forecast is a toy (placeholder ASINs, no payback). *(Current placeholder for the P1-7 forecasting gap.)* |
| P1-3 | `reports.py:_generate_report` only accepts `'cdq'` — no other report types. |
| P1-4 | No trend / time-series on quality or throughput. |
| P1-5 | No on/off-track status for KPIs/tasks. |
| P1-6 | Dashboard leads with automation vanity metrics instead of business KPIs. *(Related to P1-1/P1-5.)* |
| P1-7 | No forecasting capability. |

### Catalog / Compliance

| ID | Item |
|---|---|
| P1-8 | `flatfiles.py:/generate` ignores the `required` flag and emits no valid-values. |
| P1-9 | Missing flat-file columns: battery / hazmat / Prop 65 / CoO. |
| P1-10 | `attributeaudit` only checks barcodes — no other attribute validation. |
| P1-11 | `listing_content` `CONTENT_FIELDS` has no compliance/structured-attrs. |
| P1-12 | Compliance is not re-run on attribute update (stale compliance). |

### Advertising / Brand

| ID | Item |
|---|---|
| P1-13 | No ads/campaigns module at all. |
| P1-14 | Content view is `renderModuleStub`. |
| P1-15 | Brands view is `renderModuleStub`. |
| P1-16 | `brandcompare.py` only compares catalog-internal brands (no live competitors). |
| P1-17 | `brandcompare:/brief` AI receives only generic category strings. |
| P1-18 | `keepa.py` discards the price-history CSV. |
| P1-19 | Keepa flattens to static attributes (time-series lost). |
| P1-20 | No product-performance surface (sessions / CVR / revenue / rank). *(Related to P1-1.)* |
| P1-21 | `listing_compare` uses only string similarity. |
| P1-22 | `insights.py` is a generic file-drop, not ecommerce-aware. |

### Supply Chain

| ID | Item |
|---|---|
| P1-23 | No inventory columns in the `products` table. |
| P1-24 | No suppliers entity (lead time / MOQ / cost). |
| P1-25 | No purchase-order module. |
| P1-26 | "Inventory analysis" agent has no backend. |
| P1-27 | FBA module is a stub. |
| P1-28 | Supabase mirror limited to `{products, asana_tasks}`. |
| P1-29 | `asana_tasks` has no product/SKU link. |
| P1-30 | Stock not surfaced in `data.py` products source. |
| P1-31 | No stock→reorder Asana routing. |

## P2 — Hardening

| ID | Item | Lens |
|---|---|---|
| P2-1 | DB init/seed runs at **import time**. | SWE |
| P2-2 | Deprecated `@app.on_event` usage. | SWE |
| P2-3 | Unbounded hot-path queries — `stats()` pulls 2000 checks + 1000 tasks; `asana_summary` loads all tasks; `list_tags` full scan; `checks_summary` N+1. | SWE |
| P2-4 | Ad-hoc `threading.Thread(daemon=True)` per upload/sync. | SWE |
| P2-5 | Plaintext API key in `data/chat.json`; PATs in `data/asana.json`. *(Security — near-term.)* | SWE |
| P2-6 | `gh-token` bundled in the installer. *(Security.)* | SWE |
| P2-7 | Version hardcoded in 4+ places; `publish_release.py` still says v2.0.0. | SWE |
| P2-8 | `app.js` 10,477-line monolith; no lint/tests. | SWE |
| P2-9 | CDQ gates too weak (title `min_length=3`). | Catalog/Compliance |

## Summary counts

| Priority | Count |
|---|---|
| P0 correctness | 9 |
| P1 missing surface | 31 |
| P2 hardening | 9 |
| **Total (deduped)** | **49** |
