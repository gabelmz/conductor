# Decision: Report formats are recognized by spine-tagged, user-overridable presets

Status: decided
Date: 2026-09-12

## Decision

Recognize catalog-department report files automatically by matching them against
declarative **report presets**, with the canonical set in one module
(`BUILTIN_REPORT_PRESETS`, `backend/report_presets.py`) and user edits stored as
spine overrides. There is no manual format-selection step.

## Rationale (evidence, not preference)

1. **The report files are stable and enumerable.** The catalog department drops
   a finite, known set of formats (CDQ report, shipments, sales rollup, roster,
   ASIN map, listings, KPI definitions, reviews + OPS, and a handover document).
   Nine presets cover them; each is recognized from extension, delimiter, sheet
   name, and a header-signature fingerprint. A fixed set beats an ML/LLM
   classifier here: it is deterministic, testable, and has no per-file latency
   or token cost.

2. **The field schema must be typed to land in the right view.** Detection only
   half-solves the problem; the columns need types (`currency`, `percent`,
   `date`, `bool`, …) before they render correctly. A preset bundles recognition
   and schema in one place, so the same definition drives both.

3. **One source of truth, editable without forking.** Putting the canonical set
   in a single dict means "add a format" is one edit plus one test case. User
   edits go through the spine's existing non-secret user-config layer
   (scope `reports`, key `presets`) and are merged by `resolve_presets()` on
   read — so an edited preset survives a re-seed without clobbering the shipped
   default, and a reset restores the built-in. The scope/key is distinct from
   `reports.py`'s `scoring`/`presets` (CDQ scoring weights) to avoid collision.

4. **Built-ins are protected.** A built-in preset can be overridden or reset but
   never deleted, so a user mistake cannot remove a shipped format. Only
   user-created presets are deletable.

5. **Spine tagging makes presets first-class glossary entries.** Each built-in
   is tagged into `spine_registry` (`kind = report_preset`) by
   `_seed_report_presets`, so it is discoverable in the spine glossary and
   mirrored to Supabase `conductor.registry` — the same lifecycle as features,
   datasets, and filters. The registry row carries only summary metadata; the
   schema stays in the module, keeping one canonical place for the field
   definitions.

## Consequence

- Detection (`detect_report_format`) is side-effect free and reads only the
  built-in set; a `none` result falls through to the generic Mapping page.
- `date` and `json` are reserved, valid field types today but are not yet
  coerced (passed through as text). Revisit when a caller needs parsed dates or
  deserialized JSON.

## Re-evaluate when

- A report format is dropped whose header signature overlaps an existing
  preset's enough to cross the 0.45 partial-match threshold — the fingerprint
  set will then need disambiguation.
- The number of presets grows past a handful, at which point per-category
  split or a schema registry table may be cleaner than a single dict.
