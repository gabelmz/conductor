# Conductor Data Contracts

Status: template for implementation documentation
Owner: TBD
Last reviewed: 2026-09-10

## Contract Rules

- Every public contract has a version.
- IDs are stable and opaque to renderers.
- Source and timestamps are explicit.
- Secrets never appear in response payloads, fixtures, diagrams, or logs.
- Compatibility changes are additive when practical.

## Provider Descriptor

```json
{
  "id": "openai",
  "label": "OpenAI",
  "kind": "openai-compatible",
  "baseUrl": "https://api.openai.com/v1",
  "capabilities": ["chat", "embeddings", "models"],
  "defaultModelId": "gpt-4o-mini",
  "configured": false,
  "modelSource": "provider-api|curated|local",
  "modelSourceUpdatedAt": null
}
```

## Model Record

```json
{
  "id": "gpt-4o-mini",
  "providerId": "openai",
  "label": "gpt-4o-mini",
  "capabilities": ["chat"],
  "source": "provider-api|curated|local",
  "updatedAt": null
}
```

A model list must be filtered by `providerId`. A selected model that does not belong to the selected provider is invalid.

## Structured Report Envelope

```json
{
  "schemaVersion": 1,
  "id": 123,
  "type": "cdq",
  "title": "CDQ Analysis",
  "createdAt": "2026-09-10T00:00:00Z",
  "updatedAt": "2026-09-10T00:00:00Z",
  "source": {"kind": "live", "system": "sqlite", "dataset": "products"},
  "parameters": {
    "date": null,
    "dateFrom": null,
    "dateTo": null,
    "latestOnly": false,
    "dataType": "catalog",
    "sourceId": "sqlite"
  },
  "summary": {},
  "data": {},
  "renderHints": {},
  "actions": ["view", "refresh", "replace", "delete", "rerun"]
}
```

## Report Actions

| Action | Input | Expected result |
| --- | --- | --- |
| Generate/parse | report type + parameters | New versioned report. |
| Refresh | report ID | New result using current source state. |
| Replace | report ID + parameters | Existing logical report replaced or versioned explicitly. |
| Delete | report ID | Idempotent removal with clear missing-record behavior. |
| View/export JSON | report ID | Full envelope without hidden fields. |
| Rerun | report ID + optional parameters | New report retaining lineage. |

## Filter Semantics

- `date`: exact source date where supported.
- `dateFrom` and `dateTo`: inclusive range; reject inverted ranges.
- `latestOnly`: deterministic latest record per report type/source.
- `dataType`: validated against the report type.
- `sourceId`: validated against registered source adapters.

## Integration Status

Every adapter should expose a consistent status shape containing `adapterId`, `configured`, `reachable`, `lastSuccessAt`, `lastError`, `retryable`, and `secretState` without revealing secret values.

## Migration Notes

- Preserve existing `/api/chat/providers`, `/api/chat/models`, and `/api/reports` response fields while adding canonical fields.
- Keep plugin cards and model metadata outside the analytical report envelope until explicitly reviewed.
- Record unresolved schema assumptions as `unverified`, not as facts.
