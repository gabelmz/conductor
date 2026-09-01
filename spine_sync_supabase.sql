
    INSERT INTO conductor.status_definitions (status_key, label, description, category, color_token, sort_order, active, metadata, updated_at)
    VALUES ('draft', 'Draft', 'Created but not ready for normal use.', 'lifecycle', 'muted', 10, 1, '{}'::jsonb, '2026-09-01T07:17:24.354136+00:00')
    ON CONFLICT (status_key) DO UPDATE SET label=EXCLUDED.label, description=EXCLUDED.description, category=EXCLUDED.category, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.status_definitions (status_key, label, description, category, color_token, sort_order, active, metadata, updated_at)
    VALUES ('active', 'Active', 'Available for normal use.', 'lifecycle', 'success', 20, 1, '{}'::jsonb, '2026-09-01T07:17:24.354136+00:00')
    ON CONFLICT (status_key) DO UPDATE SET label=EXCLUDED.label, description=EXCLUDED.description, category=EXCLUDED.category, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.status_definitions (status_key, label, description, category, color_token, sort_order, active, metadata, updated_at)
    VALUES ('disabled', 'Disabled', 'Retained but unavailable for use.', 'lifecycle', 'warning', 30, 1, '{}'::jsonb, '2026-09-01T07:17:24.354136+00:00')
    ON CONFLICT (status_key) DO UPDATE SET label=EXCLUDED.label, description=EXCLUDED.description, category=EXCLUDED.category, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.status_definitions (status_key, label, description, category, color_token, sort_order, active, metadata, updated_at)
    VALUES ('deprecated', 'Deprecated', 'Supported temporarily; replace it.', 'lifecycle', 'warning', 40, 1, '{}'::jsonb, '2026-09-01T07:17:24.354136+00:00')
    ON CONFLICT (status_key) DO UPDATE SET label=EXCLUDED.label, description=EXCLUDED.description, category=EXCLUDED.category, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.status_definitions (status_key, label, description, category, color_token, sort_order, active, metadata, updated_at)
    VALUES ('archived', 'Archived', 'Historical record only.', 'lifecycle', 'muted', 50, 1, '{}'::jsonb, '2026-09-01T07:17:24.354136+00:00')
    ON CONFLICT (status_key) DO UPDATE SET label=EXCLUDED.label, description=EXCLUDED.description, category=EXCLUDED.category, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.status_definitions (status_key, label, description, category, color_token, sort_order, active, metadata, updated_at)
    VALUES ('queued', 'Queued', 'Awaiting execution.', 'job', 'muted', 60, 1, '{}'::jsonb, '2026-09-01T07:17:24.354136+00:00')
    ON CONFLICT (status_key) DO UPDATE SET label=EXCLUDED.label, description=EXCLUDED.description, category=EXCLUDED.category, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.status_definitions (status_key, label, description, category, color_token, sort_order, active, metadata, updated_at)
    VALUES ('running', 'Running', 'Currently executing.', 'job', 'info', 70, 1, '{}'::jsonb, '2026-09-01T07:17:24.354136+00:00')
    ON CONFLICT (status_key) DO UPDATE SET label=EXCLUDED.label, description=EXCLUDED.description, category=EXCLUDED.category, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.status_definitions (status_key, label, description, category, color_token, sort_order, active, metadata, updated_at)
    VALUES ('ready', 'Ready', 'Prepared for the next lifecycle action.', 'job', 'success', 80, 1, '{}'::jsonb, '2026-09-01T07:17:24.354136+00:00')
    ON CONFLICT (status_key) DO UPDATE SET label=EXCLUDED.label, description=EXCLUDED.description, category=EXCLUDED.category, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.status_definitions (status_key, label, description, category, color_token, sort_order, active, metadata, updated_at)
    VALUES ('done', 'Done', 'Completed successfully.', 'job', 'success', 90, 1, '{}'::jsonb, '2026-09-01T07:17:24.354136+00:00')
    ON CONFLICT (status_key) DO UPDATE SET label=EXCLUDED.label, description=EXCLUDED.description, category=EXCLUDED.category, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.status_definitions (status_key, label, description, category, color_token, sort_order, active, metadata, updated_at)
    VALUES ('error', 'Error', 'Failed and requires review.', 'job', 'danger', 100, 1, '{}'::jsonb, '2026-09-01T07:17:24.354136+00:00')
    ON CONFLICT (status_key) DO UPDATE SET label=EXCLUDED.label, description=EXCLUDED.description, category=EXCLUDED.category, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.lifecycle_definitions (lifecycle_key, label, description, sort_order, terminal, transitions, metadata, updated_at)
    VALUES ('draft', 'Draft', 'Definition is being designed.', 10, FALSE, '["active", "archived"]'::jsonb, '{}'::jsonb, '2026-09-01T07:17:24.354136+00:00')
    ON CONFLICT (lifecycle_key) DO UPDATE SET label=EXCLUDED.label, description=EXCLUDED.description, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.lifecycle_definitions (lifecycle_key, label, description, sort_order, terminal, transitions, metadata, updated_at)
    VALUES ('active', 'Active', 'Live and available.', 20, FALSE, '["disabled", "deprecated", "archived"]'::jsonb, '{}'::jsonb, '2026-09-01T07:17:24.354136+00:00')
    ON CONFLICT (lifecycle_key) DO UPDATE SET label=EXCLUDED.label, description=EXCLUDED.description, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.lifecycle_definitions (lifecycle_key, label, description, sort_order, terminal, transitions, metadata, updated_at)
    VALUES ('stable', 'Stable', 'Versioned, production-safe definition.', 30, FALSE, '["deprecated", "archived"]'::jsonb, '{}'::jsonb, '2026-09-01T07:17:24.354136+00:00')
    ON CONFLICT (lifecycle_key) DO UPDATE SET label=EXCLUDED.label, description=EXCLUDED.description, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.lifecycle_definitions (lifecycle_key, label, description, sort_order, terminal, transitions, metadata, updated_at)
    VALUES ('deprecated', 'Deprecated', 'No new usage; migration path required.', 40, FALSE, '["archived"]'::jsonb, '{}'::jsonb, '2026-09-01T07:17:24.354136+00:00')
    ON CONFLICT (lifecycle_key) DO UPDATE SET label=EXCLUDED.label, description=EXCLUDED.description, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.lifecycle_definitions (lifecycle_key, label, description, sort_order, terminal, transitions, metadata, updated_at)
    VALUES ('archived', 'Archived', 'Retained as a historical record.', 50, TRUE, '[]'::jsonb, '{}'::jsonb, '2026-09-01T07:17:24.354136+00:00')
    ON CONFLICT (lifecycle_key) DO UPDATE SET label=EXCLUDED.label, description=EXCLUDED.description, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.node_library (node_type, label, description, category, icon, input_schema, output_schema, config_schema, execution_mode, lifecycle_key, enabled, metadata, updated_at)
    VALUES ('ai', 'AI', 'Runs a configured chat, extraction, or embedding model.', 'ai', 'codicon-sparkle', '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, 'local', 'stable', TRUE, '{}'::jsonb, '2026-09-01T07:17:24.354136+00:00')
    ON CONFLICT (node_type) DO UPDATE SET label=EXCLUDED.label, description=EXCLUDED.description, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.node_library (node_type, label, description, category, icon, input_schema, output_schema, config_schema, execution_mode, lifecycle_key, enabled, metadata, updated_at)
    VALUES ('script', 'Script', 'Executes an approved local script.', 'automation', 'codicon-terminal', '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, 'local', 'stable', TRUE, '{}'::jsonb, '2026-09-01T07:17:24.354136+00:00')
    ON CONFLICT (node_type) DO UPDATE SET label=EXCLUDED.label, description=EXCLUDED.description, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.node_library (node_type, label, description, category, icon, input_schema, output_schema, config_schema, execution_mode, lifecycle_key, enabled, metadata, updated_at)
    VALUES ('flush', 'Flush', 'Persists the pipeline output.', 'control', 'codicon-save', '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, 'local', 'stable', TRUE, '{}'::jsonb, '2026-09-01T07:17:24.354136+00:00')
    ON CONFLICT (node_type) DO UPDATE SET label=EXCLUDED.label, description=EXCLUDED.description, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.node_library (node_type, label, description, category, icon, input_schema, output_schema, config_schema, execution_mode, lifecycle_key, enabled, metadata, updated_at)
    VALUES ('trigger', 'Trigger', 'Starts a Flow Canvas run from a manual, schedule, webhook, or event source.', 'control', 'codicon-run', '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, 'local', 'stable', TRUE, '{}'::jsonb, '2026-09-01T07:17:24.354136+00:00')
    ON CONFLICT (node_type) DO UPDATE SET label=EXCLUDED.label, description=EXCLUDED.description, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.node_library (node_type, label, description, category, icon, input_schema, output_schema, config_schema, execution_mode, lifecycle_key, enabled, metadata, updated_at)
    VALUES ('custom', 'Custom', 'Extensible user-defined node.', 'custom', 'codicon-puzzle', '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, 'local', 'stable', TRUE, '{}'::jsonb, '2026-09-01T07:17:24.354136+00:00')
    ON CONFLICT (node_type) DO UPDATE SET label=EXCLUDED.label, description=EXCLUDED.description, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.node_library (node_type, label, description, category, icon, input_schema, output_schema, config_schema, execution_mode, lifecycle_key, enabled, metadata, updated_at)
    VALUES ('json', 'JSON', 'Transforms structured JSON data.', 'data', 'codicon-json', '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, 'local', 'stable', TRUE, '{}'::jsonb, '2026-09-01T07:17:24.354136+00:00')
    ON CONFLICT (node_type) DO UPDATE SET label=EXCLUDED.label, description=EXCLUDED.description, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.node_library (node_type, label, description, category, icon, input_schema, output_schema, config_schema, execution_mode, lifecycle_key, enabled, metadata, updated_at)
    VALUES ('text', 'Text', 'Creates or transforms text values.', 'data', 'codicon-symbol-string', '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, 'local', 'stable', TRUE, '{}'::jsonb, '2026-09-01T07:17:24.354136+00:00')
    ON CONFLICT (node_type) DO UPDATE SET label=EXCLUDED.label, description=EXCLUDED.description, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.node_library (node_type, label, description, category, icon, input_schema, output_schema, config_schema, execution_mode, lifecycle_key, enabled, metadata, updated_at)
    VALUES ('drive', 'Drive', 'Reads or writes an approved file source.', 'integration', 'codicon-folder-opened', '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, 'local', 'stable', TRUE, '{}'::jsonb, '2026-09-01T07:17:24.354136+00:00')
    ON CONFLICT (node_type) DO UPDATE SET label=EXCLUDED.label, description=EXCLUDED.description, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.node_library (node_type, label, description, category, icon, input_schema, output_schema, config_schema, execution_mode, lifecycle_key, enabled, metadata, updated_at)
    VALUES ('http', 'HTTP', 'Calls an external HTTP API.', 'integration', 'codicon-globe', '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, 'local', 'stable', TRUE, '{}'::jsonb, '2026-09-01T07:17:24.354136+00:00')
    ON CONFLICT (node_type) DO UPDATE SET label=EXCLUDED.label, description=EXCLUDED.description, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.node_library (node_type, label, description, category, icon, input_schema, output_schema, config_schema, execution_mode, lifecycle_key, enabled, metadata, updated_at)
    VALUES ('sheet', 'Sheet', 'Reads or writes an approved spreadsheet source.', 'integration', 'codicon-table', '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, 'local', 'stable', TRUE, '{}'::jsonb, '2026-09-01T07:17:24.354136+00:00')
    ON CONFLICT (node_type) DO UPDATE SET label=EXCLUDED.label, description=EXCLUDED.description, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.datasets (dataset_key, label, description, entity_type, source_type, lifecycle_key, freshness_seconds, schema_definition, source_config, metadata, updated_at)
    VALUES ('asana_tasks', 'Asana Tasks', 'Mirrored work items and their project/team context.', 'task', 'asana', 'active', 3600, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, '2026-09-01T07:17:24.354136+00:00')
    ON CONFLICT (dataset_key) DO UPDATE SET label=EXCLUDED.label, description=EXCLUDED.description, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.datasets (dataset_key, label, description, entity_type, source_type, lifecycle_key, freshness_seconds, schema_definition, source_config, metadata, updated_at)
    VALUES ('catalog_products', 'Catalog Products', 'Canonical product catalog and normalized attributes.', 'product', 'sqlite', 'active', 0, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, '2026-09-01T07:17:24.354136+00:00')
    ON CONFLICT (dataset_key) DO UPDATE SET label=EXCLUDED.label, description=EXCLUDED.description, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.datasets (dataset_key, label, description, entity_type, source_type, lifecycle_key, freshness_seconds, schema_definition, source_config, metadata, updated_at)
    VALUES ('keepa_products', 'Keepa Products', 'Cached market intelligence and product detail from Keepa.', 'listing', 'keepa', 'active', 172800, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, '2026-09-01T07:17:24.354136+00:00')
    ON CONFLICT (dataset_key) DO UPDATE SET label=EXCLUDED.label, description=EXCLUDED.description, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.datasets (dataset_key, label, description, entity_type, source_type, lifecycle_key, freshness_seconds, schema_definition, source_config, metadata, updated_at)
    VALUES ('listing_comparisons', 'Listing Comparisons', 'Field-level suggested-vs-live comparison records and recommendations.', 'listing_comparison', 'computed', 'active', 0, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, '2026-09-01T07:17:24.354136+00:00')
    ON CONFLICT (dataset_key) DO UPDATE SET label=EXCLUDED.label, description=EXCLUDED.description, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.datasets (dataset_key, label, description, entity_type, source_type, lifecycle_key, freshness_seconds, schema_definition, source_config, metadata, updated_at)
    VALUES ('live_listing_content', 'Live Listing Content', 'Latest retrieved listing attributes used for comparison.', 'listing_content', 'sp_api', 'active', 172800, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, '2026-09-01T07:17:24.354136+00:00')
    ON CONFLICT (dataset_key) DO UPDATE SET label=EXCLUDED.label, description=EXCLUDED.description, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.datasets (dataset_key, label, description, entity_type, source_type, lifecycle_key, freshness_seconds, schema_definition, source_config, metadata, updated_at)
    VALUES ('suggested_content', 'Suggested Listing Content', 'Uploaded or connected proposed listing attributes.', 'listing_content', 'upload', 'active', 86400, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, '2026-09-01T07:17:24.354136+00:00')
    ON CONFLICT (dataset_key) DO UPDATE SET label=EXCLUDED.label, description=EXCLUDED.description, updated_at=EXCLUDED.updated_at;
    