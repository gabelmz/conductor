from fastapi.testclient import TestClient

from main import app


client = TestClient(app)


def test_spine_snapshot_exposes_local_first_catalog():
    response = client.get("/api/spine/snapshot")
    assert response.status_code == 200
    snapshot = response.json()

    assert len(snapshot["registry"]) >= 8
    assert len(snapshot["models"]) >= 20
    assert {node["node_type"] for node in snapshot["nodes"]} >= {
        "trigger", "http", "ai", "sheet", "drive", "flush"
    }
    assert {dataset["dataset_key"] for dataset in snapshot["datasets"]} >= {
        "catalog_products", "keepa_products", "asana_tasks", "suggested_content", "live_listing_content"
    }


def test_spine_configuration_never_requires_a_secret_value():
    body = {"value": {"default_model_preset": "openai-default"}, "secret_refs": ["provider-key:openai"]}
    saved = client.put("/api/spine/config/chat/default", json=body)
    assert saved.status_code == 200

    loaded = client.get("/api/spine/config/chat/default")
    assert loaded.status_code == 200
    assert loaded.json()["value"] == body["value"]
    assert loaded.json()["secret_refs"] == body["secret_refs"]


def test_spine_glossary_filters_local_registry():
    response = client.get("/api/spine/glossary", params={"q": "Keepa", "kind": "feature"})
    assert response.status_code == 200
    assert response.json()["count"] >= 1
