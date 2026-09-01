
    INSERT INTO conductor.file_type_definitions (extension, label, category, parse_handler, mime_types, max_bytes, enabled, metadata, updated_at)
    VALUES ('.csv', 'CSV', 'delimited', 'parse_catalog', '[]'::jsonb, 52428800, TRUE, '{}'::jsonb, NOW())
    ON CONFLICT (extension) DO UPDATE SET label=EXCLUDED.label, category=EXCLUDED.category, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.file_type_definitions (extension, label, category, parse_handler, mime_types, max_bytes, enabled, metadata, updated_at)
    VALUES ('.tsv', 'TSV', 'delimited', 'parse_catalog', '[]'::jsonb, 52428800, TRUE, '{}'::jsonb, NOW())
    ON CONFLICT (extension) DO UPDATE SET label=EXCLUDED.label, category=EXCLUDED.category, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.file_type_definitions (extension, label, category, parse_handler, mime_types, max_bytes, enabled, metadata, updated_at)
    VALUES ('.tab', 'Tab-delimited', 'delimited', 'parse_catalog', '[]'::jsonb, 52428800, TRUE, '{}'::jsonb, NOW())
    ON CONFLICT (extension) DO UPDATE SET label=EXCLUDED.label, category=EXCLUDED.category, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.file_type_definitions (extension, label, category, parse_handler, mime_types, max_bytes, enabled, metadata, updated_at)
    VALUES ('.txt', 'Text table', 'delimited', 'parse_catalog', '[]'::jsonb, 52428800, TRUE, '{}'::jsonb, NOW())
    ON CONFLICT (extension) DO UPDATE SET label=EXCLUDED.label, category=EXCLUDED.category, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.file_type_definitions (extension, label, category, parse_handler, mime_types, max_bytes, enabled, metadata, updated_at)
    VALUES ('.md', 'Markdown', 'document', 'parse_catalog', '[]'::jsonb, 52428800, TRUE, '{}'::jsonb, NOW())
    ON CONFLICT (extension) DO UPDATE SET label=EXCLUDED.label, category=EXCLUDED.category, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.file_type_definitions (extension, label, category, parse_handler, mime_types, max_bytes, enabled, metadata, updated_at)
    VALUES ('.pdf', 'PDF', 'document', 'parse_catalog', '[]'::jsonb, 52428800, TRUE, '{}'::jsonb, NOW())
    ON CONFLICT (extension) DO UPDATE SET label=EXCLUDED.label, category=EXCLUDED.category, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.file_type_definitions (extension, label, category, parse_handler, mime_types, max_bytes, enabled, metadata, updated_at)
    VALUES ('.docx', 'Word', 'document', 'parse_catalog', '[]'::jsonb, 52428800, TRUE, '{}'::jsonb, NOW())
    ON CONFLICT (extension) DO UPDATE SET label=EXCLUDED.label, category=EXCLUDED.category, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.file_type_definitions (extension, label, category, parse_handler, mime_types, max_bytes, enabled, metadata, updated_at)
    VALUES ('.xlsb', 'Excel Binary Workbook', 'spreadsheet', 'parse_catalog', '[]'::jsonb, 52428800, TRUE, '{}'::jsonb, NOW())
    ON CONFLICT (extension) DO UPDATE SET label=EXCLUDED.label, category=EXCLUDED.category, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.file_type_definitions (extension, label, category, parse_handler, mime_types, max_bytes, enabled, metadata, updated_at)
    VALUES ('.xlsm', 'Excel Macro Workbook', 'spreadsheet', 'parse_catalog', '[]'::jsonb, 52428800, TRUE, '{}'::jsonb, NOW())
    ON CONFLICT (extension) DO UPDATE SET label=EXCLUDED.label, category=EXCLUDED.category, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.file_type_definitions (extension, label, category, parse_handler, mime_types, max_bytes, enabled, metadata, updated_at)
    VALUES ('.xlsx', 'Excel Workbook', 'spreadsheet', 'parse_catalog', '[]'::jsonb, 52428800, TRUE, '{}'::jsonb, NOW())
    ON CONFLICT (extension) DO UPDATE SET label=EXCLUDED.label, category=EXCLUDED.category, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.file_type_definitions (extension, label, category, parse_handler, mime_types, max_bytes, enabled, metadata, updated_at)
    VALUES ('.json', 'JSON', 'structured', 'parse_catalog', '[]'::jsonb, 52428800, TRUE, '{}'::jsonb, NOW())
    ON CONFLICT (extension) DO UPDATE SET label=EXCLUDED.label, category=EXCLUDED.category, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.file_type_definitions (extension, label, category, parse_handler, mime_types, max_bytes, enabled, metadata, updated_at)
    VALUES ('.jsonl', 'JSON Lines', 'structured', 'parse_catalog', '[]'::jsonb, 52428800, TRUE, '{}'::jsonb, NOW())
    ON CONFLICT (extension) DO UPDATE SET label=EXCLUDED.label, category=EXCLUDED.category, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.file_type_definitions (extension, label, category, parse_handler, mime_types, max_bytes, enabled, metadata, updated_at)
    VALUES ('.ndjson', 'NDJSON', 'structured', 'parse_catalog', '[]'::jsonb, 52428800, TRUE, '{}'::jsonb, NOW())
    ON CONFLICT (extension) DO UPDATE SET label=EXCLUDED.label, category=EXCLUDED.category, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.model_catalog (provider_id, model_id, label, capabilities, context_window, input_modalities, output_modalities, is_embedding, is_active, metadata, updated_at)
    VALUES ('01ai', 'yi-lightning', '01.AI (Yi) — yi-lightning', '["chat", "completions"]'::jsonb, NULL, '["text"]'::jsonb, '["text"]'::jsonb, FALSE, TRUE, '{"base_url": "https://api.lingyiwanwu.com/v1"}'::jsonb, NOW())
    ON CONFLICT (provider_id, model_id) DO UPDATE SET label=EXCLUDED.label, capabilities=EXCLUDED.capabilities, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.model_catalog (provider_id, model_id, label, capabilities, context_window, input_modalities, output_modalities, is_embedding, is_active, metadata, updated_at)
    VALUES ('anthropic', 'claude-3-7-sonnet-20250219', 'Anthropic (Claude) — claude-3-7-sonnet-20250219', '["chat", "completions"]'::jsonb, NULL, '["text"]'::jsonb, '["text"]'::jsonb, FALSE, TRUE, '{"base_url": "https://api.anthropic.com"}'::jsonb, NOW())
    ON CONFLICT (provider_id, model_id) DO UPDATE SET label=EXCLUDED.label, capabilities=EXCLUDED.capabilities, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.model_catalog (provider_id, model_id, label, capabilities, context_window, input_modalities, output_modalities, is_embedding, is_active, metadata, updated_at)
    VALUES ('cohere', 'command-r-plus', 'Cohere — command-r-plus', '["chat", "completions", "embeddings"]'::jsonb, NULL, '["text"]'::jsonb, '["text"]'::jsonb, FALSE, TRUE, '{"base_url": "https://api.cohere.com/compatibility/v1"}'::jsonb, NOW())
    ON CONFLICT (provider_id, model_id) DO UPDATE SET label=EXCLUDED.label, capabilities=EXCLUDED.capabilities, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.model_catalog (provider_id, model_id, label, capabilities, context_window, input_modalities, output_modalities, is_embedding, is_active, metadata, updated_at)
    VALUES ('cohere', 'embed-english-v3.0', 'Cohere — embed-english-v3.0', '["embeddings"]'::jsonb, NULL, '["text"]'::jsonb, '["vector"]'::jsonb, TRUE, TRUE, '{}'::jsonb, NOW())
    ON CONFLICT (provider_id, model_id) DO UPDATE SET label=EXCLUDED.label, capabilities=EXCLUDED.capabilities, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.model_catalog (provider_id, model_id, label, capabilities, context_window, input_modalities, output_modalities, is_embedding, is_active, metadata, updated_at)
    VALUES ('dashscope', 'qwen-max', 'Qwen (DashScope) — qwen-max', '["chat", "completions", "embeddings"]'::jsonb, NULL, '["text"]'::jsonb, '["text"]'::jsonb, FALSE, TRUE, '{"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"}'::jsonb, NOW())
    ON CONFLICT (provider_id, model_id) DO UPDATE SET label=EXCLUDED.label, capabilities=EXCLUDED.capabilities, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.model_catalog (provider_id, model_id, label, capabilities, context_window, input_modalities, output_modalities, is_embedding, is_active, metadata, updated_at)
    VALUES ('dashscope', 'text-embedding-v2', 'Qwen (DashScope) — text-embedding-v2', '["embeddings"]'::jsonb, NULL, '["text"]'::jsonb, '["vector"]'::jsonb, TRUE, TRUE, '{}'::jsonb, NOW())
    ON CONFLICT (provider_id, model_id) DO UPDATE SET label=EXCLUDED.label, capabilities=EXCLUDED.capabilities, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.model_catalog (provider_id, model_id, label, capabilities, context_window, input_modalities, output_modalities, is_embedding, is_active, metadata, updated_at)
    VALUES ('deepseek', 'deepseek-chat', 'DeepSeek — deepseek-chat', '["chat", "completions"]'::jsonb, NULL, '["text"]'::jsonb, '["text"]'::jsonb, FALSE, TRUE, '{"base_url": "https://api.deepseek.com"}'::jsonb, NOW())
    ON CONFLICT (provider_id, model_id) DO UPDATE SET label=EXCLUDED.label, capabilities=EXCLUDED.capabilities, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.model_catalog (provider_id, model_id, label, capabilities, context_window, input_modalities, output_modalities, is_embedding, is_active, metadata, updated_at)
    VALUES ('fireworks', 'accounts/fireworks/models/llama-v3p3-70b-instruct', 'Fireworks AI — accounts/fireworks/models/llama-v3p3-70b-instruct', '["chat", "completions", "embeddings"]'::jsonb, NULL, '["text"]'::jsonb, '["text"]'::jsonb, FALSE, TRUE, '{"base_url": "https://api.fireworks.ai/inference/v1"}'::jsonb, NOW())
    ON CONFLICT (provider_id, model_id) DO UPDATE SET label=EXCLUDED.label, capabilities=EXCLUDED.capabilities, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.model_catalog (provider_id, model_id, label, capabilities, context_window, input_modalities, output_modalities, is_embedding, is_active, metadata, updated_at)
    VALUES ('fireworks', 'nomic-ai/nomic-embed-text-v1.5', 'Fireworks AI — nomic-ai/nomic-embed-text-v1.5', '["embeddings"]'::jsonb, NULL, '["text"]'::jsonb, '["vector"]'::jsonb, TRUE, TRUE, '{}'::jsonb, NOW())
    ON CONFLICT (provider_id, model_id) DO UPDATE SET label=EXCLUDED.label, capabilities=EXCLUDED.capabilities, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.model_catalog (provider_id, model_id, label, capabilities, context_window, input_modalities, output_modalities, is_embedding, is_active, metadata, updated_at)
    VALUES ('gemini', 'gemini-2.0-flash', 'Google Gemini — gemini-2.0-flash', '["chat", "completions", "embeddings"]'::jsonb, NULL, '["text"]'::jsonb, '["text"]'::jsonb, FALSE, TRUE, '{"base_url": "https://generativelanguage.googleapis.com/v1beta/openai"}'::jsonb, NOW())
    ON CONFLICT (provider_id, model_id) DO UPDATE SET label=EXCLUDED.label, capabilities=EXCLUDED.capabilities, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.model_catalog (provider_id, model_id, label, capabilities, context_window, input_modalities, output_modalities, is_embedding, is_active, metadata, updated_at)
    VALUES ('gemini', 'text-embedding-004', 'Google Gemini — text-embedding-004', '["embeddings"]'::jsonb, NULL, '["text"]'::jsonb, '["vector"]'::jsonb, TRUE, TRUE, '{}'::jsonb, NOW())
    ON CONFLICT (provider_id, model_id) DO UPDATE SET label=EXCLUDED.label, capabilities=EXCLUDED.capabilities, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.model_catalog (provider_id, model_id, label, capabilities, context_window, input_modalities, output_modalities, is_embedding, is_active, metadata, updated_at)
    VALUES ('grok', 'grok-2-latest', 'Grok (x.ai) — grok-2-latest', '["chat", "completions"]'::jsonb, NULL, '["text"]'::jsonb, '["text"]'::jsonb, FALSE, TRUE, '{"base_url": "https://api.x.ai/v1"}'::jsonb, NOW())
    ON CONFLICT (provider_id, model_id) DO UPDATE SET label=EXCLUDED.label, capabilities=EXCLUDED.capabilities, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.model_catalog (provider_id, model_id, label, capabilities, context_window, input_modalities, output_modalities, is_embedding, is_active, metadata, updated_at)
    VALUES ('groq', 'llama-3.3-70b-versatile', 'Groq — llama-3.3-70b-versatile', '["chat", "completions"]'::jsonb, NULL, '["text"]'::jsonb, '["text"]'::jsonb, FALSE, TRUE, '{"base_url": "https://api.groq.com/openai/v1"}'::jsonb, NOW())
    ON CONFLICT (provider_id, model_id) DO UPDATE SET label=EXCLUDED.label, capabilities=EXCLUDED.capabilities, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.model_catalog (provider_id, model_id, label, capabilities, context_window, input_modalities, output_modalities, is_embedding, is_active, metadata, updated_at)
    VALUES ('huggingface', 'BAAI/bge-small-en-v1.5', 'HuggingFace — BAAI/bge-small-en-v1.5', '["embeddings"]'::jsonb, NULL, '["text"]'::jsonb, '["vector"]'::jsonb, TRUE, TRUE, '{}'::jsonb, NOW())
    ON CONFLICT (provider_id, model_id) DO UPDATE SET label=EXCLUDED.label, capabilities=EXCLUDED.capabilities, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.model_catalog (provider_id, model_id, label, capabilities, context_window, input_modalities, output_modalities, is_embedding, is_active, metadata, updated_at)
    VALUES ('huggingface', 'meta-llama/Llama-3.3-70B-Instruct', 'HuggingFace — meta-llama/Llama-3.3-70B-Instruct', '["chat", "completions", "embeddings"]'::jsonb, NULL, '["text"]'::jsonb, '["text"]'::jsonb, FALSE, TRUE, '{"base_url": "https://api-inference.huggingface.co/v1"}'::jsonb, NOW())
    ON CONFLICT (provider_id, model_id) DO UPDATE SET label=EXCLUDED.label, capabilities=EXCLUDED.capabilities, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.model_catalog (provider_id, model_id, label, capabilities, context_window, input_modalities, output_modalities, is_embedding, is_active, metadata, updated_at)
    VALUES ('lmstudio', 'local-model', 'LM Studio (Local) — local-model', '["chat", "completions", "embeddings"]'::jsonb, NULL, '["text"]'::jsonb, '["text"]'::jsonb, FALSE, TRUE, '{"base_url": "http://localhost:1234/v1"}'::jsonb, NOW())
    ON CONFLICT (provider_id, model_id) DO UPDATE SET label=EXCLUDED.label, capabilities=EXCLUDED.capabilities, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.model_catalog (provider_id, model_id, label, capabilities, context_window, input_modalities, output_modalities, is_embedding, is_active, metadata, updated_at)
    VALUES ('lmstudio', 'text-embedding-nomic-embed-text-v1.5', 'LM Studio (Local) — text-embedding-nomic-embed-text-v1.5', '["embeddings"]'::jsonb, NULL, '["text"]'::jsonb, '["vector"]'::jsonb, TRUE, TRUE, '{}'::jsonb, NOW())
    ON CONFLICT (provider_id, model_id) DO UPDATE SET label=EXCLUDED.label, capabilities=EXCLUDED.capabilities, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.model_catalog (provider_id, model_id, label, capabilities, context_window, input_modalities, output_modalities, is_embedding, is_active, metadata, updated_at)
    VALUES ('mistral', 'mistral-embed', 'Mistral AI — mistral-embed', '["embeddings"]'::jsonb, NULL, '["text"]'::jsonb, '["vector"]'::jsonb, TRUE, TRUE, '{}'::jsonb, NOW())
    ON CONFLICT (provider_id, model_id) DO UPDATE SET label=EXCLUDED.label, capabilities=EXCLUDED.capabilities, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.model_catalog (provider_id, model_id, label, capabilities, context_window, input_modalities, output_modalities, is_embedding, is_active, metadata, updated_at)
    VALUES ('mistral', 'mistral-large-latest', 'Mistral AI — mistral-large-latest', '["chat", "completions", "embeddings"]'::jsonb, NULL, '["text"]'::jsonb, '["text"]'::jsonb, FALSE, TRUE, '{"base_url": "https://api.mistral.ai/v1"}'::jsonb, NOW())
    ON CONFLICT (provider_id, model_id) DO UPDATE SET label=EXCLUDED.label, capabilities=EXCLUDED.capabilities, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.model_catalog (provider_id, model_id, label, capabilities, context_window, input_modalities, output_modalities, is_embedding, is_active, metadata, updated_at)
    VALUES ('moonshot', 'moonshot-v1-8k', 'Moonshot AI (Kimi) — moonshot-v1-8k', '["chat", "completions"]'::jsonb, NULL, '["text"]'::jsonb, '["text"]'::jsonb, FALSE, TRUE, '{"base_url": "https://api.moonshot.cn/v1"}'::jsonb, NOW())
    ON CONFLICT (provider_id, model_id) DO UPDATE SET label=EXCLUDED.label, capabilities=EXCLUDED.capabilities, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.model_catalog (provider_id, model_id, label, capabilities, context_window, input_modalities, output_modalities, is_embedding, is_active, metadata, updated_at)
    VALUES ('novita', 'BAAI/bge-large-en-v1.5', 'Novita AI — BAAI/bge-large-en-v1.5', '["embeddings"]'::jsonb, NULL, '["text"]'::jsonb, '["vector"]'::jsonb, TRUE, TRUE, '{}'::jsonb, NOW())
    ON CONFLICT (provider_id, model_id) DO UPDATE SET label=EXCLUDED.label, capabilities=EXCLUDED.capabilities, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.model_catalog (provider_id, model_id, label, capabilities, context_window, input_modalities, output_modalities, is_embedding, is_active, metadata, updated_at)
    VALUES ('novita', 'meta-llama/llama-3.3-70b-instruct', 'Novita AI — meta-llama/llama-3.3-70b-instruct', '["chat", "completions", "embeddings"]'::jsonb, NULL, '["text"]'::jsonb, '["text"]'::jsonb, FALSE, TRUE, '{"base_url": "https://api.novita.ai/v3/openai"}'::jsonb, NOW())
    ON CONFLICT (provider_id, model_id) DO UPDATE SET label=EXCLUDED.label, capabilities=EXCLUDED.capabilities, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.model_catalog (provider_id, model_id, label, capabilities, context_window, input_modalities, output_modalities, is_embedding, is_active, metadata, updated_at)
    VALUES ('ollama', 'llama3.2', 'Ollama (Local) — llama3.2', '["chat", "completions", "embeddings"]'::jsonb, NULL, '["text"]'::jsonb, '["text"]'::jsonb, FALSE, TRUE, '{"base_url": "http://localhost:11434/v1"}'::jsonb, NOW())
    ON CONFLICT (provider_id, model_id) DO UPDATE SET label=EXCLUDED.label, capabilities=EXCLUDED.capabilities, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.model_catalog (provider_id, model_id, label, capabilities, context_window, input_modalities, output_modalities, is_embedding, is_active, metadata, updated_at)
    VALUES ('ollama', 'nomic-embed-text', 'Ollama (Local) — nomic-embed-text', '["embeddings"]'::jsonb, NULL, '["text"]'::jsonb, '["vector"]'::jsonb, TRUE, TRUE, '{}'::jsonb, NOW())
    ON CONFLICT (provider_id, model_id) DO UPDATE SET label=EXCLUDED.label, capabilities=EXCLUDED.capabilities, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.model_catalog (provider_id, model_id, label, capabilities, context_window, input_modalities, output_modalities, is_embedding, is_active, metadata, updated_at)
    VALUES ('openai', 'gpt-4o-mini', 'OpenAI — gpt-4o-mini', '["chat", "completions", "embeddings"]'::jsonb, NULL, '["text"]'::jsonb, '["text"]'::jsonb, FALSE, TRUE, '{"base_url": "https://api.openai.com/v1"}'::jsonb, NOW())
    ON CONFLICT (provider_id, model_id) DO UPDATE SET label=EXCLUDED.label, capabilities=EXCLUDED.capabilities, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.model_catalog (provider_id, model_id, label, capabilities, context_window, input_modalities, output_modalities, is_embedding, is_active, metadata, updated_at)
    VALUES ('openai', 'text-embedding-3-small', 'OpenAI — text-embedding-3-small', '["embeddings"]'::jsonb, NULL, '["text"]'::jsonb, '["vector"]'::jsonb, TRUE, TRUE, '{}'::jsonb, NOW())
    ON CONFLICT (provider_id, model_id) DO UPDATE SET label=EXCLUDED.label, capabilities=EXCLUDED.capabilities, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.model_catalog (provider_id, model_id, label, capabilities, context_window, input_modalities, output_modalities, is_embedding, is_active, metadata, updated_at)
    VALUES ('openrouter', 'auto', 'OpenRouter — auto', '["chat", "completions", "embeddings"]'::jsonb, NULL, '["text"]'::jsonb, '["text"]'::jsonb, FALSE, TRUE, '{"base_url": "https://openrouter.ai/api/v1"}'::jsonb, NOW())
    ON CONFLICT (provider_id, model_id) DO UPDATE SET label=EXCLUDED.label, capabilities=EXCLUDED.capabilities, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.model_catalog (provider_id, model_id, label, capabilities, context_window, input_modalities, output_modalities, is_embedding, is_active, metadata, updated_at)
    VALUES ('openrouter', 'openai/text-embedding-3-small', 'OpenRouter — openai/text-embedding-3-small', '["embeddings"]'::jsonb, NULL, '["text"]'::jsonb, '["vector"]'::jsonb, TRUE, TRUE, '{}'::jsonb, NOW())
    ON CONFLICT (provider_id, model_id) DO UPDATE SET label=EXCLUDED.label, capabilities=EXCLUDED.capabilities, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.model_catalog (provider_id, model_id, label, capabilities, context_window, input_modalities, output_modalities, is_embedding, is_active, metadata, updated_at)
    VALUES ('perplexity', 'sonar-pro', 'Perplexity AI — sonar-pro', '["chat", "completions"]'::jsonb, NULL, '["text"]'::jsonb, '["text"]'::jsonb, FALSE, TRUE, '{"base_url": "https://api.perplexity.ai"}'::jsonb, NOW())
    ON CONFLICT (provider_id, model_id) DO UPDATE SET label=EXCLUDED.label, capabilities=EXCLUDED.capabilities, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.model_catalog (provider_id, model_id, label, capabilities, context_window, input_modalities, output_modalities, is_embedding, is_active, metadata, updated_at)
    VALUES ('replicate', 'meta/meta-llama-3-70b-instruct', 'Replicate — meta/meta-llama-3-70b-instruct', '["chat", "completions"]'::jsonb, NULL, '["text"]'::jsonb, '["text"]'::jsonb, FALSE, TRUE, '{"base_url": "https://openai-proxy.replicate.com/v1"}'::jsonb, NOW())
    ON CONFLICT (provider_id, model_id) DO UPDATE SET label=EXCLUDED.label, capabilities=EXCLUDED.capabilities, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.model_catalog (provider_id, model_id, label, capabilities, context_window, input_modalities, output_modalities, is_embedding, is_active, metadata, updated_at)
    VALUES ('siliconflow', 'BAAI/bge-large-en-v1.5', 'SiliconFlow — BAAI/bge-large-en-v1.5', '["embeddings"]'::jsonb, NULL, '["text"]'::jsonb, '["vector"]'::jsonb, TRUE, TRUE, '{}'::jsonb, NOW())
    ON CONFLICT (provider_id, model_id) DO UPDATE SET label=EXCLUDED.label, capabilities=EXCLUDED.capabilities, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.model_catalog (provider_id, model_id, label, capabilities, context_window, input_modalities, output_modalities, is_embedding, is_active, metadata, updated_at)
    VALUES ('siliconflow', 'deepseek-ai/DeepSeek-V3', 'SiliconFlow — deepseek-ai/DeepSeek-V3', '["chat", "completions", "embeddings"]'::jsonb, NULL, '["text"]'::jsonb, '["text"]'::jsonb, FALSE, TRUE, '{"base_url": "https://api.siliconflow.cn/v1"}'::jsonb, NOW())
    ON CONFLICT (provider_id, model_id) DO UPDATE SET label=EXCLUDED.label, capabilities=EXCLUDED.capabilities, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.model_catalog (provider_id, model_id, label, capabilities, context_window, input_modalities, output_modalities, is_embedding, is_active, metadata, updated_at)
    VALUES ('together', 'BAAI/bge-large-en-v1.5', 'Together AI — BAAI/bge-large-en-v1.5', '["embeddings"]'::jsonb, NULL, '["text"]'::jsonb, '["vector"]'::jsonb, TRUE, TRUE, '{}'::jsonb, NOW())
    ON CONFLICT (provider_id, model_id) DO UPDATE SET label=EXCLUDED.label, capabilities=EXCLUDED.capabilities, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.model_catalog (provider_id, model_id, label, capabilities, context_window, input_modalities, output_modalities, is_embedding, is_active, metadata, updated_at)
    VALUES ('together', 'meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo', 'Together AI — meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo', '["chat", "completions", "embeddings"]'::jsonb, NULL, '["text"]'::jsonb, '["text"]'::jsonb, FALSE, TRUE, '{"base_url": "https://api.together.xyz/v1"}'::jsonb, NOW())
    ON CONFLICT (provider_id, model_id) DO UPDATE SET label=EXCLUDED.label, capabilities=EXCLUDED.capabilities, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.model_catalog (provider_id, model_id, label, capabilities, context_window, input_modalities, output_modalities, is_embedding, is_active, metadata, updated_at)
    VALUES ('venice', 'default', 'Venice AI — default', '["embeddings"]'::jsonb, NULL, '["text"]'::jsonb, '["vector"]'::jsonb, TRUE, TRUE, '{}'::jsonb, NOW())
    ON CONFLICT (provider_id, model_id) DO UPDATE SET label=EXCLUDED.label, capabilities=EXCLUDED.capabilities, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.model_catalog (provider_id, model_id, label, capabilities, context_window, input_modalities, output_modalities, is_embedding, is_active, metadata, updated_at)
    VALUES ('venice', 'llama-3.3-70b', 'Venice AI — llama-3.3-70b', '["chat", "completions", "embeddings"]'::jsonb, NULL, '["text"]'::jsonb, '["text"]'::jsonb, FALSE, TRUE, '{"base_url": "https://api.venice.ai/api/v1"}'::jsonb, NOW())
    ON CONFLICT (provider_id, model_id) DO UPDATE SET label=EXCLUDED.label, capabilities=EXCLUDED.capabilities, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.model_presets (preset_key, label, description, provider_id, model_id, system_prompt_key, parameters, enabled, metadata, updated_at)
    VALUES ('01ai-default', '01.AI (Yi) Default', 'Provider''s default Conductor chat target.', '01ai', 'yi-lightning', 'default', '{"temperature": 0.6, "max_tokens": 1200}'::jsonb, TRUE, '{}'::jsonb, NOW())
    ON CONFLICT (preset_key) DO UPDATE SET label=EXCLUDED.label, description=EXCLUDED.description, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.model_presets (preset_key, label, description, provider_id, model_id, system_prompt_key, parameters, enabled, metadata, updated_at)
    VALUES ('anthropic-default', 'Anthropic (Claude) Default', 'Provider''s default Conductor chat target.', 'anthropic', 'claude-3-7-sonnet-20250219', 'default', '{"temperature": 0.6, "max_tokens": 1200}'::jsonb, TRUE, '{}'::jsonb, NOW())
    ON CONFLICT (preset_key) DO UPDATE SET label=EXCLUDED.label, description=EXCLUDED.description, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.model_presets (preset_key, label, description, provider_id, model_id, system_prompt_key, parameters, enabled, metadata, updated_at)
    VALUES ('cohere-default', 'Cohere Default', 'Provider''s default Conductor chat target.', 'cohere', 'command-r-plus', 'default', '{"temperature": 0.6, "max_tokens": 1200}'::jsonb, TRUE, '{}'::jsonb, NOW())
    ON CONFLICT (preset_key) DO UPDATE SET label=EXCLUDED.label, description=EXCLUDED.description, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.model_presets (preset_key, label, description, provider_id, model_id, system_prompt_key, parameters, enabled, metadata, updated_at)
    VALUES ('deepseek-default', 'DeepSeek Default', 'Provider''s default Conductor chat target.', 'deepseek', 'deepseek-chat', 'default', '{"temperature": 0.6, "max_tokens": 1200}'::jsonb, TRUE, '{}'::jsonb, NOW())
    ON CONFLICT (preset_key) DO UPDATE SET label=EXCLUDED.label, description=EXCLUDED.description, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.model_presets (preset_key, label, description, provider_id, model_id, system_prompt_key, parameters, enabled, metadata, updated_at)
    VALUES ('fireworks-default', 'Fireworks AI Default', 'Provider''s default Conductor chat target.', 'fireworks', 'accounts/fireworks/models/llama-v3p3-70b-instruct', 'default', '{"temperature": 0.6, "max_tokens": 1200}'::jsonb, TRUE, '{}'::jsonb, NOW())
    ON CONFLICT (preset_key) DO UPDATE SET label=EXCLUDED.label, description=EXCLUDED.description, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.model_presets (preset_key, label, description, provider_id, model_id, system_prompt_key, parameters, enabled, metadata, updated_at)
    VALUES ('gemini-default', 'Google Gemini Default', 'Provider''s default Conductor chat target.', 'gemini', 'gemini-2.0-flash', 'default', '{"temperature": 0.6, "max_tokens": 1200}'::jsonb, TRUE, '{}'::jsonb, NOW())
    ON CONFLICT (preset_key) DO UPDATE SET label=EXCLUDED.label, description=EXCLUDED.description, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.model_presets (preset_key, label, description, provider_id, model_id, system_prompt_key, parameters, enabled, metadata, updated_at)
    VALUES ('grok-default', 'Grok (x.ai) Default', 'Provider''s default Conductor chat target.', 'grok', 'grok-2-latest', 'default', '{"temperature": 0.6, "max_tokens": 1200}'::jsonb, TRUE, '{}'::jsonb, NOW())
    ON CONFLICT (preset_key) DO UPDATE SET label=EXCLUDED.label, description=EXCLUDED.description, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.model_presets (preset_key, label, description, provider_id, model_id, system_prompt_key, parameters, enabled, metadata, updated_at)
    VALUES ('groq-default', 'Groq Default', 'Provider''s default Conductor chat target.', 'groq', 'llama-3.3-70b-versatile', 'default', '{"temperature": 0.6, "max_tokens": 1200}'::jsonb, TRUE, '{}'::jsonb, NOW())
    ON CONFLICT (preset_key) DO UPDATE SET label=EXCLUDED.label, description=EXCLUDED.description, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.model_presets (preset_key, label, description, provider_id, model_id, system_prompt_key, parameters, enabled, metadata, updated_at)
    VALUES ('huggingface-default', 'HuggingFace Default', 'Provider''s default Conductor chat target.', 'huggingface', 'meta-llama/Llama-3.3-70B-Instruct', 'default', '{"temperature": 0.6, "max_tokens": 1200}'::jsonb, TRUE, '{}'::jsonb, NOW())
    ON CONFLICT (preset_key) DO UPDATE SET label=EXCLUDED.label, description=EXCLUDED.description, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.model_presets (preset_key, label, description, provider_id, model_id, system_prompt_key, parameters, enabled, metadata, updated_at)
    VALUES ('lmstudio-default', 'LM Studio (Local) Default', 'Provider''s default Conductor chat target.', 'lmstudio', 'local-model', 'default', '{"temperature": 0.6, "max_tokens": 1200}'::jsonb, TRUE, '{}'::jsonb, NOW())
    ON CONFLICT (preset_key) DO UPDATE SET label=EXCLUDED.label, description=EXCLUDED.description, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.model_presets (preset_key, label, description, provider_id, model_id, system_prompt_key, parameters, enabled, metadata, updated_at)
    VALUES ('mistral-default', 'Mistral AI Default', 'Provider''s default Conductor chat target.', 'mistral', 'mistral-large-latest', 'default', '{"temperature": 0.6, "max_tokens": 1200}'::jsonb, TRUE, '{}'::jsonb, NOW())
    ON CONFLICT (preset_key) DO UPDATE SET label=EXCLUDED.label, description=EXCLUDED.description, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.model_presets (preset_key, label, description, provider_id, model_id, system_prompt_key, parameters, enabled, metadata, updated_at)
    VALUES ('moonshot-default', 'Moonshot AI (Kimi) Default', 'Provider''s default Conductor chat target.', 'moonshot', 'moonshot-v1-8k', 'default', '{"temperature": 0.6, "max_tokens": 1200}'::jsonb, TRUE, '{}'::jsonb, NOW())
    ON CONFLICT (preset_key) DO UPDATE SET label=EXCLUDED.label, description=EXCLUDED.description, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.model_presets (preset_key, label, description, provider_id, model_id, system_prompt_key, parameters, enabled, metadata, updated_at)
    VALUES ('novita-default', 'Novita AI Default', 'Provider''s default Conductor chat target.', 'novita', 'meta-llama/llama-3.3-70b-instruct', 'default', '{"temperature": 0.6, "max_tokens": 1200}'::jsonb, TRUE, '{}'::jsonb, NOW())
    ON CONFLICT (preset_key) DO UPDATE SET label=EXCLUDED.label, description=EXCLUDED.description, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.model_presets (preset_key, label, description, provider_id, model_id, system_prompt_key, parameters, enabled, metadata, updated_at)
    VALUES ('ollama-default', 'Ollama (Local) Default', 'Provider''s default Conductor chat target.', 'ollama', 'llama3.2', 'default', '{"temperature": 0.6, "max_tokens": 1200}'::jsonb, TRUE, '{}'::jsonb, NOW())
    ON CONFLICT (preset_key) DO UPDATE SET label=EXCLUDED.label, description=EXCLUDED.description, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.model_presets (preset_key, label, description, provider_id, model_id, system_prompt_key, parameters, enabled, metadata, updated_at)
    VALUES ('openai-default', 'OpenAI Default', 'Provider''s default Conductor chat target.', 'openai', 'gpt-4o-mini', 'default', '{"temperature": 0.6, "max_tokens": 1200}'::jsonb, TRUE, '{}'::jsonb, NOW())
    ON CONFLICT (preset_key) DO UPDATE SET label=EXCLUDED.label, description=EXCLUDED.description, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.model_presets (preset_key, label, description, provider_id, model_id, system_prompt_key, parameters, enabled, metadata, updated_at)
    VALUES ('openrouter-default', 'OpenRouter Default', 'Provider''s default Conductor chat target.', 'openrouter', 'auto', 'default', '{"temperature": 0.6, "max_tokens": 1200}'::jsonb, TRUE, '{}'::jsonb, NOW())
    ON CONFLICT (preset_key) DO UPDATE SET label=EXCLUDED.label, description=EXCLUDED.description, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.model_presets (preset_key, label, description, provider_id, model_id, system_prompt_key, parameters, enabled, metadata, updated_at)
    VALUES ('perplexity-default', 'Perplexity AI Default', 'Provider''s default Conductor chat target.', 'perplexity', 'sonar-pro', 'default', '{"temperature": 0.6, "max_tokens": 1200}'::jsonb, TRUE, '{}'::jsonb, NOW())
    ON CONFLICT (preset_key) DO UPDATE SET label=EXCLUDED.label, description=EXCLUDED.description, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.model_presets (preset_key, label, description, provider_id, model_id, system_prompt_key, parameters, enabled, metadata, updated_at)
    VALUES ('dashscope-default', 'Qwen (DashScope) Default', 'Provider''s default Conductor chat target.', 'dashscope', 'qwen-max', 'default', '{"temperature": 0.6, "max_tokens": 1200}'::jsonb, TRUE, '{}'::jsonb, NOW())
    ON CONFLICT (preset_key) DO UPDATE SET label=EXCLUDED.label, description=EXCLUDED.description, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.model_presets (preset_key, label, description, provider_id, model_id, system_prompt_key, parameters, enabled, metadata, updated_at)
    VALUES ('replicate-default', 'Replicate Default', 'Provider''s default Conductor chat target.', 'replicate', 'meta/meta-llama-3-70b-instruct', 'default', '{"temperature": 0.6, "max_tokens": 1200}'::jsonb, TRUE, '{}'::jsonb, NOW())
    ON CONFLICT (preset_key) DO UPDATE SET label=EXCLUDED.label, description=EXCLUDED.description, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.model_presets (preset_key, label, description, provider_id, model_id, system_prompt_key, parameters, enabled, metadata, updated_at)
    VALUES ('siliconflow-default', 'SiliconFlow Default', 'Provider''s default Conductor chat target.', 'siliconflow', 'deepseek-ai/DeepSeek-V3', 'default', '{"temperature": 0.6, "max_tokens": 1200}'::jsonb, TRUE, '{}'::jsonb, NOW())
    ON CONFLICT (preset_key) DO UPDATE SET label=EXCLUDED.label, description=EXCLUDED.description, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.model_presets (preset_key, label, description, provider_id, model_id, system_prompt_key, parameters, enabled, metadata, updated_at)
    VALUES ('together-default', 'Together AI Default', 'Provider''s default Conductor chat target.', 'together', 'meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo', 'default', '{"temperature": 0.6, "max_tokens": 1200}'::jsonb, TRUE, '{}'::jsonb, NOW())
    ON CONFLICT (preset_key) DO UPDATE SET label=EXCLUDED.label, description=EXCLUDED.description, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.model_presets (preset_key, label, description, provider_id, model_id, system_prompt_key, parameters, enabled, metadata, updated_at)
    VALUES ('venice-default', 'Venice AI Default', 'Provider''s default Conductor chat target.', 'venice', 'llama-3.3-70b', 'default', '{"temperature": 0.6, "max_tokens": 1200}'::jsonb, TRUE, '{}'::jsonb, NOW())
    ON CONFLICT (preset_key) DO UPDATE SET label=EXCLUDED.label, description=EXCLUDED.description, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.global_filter_definitions (filter_key, label, entity_type, field_path, control_type, options_source, default_value, enabled, sort_order, metadata, updated_at)
    VALUES ('marketplace', 'Marketplace', 'listing', 'marketplace', 'select', '{"dataset": "catalog_products", "field": "market"}'::jsonb, NULL, TRUE, 10, '{}'::jsonb, NOW())
    ON CONFLICT (filter_key) DO UPDATE SET label=EXCLUDED.label, entity_type=EXCLUDED.entity_type, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.global_filter_definitions (filter_key, label, entity_type, field_path, control_type, options_source, default_value, enabled, sort_order, metadata, updated_at)
    VALUES ('brand', 'Brand', 'listing', 'attributes.brand', 'select', '{"dataset": "catalog_products", "field": "attributes.brand"}'::jsonb, NULL, TRUE, 20, '{}'::jsonb, NOW())
    ON CONFLICT (filter_key) DO UPDATE SET label=EXCLUDED.label, entity_type=EXCLUDED.entity_type, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.global_filter_definitions (filter_key, label, entity_type, field_path, control_type, options_source, default_value, enabled, sort_order, metadata, updated_at)
    VALUES ('team', 'Team', 'task', 'team_name', 'select', '{"dataset": "asana_tasks", "field": "team_name"}'::jsonb, NULL, TRUE, 30, '{}'::jsonb, NOW())
    ON CONFLICT (filter_key) DO UPDATE SET label=EXCLUDED.label, entity_type=EXCLUDED.entity_type, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.global_filter_definitions (filter_key, label, entity_type, field_path, control_type, options_source, default_value, enabled, sort_order, metadata, updated_at)
    VALUES ('project', 'Project', 'task', 'project_name', 'select', '{"dataset": "asana_tasks", "field": "project_name"}'::jsonb, NULL, TRUE, 40, '{}'::jsonb, NOW())
    ON CONFLICT (filter_key) DO UPDATE SET label=EXCLUDED.label, entity_type=EXCLUDED.entity_type, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.global_filter_definitions (filter_key, label, entity_type, field_path, control_type, options_source, default_value, enabled, sort_order, metadata, updated_at)
    VALUES ('freshness', 'Freshness', 'listing', 'updated_at', 'age', '{"options": ["fresh", "stale", "missing"]}'::jsonb, NULL, TRUE, 50, '{}'::jsonb, NOW())
    ON CONFLICT (filter_key) DO UPDATE SET label=EXCLUDED.label, entity_type=EXCLUDED.entity_type, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.registry (kind, registry_key, label, description, route, icon, status_key, lifecycle_key, capabilities, metadata, source_hash, created_at, updated_at)
    VALUES ('feature', 'aiworkflows', 'AI Workflows', 'Conductor application feature.', 'ai', 'codicon-sparkle', 'active', 'stable', '[]'::jsonb, '{"view": "ai", "count": "ai"}'::jsonb, '99a301c725f6e416175ebb5a1c9875f1e2173ccce19a0c85098888d7b0640bd7', NOW(), NOW())
    ON CONFLICT (kind, registry_key) DO UPDATE SET label=EXCLUDED.label, route=EXCLUDED.route, icon=EXCLUDED.icon, metadata=EXCLUDED.metadata, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.registry (kind, registry_key, label, description, route, icon, status_key, lifecycle_key, capabilities, metadata, source_hash, created_at, updated_at)
    VALUES ('feature', 'tasks', 'Action Queue', 'Conductor application feature.', 'tasks', 'codicon-checklist', 'active', 'stable', '[]'::jsonb, '{"view": "tasks", "count": "tasks"}'::jsonb, '1eb384e171c9bac314975d9f6e324cea8f70495935304c5b0fead72700004578', NOW(), NOW())
    ON CONFLICT (kind, registry_key) DO UPDATE SET label=EXCLUDED.label, route=EXCLUDED.route, icon=EXCLUDED.icon, metadata=EXCLUDED.metadata, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.registry (kind, registry_key, label, description, route, icon, status_key, lifecycle_key, capabilities, metadata, source_hash, created_at, updated_at)
    VALUES ('feature', 'agency', 'Agency', 'Conductor application feature.', 'agency', 'codicon-globe', 'active', 'stable', '[]'::jsonb, '{"view": "agency", "count": null}'::jsonb, '872a53e6c382599f55588297b8919992ea36060ed16eda96063323e133cd29c4', NOW(), NOW())
    ON CONFLICT (kind, registry_key) DO UPDATE SET label=EXCLUDED.label, route=EXCLUDED.route, icon=EXCLUDED.icon, metadata=EXCLUDED.metadata, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.registry (kind, registry_key, label, description, route, icon, status_key, lifecycle_key, capabilities, metadata, source_hash, created_at, updated_at)
    VALUES ('feature', 'agentbuilder', 'Agent Builder', 'Conductor application feature.', 'agentbuilder', 'codicon-rocket', 'active', 'stable', '[]'::jsonb, '{"view": "agentbuilder", "count": null}'::jsonb, '6a0a4890e2a5006bcea7850a260ac6dff54f56c2ed612e54df08982719a7df63', NOW(), NOW())
    ON CONFLICT (kind, registry_key) DO UPDATE SET label=EXCLUDED.label, route=EXCLUDED.route, icon=EXCLUDED.icon, metadata=EXCLUDED.metadata, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.registry (kind, registry_key, label, description, route, icon, status_key, lifecycle_key, capabilities, metadata, source_hash, created_at, updated_at)
    VALUES ('feature', 'agents', 'Agents', 'Conductor application feature.', 'agents', 'codicon-robot', 'active', 'stable', '[]'::jsonb, '{"view": "agents", "count": "agents"}'::jsonb, 'affbf487d3487756bf01adc8b7bed9c3c1f9c0ed6e32271f56592ea4a650fe4a', NOW(), NOW())
    ON CONFLICT (kind, registry_key) DO UPDATE SET label=EXCLUDED.label, route=EXCLUDED.route, icon=EXCLUDED.icon, metadata=EXCLUDED.metadata, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.registry (kind, registry_key, label, description, route, icon, status_key, lifecycle_key, capabilities, metadata, source_hash, created_at, updated_at)
    VALUES ('feature', 'amazon', 'Amazon', 'Conductor application feature.', 'amazon', 'codicon-globe', 'active', 'stable', '[]'::jsonb, '{"view": "amazon", "count": null}'::jsonb, 'a5aeca0077cffe2394189f1e2c2289195badd1773b9a91c69f93c788ab645942', NOW(), NOW())
    ON CONFLICT (kind, registry_key) DO UPDATE SET label=EXCLUDED.label, route=EXCLUDED.route, icon=EXCLUDED.icon, metadata=EXCLUDED.metadata, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.registry (kind, registry_key, label, description, route, icon, status_key, lifecycle_key, capabilities, metadata, source_hash, created_at, updated_at)
    VALUES ('feature', 'asana', 'Asana', 'Conductor application feature.', 'asana', 'codicon-organization', 'active', 'stable', '[]'::jsonb, '{"view": "asana", "count": "asana"}'::jsonb, 'e145da2cbd536ec228ad116641790a27da8c3380c03ae819052b7bdb6902ac22', NOW(), NOW())
    ON CONFLICT (kind, registry_key) DO UPDATE SET label=EXCLUDED.label, route=EXCLUDED.route, icon=EXCLUDED.icon, metadata=EXCLUDED.metadata, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.registry (kind, registry_key, label, description, route, icon, status_key, lifecycle_key, capabilities, metadata, source_hash, created_at, updated_at)
    VALUES ('feature', 'asanarules', 'Asana Rules Canvas', 'Conductor application feature.', 'asanarules', 'codicon-rules', 'active', 'stable', '[]'::jsonb, '{"view": "asanarules", "count": null}'::jsonb, '3891319a712d0e3b04dead45d5f124417827d47bc2b84d5d9caa53ac87a060e3', NOW(), NOW())
    ON CONFLICT (kind, registry_key) DO UPDATE SET label=EXCLUDED.label, route=EXCLUDED.route, icon=EXCLUDED.icon, metadata=EXCLUDED.metadata, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.registry (kind, registry_key, label, description, route, icon, status_key, lifecycle_key, capabilities, metadata, source_hash, created_at, updated_at)
    VALUES ('feature', 'attraudit', 'Attribute Audit', 'Conductor application feature.', 'attraudit', 'codicon-verified', 'active', 'stable', '[]'::jsonb, '{"view": "attraudit", "count": null}'::jsonb, 'd9f28b8ec9aa8d70899dd905313404727b8a190aadb4a9da2f7ae6cefdca6c62', NOW(), NOW())
    ON CONFLICT (kind, registry_key) DO UPDATE SET label=EXCLUDED.label, route=EXCLUDED.route, icon=EXCLUDED.icon, metadata=EXCLUDED.metadata, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.registry (kind, registry_key, label, description, route, icon, status_key, lifecycle_key, capabilities, metadata, source_hash, created_at, updated_at)
    VALUES ('feature', 'automations', 'Automations', 'Conductor application feature.', 'automations', 'codicon-zap', 'active', 'stable', '[]'::jsonb, '{"view": "automations", "count": "automations"}'::jsonb, '657719d07021b21057cade7c75b2cb00c6552e79a5a9d73e701a300c597f7fab', NOW(), NOW())
    ON CONFLICT (kind, registry_key) DO UPDATE SET label=EXCLUDED.label, route=EXCLUDED.route, icon=EXCLUDED.icon, metadata=EXCLUDED.metadata, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.registry (kind, registry_key, label, description, route, icon, status_key, lifecycle_key, capabilities, metadata, source_hash, created_at, updated_at)
    VALUES ('feature', 'brandcompare', 'Brand Compare', 'Conductor application feature.', 'brandcompare', 'codicon-telescope', 'active', 'stable', '[]'::jsonb, '{"view": "brandcompare", "count": null}'::jsonb, '9856faa45c48163c991fba4024c04855443a8a2bebd1d55e4252df9a39b2ca6d', NOW(), NOW())
    ON CONFLICT (kind, registry_key) DO UPDATE SET label=EXCLUDED.label, route=EXCLUDED.route, icon=EXCLUDED.icon, metadata=EXCLUDED.metadata, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.registry (kind, registry_key, label, description, route, icon, status_key, lifecycle_key, capabilities, metadata, source_hash, created_at, updated_at)
    VALUES ('feature', 'brands', 'Brands', 'Conductor application feature.', 'brands', 'codicon-briefcase', 'active', 'stable', '[]'::jsonb, '{"view": "brands", "count": null}'::jsonb, '75284dcc8e28e3e62bb4399f3b405bdd4691a2bb4dc84d9e32b9204fb6bae871', NOW(), NOW())
    ON CONFLICT (kind, registry_key) DO UPDATE SET label=EXCLUDED.label, route=EXCLUDED.route, icon=EXCLUDED.icon, metadata=EXCLUDED.metadata, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.registry (kind, registry_key, label, description, route, icon, status_key, lifecycle_key, capabilities, metadata, source_hash, created_at, updated_at)
    VALUES ('feature', 'import', 'Bulk Import', 'Conductor application feature.', 'import', 'codicon-cloud-upload', 'active', 'stable', '[]'::jsonb, '{"view": "import", "count": null}'::jsonb, 'f0078453a37efe8deb789f1a963f1018415b29089acb7f816c7ea1fbcdfa953e', NOW(), NOW())
    ON CONFLICT (kind, registry_key) DO UPDATE SET label=EXCLUDED.label, route=EXCLUDED.route, icon=EXCLUDED.icon, metadata=EXCLUDED.metadata, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.registry (kind, registry_key, label, description, route, icon, status_key, lifecycle_key, capabilities, metadata, source_hash, created_at, updated_at)
    VALUES ('feature', 'case', 'Case', 'Conductor application feature.', 'case', 'codicon-issue-opened', 'active', 'stable', '[]'::jsonb, '{"view": "case", "count": null}'::jsonb, 'df8f3de5ea5e5387d938e7a95ef5a3e210a323e0dc8cab8e9b77d3a43b3e5f0d', NOW(), NOW())
    ON CONFLICT (kind, registry_key) DO UPDATE SET label=EXCLUDED.label, route=EXCLUDED.route, icon=EXCLUDED.icon, metadata=EXCLUDED.metadata, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.registry (kind, registry_key, label, description, route, icon, status_key, lifecycle_key, capabilities, metadata, source_hash, created_at, updated_at)
    VALUES ('feature', 'ingest', 'Catalog Ingest', 'Conductor application feature.', 'ingest', 'codicon-cloud-upload', 'active', 'stable', '[]'::jsonb, '{"view": "ingest", "count": "files"}'::jsonb, 'd990b0bec0ee1cd4e880b004b27201905de80fa3fb631a1eed02ff4d2ccfb060', NOW(), NOW())
    ON CONFLICT (kind, registry_key) DO UPDATE SET label=EXCLUDED.label, route=EXCLUDED.route, icon=EXCLUDED.icon, metadata=EXCLUDED.metadata, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.registry (kind, registry_key, label, description, route, icon, status_key, lifecycle_key, capabilities, metadata, source_hash, created_at, updated_at)
    VALUES ('feature', 'chat', 'Chat', 'Conductor application feature.', 'chat', 'codicon-comment-discussion', 'active', 'stable', '[]'::jsonb, '{"view": "chat", "count": null}'::jsonb, '954d3c3b9ff5628518dd60121a3172f0352e213921ded3744e102a3e20d8efdb', NOW(), NOW())
    ON CONFLICT (kind, registry_key) DO UPDATE SET label=EXCLUDED.label, route=EXCLUDED.route, icon=EXCLUDED.icon, metadata=EXCLUDED.metadata, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.registry (kind, registry_key, label, description, route, icon, status_key, lifecycle_key, capabilities, metadata, source_hash, created_at, updated_at)
    VALUES ('feature', 'coastal', 'Coastal', 'Conductor application feature.', 'coastal', 'codicon-globe', 'active', 'stable', '[]'::jsonb, '{"view": "coastal", "count": null}'::jsonb, '196284eff23d5e0613f1632094b53695378ea97f5a00afb1ff35a87bca1032ef', NOW(), NOW())
    ON CONFLICT (kind, registry_key) DO UPDATE SET label=EXCLUDED.label, route=EXCLUDED.route, icon=EXCLUDED.icon, metadata=EXCLUDED.metadata, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.registry (kind, registry_key, label, description, route, icon, status_key, lifecycle_key, capabilities, metadata, source_hash, created_at, updated_at)
    VALUES ('feature', 'compliance', 'Compliance', 'Conductor application feature.', 'checks', 'codicon-shield', 'active', 'stable', '[]'::jsonb, '{"view": "checks", "count": "checks"}'::jsonb, 'e6623732cbd33334c5b0fd917a76f2ec09a3aac9ec66a814bd1d52e45ee4de02', NOW(), NOW())
    ON CONFLICT (kind, registry_key) DO UPDATE SET label=EXCLUDED.label, route=EXCLUDED.route, icon=EXCLUDED.icon, metadata=EXCLUDED.metadata, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.registry (kind, registry_key, label, description, route, icon, status_key, lifecycle_key, capabilities, metadata, source_hash, created_at, updated_at)
    VALUES ('feature', 'content', 'Content', 'Conductor application feature.', 'content', 'codicon-notebook', 'active', 'stable', '[]'::jsonb, '{"view": "content", "count": null}'::jsonb, 'b63ebecf57539901be4e45016aff91f3b61cb8f47e14ec4c90d40de66fde4eaf', NOW(), NOW())
    ON CONFLICT (kind, registry_key) DO UPDATE SET label=EXCLUDED.label, route=EXCLUDED.route, icon=EXCLUDED.icon, metadata=EXCLUDED.metadata, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.registry (kind, registry_key, label, description, route, icon, status_key, lifecycle_key, capabilities, metadata, source_hash, created_at, updated_at)
    VALUES ('feature', 'customerservice', 'Customer Service', 'Conductor application feature.', 'customerservice', 'codicon-person', 'active', 'stable', '[]'::jsonb, '{"view": "customerservice", "count": null}'::jsonb, '327cb9631d93e1b31ecd2682b52646a5ba549a4dd4ef6403e804d94353ca1a99', NOW(), NOW())
    ON CONFLICT (kind, registry_key) DO UPDATE SET label=EXCLUDED.label, route=EXCLUDED.route, icon=EXCLUDED.icon, metadata=EXCLUDED.metadata, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.registry (kind, registry_key, label, description, route, icon, status_key, lifecycle_key, capabilities, metadata, source_hash, created_at, updated_at)
    VALUES ('feature', 'dashboard', 'Dashboard', 'Conductor application feature.', 'dashboard', 'codicon-dashboard', 'active', 'stable', '[]'::jsonb, '{"view": "dashboard", "count": null}'::jsonb, '56ab5cd0449e6b2574e86d0d83a798aef00eb205b9c390e87b12a840fc107a7d', NOW(), NOW())
    ON CONFLICT (kind, registry_key) DO UPDATE SET label=EXCLUDED.label, route=EXCLUDED.route, icon=EXCLUDED.icon, metadata=EXCLUDED.metadata, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.registry (kind, registry_key, label, description, route, icon, status_key, lifecycle_key, capabilities, metadata, source_hash, created_at, updated_at)
    VALUES ('feature', 'data', 'Data Management', 'Conductor application feature.', 'data', 'codicon-database', 'active', 'stable', '[]'::jsonb, '{"view": "data", "count": null}'::jsonb, 'd9b8c0eb5b74429691704f86c71ddbc71e969ef42dd4959f956eecca1e07eb92', NOW(), NOW())
    ON CONFLICT (kind, registry_key) DO UPDATE SET label=EXCLUDED.label, route=EXCLUDED.route, icon=EXCLUDED.icon, metadata=EXCLUDED.metadata, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.registry (kind, registry_key, label, description, route, icon, status_key, lifecycle_key, capabilities, metadata, source_hash, created_at, updated_at)
    VALUES ('feature', 'datawrangler', 'DataWrangler', 'Conductor application feature.', 'datawrangler', 'codicon-table', 'active', 'stable', '[]'::jsonb, '{"view": "datawrangler", "count": null}'::jsonb, 'dcdb99205b3a2943f5bdc48fea04b56fa7776be60502b5a317ef32b202d98dd6', NOW(), NOW())
    ON CONFLICT (kind, registry_key) DO UPDATE SET label=EXCLUDED.label, route=EXCLUDED.route, icon=EXCLUDED.icon, metadata=EXCLUDED.metadata, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.registry (kind, registry_key, label, description, route, icon, status_key, lifecycle_key, capabilities, metadata, source_hash, created_at, updated_at)
    VALUES ('feature', 'developer', 'Developer', 'Conductor application feature.', 'developer', 'codicon-wrench', 'active', 'stable', '[]'::jsonb, '{"view": "developer", "count": null}'::jsonb, 'a87a34cb8f964fee2c0a1a8d347e838fc00ef4801c111ec6f17fad3c6dae9ef9', NOW(), NOW())
    ON CONFLICT (kind, registry_key) DO UPDATE SET label=EXCLUDED.label, route=EXCLUDED.route, icon=EXCLUDED.icon, metadata=EXCLUDED.metadata, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.registry (kind, registry_key, label, description, route, icon, status_key, lifecycle_key, capabilities, metadata, source_hash, created_at, updated_at)
    VALUES ('feature', 'events', 'Events', 'Conductor application feature.', 'events', 'codicon-radio-tower', 'active', 'stable', '[]'::jsonb, '{"view": "events", "count": "events"}'::jsonb, '1adfb88f5a8d671ce6c7b1e8a7bce74cf049d7f878dbd250132cd2a34b65e8a1', NOW(), NOW())
    ON CONFLICT (kind, registry_key) DO UPDATE SET label=EXCLUDED.label, route=EXCLUDED.route, icon=EXCLUDED.icon, metadata=EXCLUDED.metadata, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.registry (kind, registry_key, label, description, route, icon, status_key, lifecycle_key, capabilities, metadata, source_hash, created_at, updated_at)
    VALUES ('feature', 'fba', 'FBA', 'Conductor application feature.', 'fba', 'codicon-package', 'active', 'stable', '[]'::jsonb, '{"view": "fba", "count": null}'::jsonb, '16e325befda508a0afe6aa9e7e483f70305f572e2213f0d4dd673191505c8667', NOW(), NOW())
    ON CONFLICT (kind, registry_key) DO UPDATE SET label=EXCLUDED.label, route=EXCLUDED.route, icon=EXCLUDED.icon, metadata=EXCLUDED.metadata, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.registry (kind, registry_key, label, description, route, icon, status_key, lifecycle_key, capabilities, metadata, source_hash, created_at, updated_at)
    VALUES ('feature', 'features', 'Feature Studio', 'Conductor application feature.', 'features', 'codicon-beaker', 'active', 'stable', '[]'::jsonb, '{"view": "features", "count": null}'::jsonb, 'acfa0884f8a769ec29fbb52a5073062578307df880653956a74536967e1e7be8', NOW(), NOW())
    ON CONFLICT (kind, registry_key) DO UPDATE SET label=EXCLUDED.label, route=EXCLUDED.route, icon=EXCLUDED.icon, metadata=EXCLUDED.metadata, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.registry (kind, registry_key, label, description, route, icon, status_key, lifecycle_key, capabilities, metadata, source_hash, created_at, updated_at)
    VALUES ('feature', 'flatfile', 'Flat Files', 'Conductor application feature.', 'flatfile', 'codicon-table', 'active', 'stable', '[]'::jsonb, '{"view": "flatfile", "count": null}'::jsonb, '671d86bb22c475e8e684189714a8e373f83dcbfa487a5cdb7d97097cace9f266', NOW(), NOW())
    ON CONFLICT (kind, registry_key) DO UPDATE SET label=EXCLUDED.label, route=EXCLUDED.route, icon=EXCLUDED.icon, metadata=EXCLUDED.metadata, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.registry (kind, registry_key, label, description, route, icon, status_key, lifecycle_key, capabilities, metadata, source_hash, created_at, updated_at)
    VALUES ('feature', 'bernie', 'Flow Canvas', 'Conductor application feature.', 'bernie', 'codicon-graph', 'active', 'stable', '[]'::jsonb, '{"view": "bernie", "count": null}'::jsonb, 'a00a26e90ac178734ce39f6e2e75b36f28a91e0304cdf2d7d6c49393006f03e5', NOW(), NOW())
    ON CONFLICT (kind, registry_key) DO UPDATE SET label=EXCLUDED.label, route=EXCLUDED.route, icon=EXCLUDED.icon, metadata=EXCLUDED.metadata, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.registry (kind, registry_key, label, description, route, icon, status_key, lifecycle_key, capabilities, metadata, source_hash, created_at, updated_at)
    VALUES ('feature', 'guidelines', 'Guidelines', 'Conductor application feature.', 'guidelines', 'codicon-symbol-property', 'active', 'stable', '[]'::jsonb, '{"view": "guidelines", "count": null}'::jsonb, 'afbb23f764d722edffe3086454cf290ea75f1f3cd44393d3955bcea122bb9f89', NOW(), NOW())
    ON CONFLICT (kind, registry_key) DO UPDATE SET label=EXCLUDED.label, route=EXCLUDED.route, icon=EXCLUDED.icon, metadata=EXCLUDED.metadata, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.registry (kind, registry_key, label, description, route, icon, status_key, lifecycle_key, capabilities, metadata, source_hash, created_at, updated_at)
    VALUES ('feature', 'requests', 'HTTP', 'Conductor application feature.', 'requests', 'codicon-arrow-swap', 'active', 'stable', '[]'::jsonb, '{"view": "requests", "count": "requests"}'::jsonb, '51659bfd612cf56c3c3832bfb15ee645af1b994a27ac400a15d51ef1907cbe67', NOW(), NOW())
    ON CONFLICT (kind, registry_key) DO UPDATE SET label=EXCLUDED.label, route=EXCLUDED.route, icon=EXCLUDED.icon, metadata=EXCLUDED.metadata, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.registry (kind, registry_key, label, description, route, icon, status_key, lifecycle_key, capabilities, metadata, source_hash, created_at, updated_at)
    VALUES ('feature', 'insights', 'Insights', 'Conductor application feature.', 'insights', 'codicon-graph', 'active', 'stable', '[]'::jsonb, '{"view": "insights", "count": null}'::jsonb, '1ee28f48497237b6f253a0793aa57e9fe50017a603b4efb4853f926900b52e59', NOW(), NOW())
    ON CONFLICT (kind, registry_key) DO UPDATE SET label=EXCLUDED.label, route=EXCLUDED.route, icon=EXCLUDED.icon, metadata=EXCLUDED.metadata, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.registry (kind, registry_key, label, description, route, icon, status_key, lifecycle_key, capabilities, metadata, source_hash, created_at, updated_at)
    VALUES ('feature', 'integrations', 'Integrations', 'Conductor application feature.', 'integrations', 'codicon-plug', 'active', 'stable', '[]'::jsonb, '{"view": "integrations", "count": null}'::jsonb, '490a2dfc6589254d56e5cc9a5c8b5af6954ebe0d2e0749d4c47854e6fdeda36c', NOW(), NOW())
    ON CONFLICT (kind, registry_key) DO UPDATE SET label=EXCLUDED.label, route=EXCLUDED.route, icon=EXCLUDED.icon, metadata=EXCLUDED.metadata, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.registry (kind, registry_key, label, description, route, icon, status_key, lifecycle_key, capabilities, metadata, source_hash, created_at, updated_at)
    VALUES ('feature', 'kpi', 'KPI Studio', 'Conductor application feature.', 'kpi', 'codicon-graph-line', 'active', 'stable', '[]'::jsonb, '{"view": "kpi", "count": null}'::jsonb, '30b6e5208e0457e9833fd992ea27817e00a867a407ebb8cc528245fdcf99730b', NOW(), NOW())
    ON CONFLICT (kind, registry_key) DO UPDATE SET label=EXCLUDED.label, route=EXCLUDED.route, icon=EXCLUDED.icon, metadata=EXCLUDED.metadata, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.registry (kind, registry_key, label, description, route, icon, status_key, lifecycle_key, capabilities, metadata, source_hash, created_at, updated_at)
    VALUES ('feature', 'keepa', 'Keepa', 'Conductor application feature.', 'keepa', 'codicon-graph-line', 'active', 'stable', '[]'::jsonb, '{"view": "keepa", "count": null}'::jsonb, '5d0093905cbde0f471b4a6e5116680445cbe3fd5372f94f03d70ae93e34bb4e1', NOW(), NOW())
    ON CONFLICT (kind, registry_key) DO UPDATE SET label=EXCLUDED.label, route=EXCLUDED.route, icon=EXCLUDED.icon, metadata=EXCLUDED.metadata, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.registry (kind, registry_key, label, description, route, icon, status_key, lifecycle_key, capabilities, metadata, source_hash, created_at, updated_at)
    VALUES ('feature', 'listings', 'Listings', 'Conductor application feature.', 'listings', 'codicon-list-unordered', 'active', 'stable', '[]'::jsonb, '{"view": "listings", "count": null}'::jsonb, '704af572c0e8b7fb4b49ad80dfba833706b865af96ea74bbd5378120a26e7efc', NOW(), NOW())
    ON CONFLICT (kind, registry_key) DO UPDATE SET label=EXCLUDED.label, route=EXCLUDED.route, icon=EXCLUDED.icon, metadata=EXCLUDED.metadata, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.registry (kind, registry_key, label, description, route, icon, status_key, lifecycle_key, capabilities, metadata, source_hash, created_at, updated_at)
    VALUES ('feature', 'sources', 'Local Sources', 'Conductor application feature.', 'sources', 'codicon-folder-opened', 'active', 'stable', '[]'::jsonb, '{"view": "sources", "count": null}'::jsonb, 'd01925a8208b6c38d5394279dad748da77bbbf15d340503e60c54e55980761d5', NOW(), NOW())
    ON CONFLICT (kind, registry_key) DO UPDATE SET label=EXCLUDED.label, route=EXCLUDED.route, icon=EXCLUDED.icon, metadata=EXCLUDED.metadata, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.registry (kind, registry_key, label, description, route, icon, status_key, lifecycle_key, capabilities, metadata, source_hash, created_at, updated_at)
    VALUES ('feature', 'models', 'Models', 'Conductor application feature.', 'models', 'codicon-hubot', 'active', 'stable', '[]'::jsonb, '{"view": "models", "count": null}'::jsonb, '59a4745f8ada9d3c8700c95497d5467832f46f37356bf64a6a0754dca81e33a8', NOW(), NOW())
    ON CONFLICT (kind, registry_key) DO UPDATE SET label=EXCLUDED.label, route=EXCLUDED.route, icon=EXCLUDED.icon, metadata=EXCLUDED.metadata, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.registry (kind, registry_key, label, description, route, icon, status_key, lifecycle_key, capabilities, metadata, source_hash, created_at, updated_at)
    VALUES ('feature', 'people', 'People', 'Conductor application feature.', 'people', 'codicon-organization', 'active', 'stable', '[]'::jsonb, '{"view": "people", "count": null}'::jsonb, '7fe25bf8f4fcb27e56166cf18c3c4b8dc74649243e68635627915829dd4274a8', NOW(), NOW())
    ON CONFLICT (kind, registry_key) DO UPDATE SET label=EXCLUDED.label, route=EXCLUDED.route, icon=EXCLUDED.icon, metadata=EXCLUDED.metadata, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.registry (kind, registry_key, label, description, route, icon, status_key, lifecycle_key, capabilities, metadata, source_hash, created_at, updated_at)
    VALUES ('feature', 'policies', 'Policies', 'Conductor application feature.', 'policies', 'codicon-library', 'active', 'stable', '[]'::jsonb, '{"view": "policies", "count": null}'::jsonb, '3344e364a12b5422b55416208ed86225dd4f0a8748168abff5724f00390108be', NOW(), NOW())
    ON CONFLICT (kind, registry_key) DO UPDATE SET label=EXCLUDED.label, route=EXCLUDED.route, icon=EXCLUDED.icon, metadata=EXCLUDED.metadata, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.registry (kind, registry_key, label, description, route, icon, status_key, lifecycle_key, capabilities, metadata, source_hash, created_at, updated_at)
    VALUES ('feature', 'processes', 'Process Discovery', 'Conductor application feature.', 'processes', 'codicon-lightbulb', 'active', 'stable', '[]'::jsonb, '{"view": "processes", "count": "processes"}'::jsonb, '2901bc0bc83c3d59fef5248695c52cea380dfd70f767f684f0ff00f36de64852', NOW(), NOW())
    ON CONFLICT (kind, registry_key) DO UPDATE SET label=EXCLUDED.label, route=EXCLUDED.route, icon=EXCLUDED.icon, metadata=EXCLUDED.metadata, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.registry (kind, registry_key, label, description, route, icon, status_key, lifecycle_key, capabilities, metadata, source_hash, created_at, updated_at)
    VALUES ('feature', 'products', 'Products', 'Conductor application feature.', 'products', 'codicon-package', 'active', 'stable', '[]'::jsonb, '{"view": "products", "count": "products"}'::jsonb, '34101ba144ce9745a4ed13915f9772589c487c086b2dcb7b40476e9a1e08b587', NOW(), NOW())
    ON CONFLICT (kind, registry_key) DO UPDATE SET label=EXCLUDED.label, route=EXCLUDED.route, icon=EXCLUDED.icon, metadata=EXCLUDED.metadata, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.registry (kind, registry_key, label, description, route, icon, status_key, lifecycle_key, capabilities, metadata, source_hash, created_at, updated_at)
    VALUES ('feature', 'regs', 'Regulations', 'Conductor application feature.', 'regs', 'codicon-law', 'active', 'stable', '[]'::jsonb, '{"view": "regs", "count": null}'::jsonb, '7d3bd05ef1a816c4c8419385aad6fda7fb266f5f83e886550a2730daf5082830', NOW(), NOW())
    ON CONFLICT (kind, registry_key) DO UPDATE SET label=EXCLUDED.label, route=EXCLUDED.route, icon=EXCLUDED.icon, metadata=EXCLUDED.metadata, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.registry (kind, registry_key, label, description, route, icon, status_key, lifecycle_key, capabilities, metadata, source_hash, created_at, updated_at)
    VALUES ('feature', 'reports', 'Reports', 'Conductor application feature.', 'reports', 'codicon-report', 'active', 'stable', '[]'::jsonb, '{"view": "reports", "count": null}'::jsonb, 'e50d247d575fb3687cd1e1c0e3eb17aa77d63adf1aefb6b002002554122b0ac6', NOW(), NOW())
    ON CONFLICT (kind, registry_key) DO UPDATE SET label=EXCLUDED.label, route=EXCLUDED.route, icon=EXCLUDED.icon, metadata=EXCLUDED.metadata, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.registry (kind, registry_key, label, description, route, icon, status_key, lifecycle_key, capabilities, metadata, source_hash, created_at, updated_at)
    VALUES ('feature', 'runbooks', 'Runbooks', 'Conductor application feature.', 'runbooks', 'codicon-notebook', 'active', 'stable', '[]'::jsonb, '{"view": "runbooks", "count": null}'::jsonb, '492ac3d175e34d48b1f8b414a159135906e3f9a81bf8d17a16ad282c5750c9c4', NOW(), NOW())
    ON CONFLICT (kind, registry_key) DO UPDATE SET label=EXCLUDED.label, route=EXCLUDED.route, icon=EXCLUDED.icon, metadata=EXCLUDED.metadata, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.registry (kind, registry_key, label, description, route, icon, status_key, lifecycle_key, capabilities, metadata, source_hash, created_at, updated_at)
    VALUES ('feature', 'sops', 'SOPs', 'Conductor application feature.', 'sops', 'codicon-book', 'active', 'stable', '[]'::jsonb, '{"view": "sops", "count": "sops"}'::jsonb, '9f56fd31a09bf39b069831b9c3f40bc97e01be39e23e58d2a452a37a898e7d6d', NOW(), NOW())
    ON CONFLICT (kind, registry_key) DO UPDATE SET label=EXCLUDED.label, route=EXCLUDED.route, icon=EXCLUDED.icon, metadata=EXCLUDED.metadata, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.registry (kind, registry_key, label, description, route, icon, status_key, lifecycle_key, capabilities, metadata, source_hash, created_at, updated_at)
    VALUES ('feature', 'spapi', 'SP-API', 'Conductor application feature.', 'productpipeline', 'codicon-git-merge', 'active', 'stable', '[]'::jsonb, '{"view": "productpipeline", "count": null}'::jsonb, 'ee752a0067bce7b12e42a345558efa26b22d3d2c8991bf51156adb2d4e33b886', NOW(), NOW())
    ON CONFLICT (kind, registry_key) DO UPDATE SET label=EXCLUDED.label, route=EXCLUDED.route, icon=EXCLUDED.icon, metadata=EXCLUDED.metadata, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.registry (kind, registry_key, label, description, route, icon, status_key, lifecycle_key, capabilities, metadata, source_hash, created_at, updated_at)
    VALUES ('feature', 'spp', 'SPP', 'Conductor application feature.', 'spp', 'codicon-globe', 'active', 'stable', '[]'::jsonb, '{"view": "spp", "count": null}'::jsonb, '9d7558e37776ef74fb0912b3617dd5217b5a4ff5d22601d1767e47ceb2c4f8f9', NOW(), NOW())
    ON CONFLICT (kind, registry_key) DO UPDATE SET label=EXCLUDED.label, route=EXCLUDED.route, icon=EXCLUDED.icon, metadata=EXCLUDED.metadata, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.registry (kind, registry_key, label, description, route, icon, status_key, lifecycle_key, capabilities, metadata, source_hash, created_at, updated_at)
    VALUES ('feature', 'settings', 'Settings', 'Conductor application feature.', 'settings', 'codicon-settings-gear', 'active', 'stable', '[]'::jsonb, '{"view": "settings", "count": null}'::jsonb, '0b8598498cd2d7fa6119cd57aab1983cf73ba5e95eed6cb20430fa75ffbebeaa', NOW(), NOW())
    ON CONFLICT (kind, registry_key) DO UPDATE SET label=EXCLUDED.label, route=EXCLUDED.route, icon=EXCLUDED.icon, metadata=EXCLUDED.metadata, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.registry (kind, registry_key, label, description, route, icon, status_key, lifecycle_key, capabilities, metadata, source_hash, created_at, updated_at)
    VALUES ('feature', 'svl', 'SvL Comparison', 'Conductor application feature.', 'svl', 'codicon-arrow-swap', 'active', 'stable', '[]'::jsonb, '{"view": "svl", "count": null}'::jsonb, '8ff7fc1d2ef0153ce954a2ba8b49a6a2c98fa7e6754e7fed9f76dad78da2e350', NOW(), NOW())
    ON CONFLICT (kind, registry_key) DO UPDATE SET label=EXCLUDED.label, route=EXCLUDED.route, icon=EXCLUDED.icon, metadata=EXCLUDED.metadata, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.registry (kind, registry_key, label, description, route, icon, status_key, lifecycle_key, capabilities, metadata, source_hash, created_at, updated_at)
    VALUES ('feature', 'mcpsync', 'Sync Center', 'Conductor application feature.', 'mcpsync', 'codicon-server-process', 'active', 'stable', '[]'::jsonb, '{"view": "mcpsync", "count": null}'::jsonb, 'a6b969f4a43db832147540a482263c3670e28cedc2b87fdc30554d770a743335', NOW(), NOW())
    ON CONFLICT (kind, registry_key) DO UPDATE SET label=EXCLUDED.label, route=EXCLUDED.route, icon=EXCLUDED.icon, metadata=EXCLUDED.metadata, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.registry (kind, registry_key, label, description, route, icon, status_key, lifecycle_key, capabilities, metadata, source_hash, created_at, updated_at)
    VALUES ('feature', 'target', 'Target', 'Conductor application feature.', 'target', 'codicon-globe', 'active', 'stable', '[]'::jsonb, '{"view": "target", "count": null}'::jsonb, '0435b2d08a154451b20317d4a6cec5bde3890d49c8dfa38058153e3a7f0a6558', NOW(), NOW())
    ON CONFLICT (kind, registry_key) DO UPDATE SET label=EXCLUDED.label, route=EXCLUDED.route, icon=EXCLUDED.icon, metadata=EXCLUDED.metadata, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.registry (kind, registry_key, label, description, route, icon, status_key, lifecycle_key, capabilities, metadata, source_hash, created_at, updated_at)
    VALUES ('feature', 'tiktok', 'TikTok', 'Conductor application feature.', 'tiktok', 'codicon-globe', 'active', 'stable', '[]'::jsonb, '{"view": "tiktok", "count": null}'::jsonb, '0ecfab2687d51c241f6dc6a55521f9916f06ee70076de157fbecd7aec25d0b4c', NOW(), NOW())
    ON CONFLICT (kind, registry_key) DO UPDATE SET label=EXCLUDED.label, route=EXCLUDED.route, icon=EXCLUDED.icon, metadata=EXCLUDED.metadata, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.registry (kind, registry_key, label, description, route, icon, status_key, lifecycle_key, capabilities, metadata, source_hash, created_at, updated_at)
    VALUES ('feature', 'variations', 'Variations', 'Conductor application feature.', 'variation', 'codicon-versions', 'active', 'stable', '[]'::jsonb, '{"view": "variation", "count": null}'::jsonb, 'c3bb716031af57961a6ae86388322350d4ce7ff9543053183215deaee63417d1', NOW(), NOW())
    ON CONFLICT (kind, registry_key) DO UPDATE SET label=EXCLUDED.label, route=EXCLUDED.route, icon=EXCLUDED.icon, metadata=EXCLUDED.metadata, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.registry (kind, registry_key, label, description, route, icon, status_key, lifecycle_key, capabilities, metadata, source_hash, created_at, updated_at)
    VALUES ('feature', 'walmart', 'Walmart', 'Conductor application feature.', 'walmart', 'codicon-globe', 'active', 'stable', '[]'::jsonb, '{"view": "walmart", "count": null}'::jsonb, 'bd8d713f595a8f0bdf25f11a4fcc935046fec3ea4d9f061b14d2e23d40cc2e44', NOW(), NOW())
    ON CONFLICT (kind, registry_key) DO UPDATE SET label=EXCLUDED.label, route=EXCLUDED.route, icon=EXCLUDED.icon, metadata=EXCLUDED.metadata, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.registry (kind, registry_key, label, description, route, icon, status_key, lifecycle_key, capabilities, metadata, source_hash, created_at, updated_at)
    VALUES ('feature', 'workflowbuilder', 'Workflow Builder', 'Conductor application feature.', 'automations', 'codicon-circuit-board', 'active', 'stable', '[]'::jsonb, '{"view": "automations", "count": null}'::jsonb, '70ac63412787d206972e15a696596cf69dba7ae6370681358afdc9dda624bccb', NOW(), NOW())
    ON CONFLICT (kind, registry_key) DO UPDATE SET label=EXCLUDED.label, route=EXCLUDED.route, icon=EXCLUDED.icon, metadata=EXCLUDED.metadata, updated_at=EXCLUDED.updated_at;
    

    INSERT INTO conductor.registry (kind, registry_key, label, description, route, icon, status_key, lifecycle_key, capabilities, metadata, source_hash, created_at, updated_at)
    VALUES ('feature', 'workflows', 'Workflows', 'Conductor application feature.', 'workflows', 'codicon-git-merge', 'active', 'stable', '[]'::jsonb, '{"view": "workflows", "count": null}'::jsonb, '089bdbef97339678d80d7eed5f9c6a6553a62b9d5548058bba8429f00b5c7ab3', NOW(), NOW())
    ON CONFLICT (kind, registry_key) DO UPDATE SET label=EXCLUDED.label, route=EXCLUDED.route, icon=EXCLUDED.icon, metadata=EXCLUDED.metadata, updated_at=EXCLUDED.updated_at;
    