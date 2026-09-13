# Report Presets

Status: current
Owner: catalog dev
Last reviewed: 2026-09-12

## What report presets are

Every report the catalog department drops into Conductor is matched against a
**preset** so it lands in the right view with the right column types
immediately — no manual format selection. A preset is a single declarative
object that describes:

| Concern | Field | Purpose |
| --- | --- | --- |
| Identity | `key`, `label`, `category`, `description` | Naming, grouping, and glossary text |
| Target entity | `entity` | Which entity the parsed rows map onto (`cdq`, `listing`, `shipment`, `sales`, `employee`, …) |
| Document flag | `is_document` | `true` for narrative files (DOCX/PDF/MD) that have no column schema |
| Recognition | `file` | How to recognize the file: extensions, delimiter, sheet name, header row, header signature |
| Typed schema | `fields` | Column definitions with a key, label, type, required flag, and aliases |

The canonical set lives in `backend/report_presets.py` as
`BUILTIN_REPORT_PRESETS` — the **single source of truth** (see
[Adding a new report format](#adding-a-new-report-format)). User edits are stored
separately as spine overrides and merged on read, so a shipped default is never
clobbered by an edit and an edit survives a re-seed.

### The nine built-in presets

| Key | Label | Entity | Category | Recognized as |
| --- | --- | --- | --- | --- |
| `kpi_definitions` | KPI Definitions | `kpi_definition` | team | Multi-section CSV (`Sheet13.csv`): Universal + Team KPI definitions |
| `catalog_ops` | Catalog OPS — Employee Roster | `employee` | team | XLSX/XLSM, sheet `BASE`, header on row 3 |
| `asin_map` | Active ASIN List | `asin_sku_map` | catalog | CSV: vendor → ASIN → SKU map |
| `cdq_report` | CDQ Report | `cdq` | catalog_quality | CSV: Catalog Data Quality v3 |
| `reviews_ops` | Reviews + OPS | `reviews_ops` | reviews | XLSX/XLSM, sheet `Export Data` |
| `amazon_listings` | Amazon Listings Report | `listing` | catalog | Tab-delimited `.txt`/`.tab`/`.tsv` |
| `handover_doc` | Handover / Process Document | `document` | document | DOCX/PDF/MD (narrative, `is_document`) |
| `shipments` | FBA Shipments (Shipment-level) | `shipment` | supply_chain | CSV: shipment-level FBA report |
| `sales_by_collection` | Sales by Collection (Quarterly) | `sales` | sales | CSV: quarterly sales rollup by collection |

## How detection works

`detect_report_format()` (`backend/report_presets.py:392`) scores every preset
against whatever the caller can provide about a file — `filename`, `headers`,
`sheet`, and `first_rows` — and returns the best match as
`{key, label, confidence, match_type}`. Header tokens are normalized first:
lowercased, every non-alphanumeric character becomes `_`, and runs of
underscores collapse (`_normalize`, matching the parser's `_clean_header`).

### Scoring

Each preset's `file` block contributes to a 0..1 confidence score:

| Signal | Weight | Condition |
| --- | --- | --- |
| Extension | +0.25 / −0.30 | extension in the preset's `extensions` (else penalized) |
| Sheet name | +0.25 / −0.20 | spreadsheet preset; `sheet` equals the preset's `sheet` (else penalized) |
| Header signature | +0.5 × (overlap ÷ signature length) | proportion of the preset's `header_signature` tokens present in the file's tokens |

The signature overlap is the dominant signal — a delimited file whose headers
fully match a preset's signature scores 0.75 (extension + full signature). Only
spreadsheet presets that also match on sheet name reach ~1.0.

### Match classification

| `match_type` | Confidence | Meaning |
| --- | --- | --- |
| `exact` | ≥ 0.90 | Extension, sheet name (where applicable), and full header signature all match |
| `partial` | ≥ 0.45 | Cleared the minimum threshold — likely match, confirm before trusting the schema |
| `none` | < 0.45 | No preset matches — the caller should fall through to the generic Mapping page for user-assisted mapping |

`detect_report_format` is idempotent and side-effect free; it reads only the
built-in set and never touches the spine. It is exposed without any persistence
via `POST /api/report-presets/detect`.

## Field-type taxonomy

`FIELD_TYPES` (`backend/report_presets.py:43`) is the closed set of legal field
types. `NUMERIC_TYPES` (`int`, `float`, `number`, `percent`, `currency`) is the
numeric subset, returned by `GET /api/report-presets/field-types` for UI hints.

| Type | Category | `_coerce` behavior |
| --- | --- | --- |
| `string` | text | Stored as-is |
| `int` | numeric | Strip `$ , %`, then `int(float(x))` |
| `float` | numeric | Strip `$ , %`, then `float(x)` |
| `number` | numeric | Same as `float` (generic numeric alias) |
| `currency` | numeric | Strip `$ , %`, then `float(x)` — raw numeric value, symbol dropped |
| `percent` | numeric | Strip `% ,`, then `float(x) / 100` (e.g. `"100.00%"` → `1.0`) |
| `date` | temporal | Passed through as text — not yet parsed to a date object |
| `bool` | flag | Truthy tokens `1`, `yes`, `true`, `y`, `on` (case-insensitive) → `true`, else `false` |
| `json` | structured | Passed through as text — not yet deserialized |

Coercion rules (shared with ingestion via `parse_delimited`):

- Empty/whitespace cells become `None`.
- A numeric cell that fails to parse is **left as-is** — it is never silently
  zeroed, so a bad value is visible rather than corrupting a rollup.
- `date` and `json` are valid, reserved type labels, but `_coerce` currently
  passes them through as raw text. Use `string` until a caller actually needs
  parsed dates or deserialized JSON.

Each field is declared with:

```json
{"key": "cdq_score", "label": "CDQ v3 Score", "type": "percent",
 "required": false, "aliases": ["cdq_v3_score"]}
```

`aliases` are extra header tokens that map onto the field during parsing, in
addition to the normalized `key` and `label`. A field marked `required` denotes
a key column (the preset's identity columns); every non-document preset must
declare at least one required field.

## Editing, adding, and resetting presets

All preset CRUD is served from the `report_presets` router, prefix
`/api/report-presets` (registered in `backend/main.py`).

### Endpoints

| Method | Path | Behavior |
| --- | --- | --- |
| GET | `/api/report-presets/presets` | Merged list `{presets: [...], count}` |
| GET | `/api/report-presets/presets/{key}` | One preset; 404 if unknown |
| POST | `/api/report-presets/detect` | Dry-run detection; no writes |
| PUT | `/api/report-presets/presets/{key}` | Create or edit a preset (validated) |
| DELETE | `/api/report-presets/presets/{key}` | Delete a **non-built-in** preset (204) |
| POST | `/api/report-presets/presets/{key}/reset` | Drop the override, restore the built-in (204) |
| GET | `/api/report-presets/field-types` | `{types: [...], numeric: [...]}` |

### Edit / add a preset

`PUT /api/report-presets/presets/{key}` takes the same shape as a built-in entry
(`label`, `category`, `description`, `entity`, `is_document`, `file`, `fields`)
and validates it before persisting:

- `label` is required; `entity` defaults to `report` if omitted.
- `file` must be an object; `fields` must be a list.
- Each field's `type` must be in `FIELD_TYPES`, its `key` is required, and keys
  must be unique within the preset.

Editing a built-in key (`cdq_report`, …) stores an override on top of the
shipped default; the response echoes `builtin: true`. A brand-new key produces a
custom preset with `builtin: false`.

```bash
curl -X PUT http://localhost:PORT/api/report-presets/presets/cdq_report \
  -H "Content-Type: application/json" \
  -d '{"label": "CDQ Report (edited)", "category": "catalog_quality",
       "entity": "cdq", "file": {"extensions": [".csv"], "delimiter": ",",
       "header_signature": ["parent_asin", "cdq_v3_grade"]},
       "fields": [{"key": "parent_asin", "label": "Parent ASIN",
                   "type": "string", "required": true}]}'
```

### Delete vs. reset

- **Built-ins cannot be deleted.** `DELETE` on a built-in key returns 400 with
  *"override it instead of deleting it"*. To go back to the shipped default, use
  `reset` (204), which drops the override and restores the built-in body.
- **Custom presets** (created by the user) can be deleted with `DELETE` (204).
  `reset` on a custom preset simply removes it, since there is no built-in to
  fall back to.

## Where presets persist (spine)

Presets are "tagged onto the spine" in two distinct places:

1. **User overrides** — `spine.user_config`, scope `reports`, key `presets`
   (`SPINE_SCOPE` / `SPINE_KEY`, `backend/report_presets.py:35-36`). These land
   in the `spine_configurations` table (the same non-secret, user-editable layer
   used by every other setting) via `user_config.put_configuration` /
   `read_configuration_value`. The scope/key is deliberately distinct from
   `reports.py`'s `scoring`/`presets` (CDQ scoring weights) so the two never
   collide.

2. **Registry glossary entries** — each built-in is tagged into `spine_registry`
   with `kind = report_preset` by `_seed_report_presets`
   (`backend/spine/default_state.py:154`), an idempotent upsert
   (`ON CONFLICT(kind, registry_key)`) that runs on every `init_spine_db()`.
   The registry row stores only summary metadata (entity, category, extensions,
   field count) and points at the `report-presets` route with the `codicon-file`
   icon — it makes presets discoverable in the spine glossary and mirrored to
   Supabase `conductor.registry` by `spine_sync.push_all()`. It never holds the
   field schema; that lives in `BUILTIN_REPORT_PRESETS`.

`resolve_presets()` (`backend/report_presets.py:445`) is the single merged read
path: built-ins first, then user overrides overlaid per key. This is what the
list/get endpoints return, and it is why an edited preset survives a re-seed
without clobbering the shipped default.

> Note: the module docstring refers to `default_state.seed_report_presets`; the
> actual function name is `_seed_report_presets`.

## Adding a new report format

The **single source of truth is `BUILTIN_REPORT_PRESETS`**
(`backend/report_presets.py:65`). To support a new report format, add one entry
to that dict and nothing else:

1. Pick a stable `key` (snake_case) and fill `label`, `category`, `description`,
   `entity`, and `is_document`.
2. Describe recognition in `file`:
   - `extensions` — file extensions to accept;
   - `delimiter` — `,` or `\t` for delimited files, `null` for spreadsheets/documents;
   - `sheet` — required sheet name for spreadsheet presets, else `null`;
   - `header_row` — 0-based header row index (row 3 ⇒ `3`);
   - `multi_section` — `true` for files whose header appears across sections;
   - `header_signature` — the distinctive header tokens (normalized form) that
     identify this format. These drive detection, so pick the few columns that
     are unique to this report.
3. Declare `fields` with the `_f(key, label, type, required=..., aliases=...)`
   helper. Mark the identity columns `required`. Non-document presets must have
   at least one required field.
4. Add a detection case to `DETECT_CASES` in `tests/test_report_presets.py` so
   recognition is covered.

No changes to `default_state.py`, `user_config.py`, or the router are needed —
`_seed_report_presets` iterates `BUILTIN_REPORT_PRESETS` and tags the new entry
into `spine_registry` on the next `init_spine_db()`.

A document-format preset (`is_document: true`, e.g. `handover_doc`) declares no
`fields` and an empty `header_signature`; it routes to the document viewer
rather than the tabular parser.
