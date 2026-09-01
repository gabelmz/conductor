import pytest
from fastapi.testclient import TestClient
from main import app
import providers

client = TestClient(app)


def test_hosted_providers_presets_count():
    assert len(providers.HOSTED_PROVIDERS) >= 20
    preset_ids = set(providers.HOSTED_PROVIDERS.keys())
    required = {
        "openai",
        "anthropic",
        "gemini",
        "openrouter",
        "deepseek",
        "grok",
        "huggingface",
        "venice",
        "groq",
        "together",
        "mistral",
        "perplexity",
        "fireworks",
        "cohere",
        "replicate",
        "siliconflow",
        "dashscope",
        "novita",
        "ollama",
        "lmstudio",
        "moonshot",
        "01ai",
    }
    for req in required:
        assert req in preset_ids, f"Missing expected provider preset: {req}"


def test_list_providers_endpoint():
    res = client.get("/api/chat/providers")
    assert res.status_code == 200
    data = res.json()
    assert "providers" in data
    prov_map = {p["id"]: p for p in data["providers"]}
    assert len(prov_map) >= 20
    assert "gemini" in prov_map
    assert "openrouter" in prov_map
    assert "venice" in prov_map
    assert "huggingface" in prov_map

    gemini = prov_map["gemini"]
    assert gemini["baseUrl"] == "https://generativelanguage.googleapis.com/v1beta/openai"
    assert gemini["defaultModelId"] == "gemini-2.0-flash"
    assert gemini["defaultEmbeddingModel"] == "text-embedding-004"


def test_set_config_with_new_presets():
    res = client.post("/api/chat/config", json={"provider": "openrouter", "model": "anthropic/claude-3.5-sonnet"})
    assert res.status_code == 200
    data = res.json()
    assert data["provider"] == "openrouter"

    res_gemini = client.post("/api/chat/config", json={"provider": "gemini", "model": "gemini-2.0-flash"})
    assert res_gemini.status_code == 200
    assert res_gemini.json()["provider"] == "gemini"


def test_list_models_endpoint():
    res = client.get("/api/chat/models")
    assert res.status_code == 200
    assert "models" in res.json()


def test_embeddings_endpoint_validation():
    res = client.post("/api/chat/embeddings", json={})
    assert res.status_code == 400
    assert "required" in res.json()["detail"].lower()
