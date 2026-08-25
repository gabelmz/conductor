"""Product tagging: tags column, tag-filtered catalog reads, tag list, and the
sticky per-module tag preference backed by the settings store."""
from __future__ import annotations

import threading

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import storage
import settings
from backend import data


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "conductor.db")
    monkeypatch.setattr(storage, "UPLOAD_DIR", tmp_path / "uploads")
    storage._local = threading.local()  # fresh per-thread conns for this DB
    storage.init_db()
    return tmp_path


@pytest.fixture()
def client(db):
    app = FastAPI()
    app.include_router(data.router)
    return TestClient(app)


@pytest.fixture()
def catalog(client):
    a = storage.create_product("SKU-A", "Widget A", tags=["keepa", "suggested content"])
    b = storage.create_product("SKU-B", "Widget B", tags=["all listings report"])
    c = storage.create_product("SKU-C", "Widget C", tags=[])
    d = storage.create_product("SKU-D", "Widget D", tags=["keepa"])
    return {"a": a, "b": b, "c": c, "d": d}


def test_tags_roundtrip_through_storage(catalog):
    a = storage.get_product(catalog["a"])
    assert a["tags"] == ["keepa", "suggested content"]
    # update_product replaces tags
    storage.update_product(catalog["a"], tags=["keepa"])
    assert storage.get_product(catalog["a"])["tags"] == ["keepa"]
    # create_product sanitizes entries
    pid = storage.create_product("SKU-E", "Widget E", tags=[" keepa ", "", "x"])
    assert storage.get_product(pid)["tags"] == ["keepa", "x"]


def test_list_tags_aggregates_and_sorts(catalog):
    tags = storage.list_tags()
    by_tag = {t["tag"]: t["count"] for t in tags}
    assert by_tag == {"keepa": 2, "all listings report": 1, "suggested content": 1}
    # most frequent first, then alphabetical
    assert tags[0]["tag"] == "keepa"


def test_list_products_tag_filter(catalog):
    rows = storage.list_products(limit=100, tag="keepa")
    assert sorted(r["sku"] for r in rows) == ["SKU-A", "SKU-D"]
    assert storage.list_products(limit=100, tag="nope") == []


def test_table_tag_filter(client, catalog):
    resp = client.get("/api/data/table", params={"source": "products", "tag": "keepa"})
    assert resp.status_code == 200
    rows = resp.json()["rows"]
    assert sorted(r["sku"] for r in rows) == ["SKU-A", "SKU-D"]
    assert all("keepa" in r["tags"] for r in rows)
    # untagged products still listed when no filter
    all_rows = client.get("/api/data/table", params={"source": "products"}).json()["rows"]
    assert len(all_rows) == 4


def test_sources_include_tags(client, catalog):
    resp = client.get("/api/data/sources")
    products = next(s for s in resp.json() if s["id"] == "products")
    assert {t["tag"] for t in products["tags"]} == {"keepa", "suggested content", "all listings report"}
    assert "tags" in products["columns"]


def test_tagpref_sticky_through_settings_store(db):
    assert settings.get("tagPref.data") == "all"          # baseline default
    assert settings.set("tagPref.data", "keepa") == "keepa"
    assert settings.get("tagPref.data") == "keepa"        # delta wins
    assert settings.resolve()["tagPref.data"] == "keepa"
    assert settings.reset("tagPref.data") == "all"        # back to baseline
    assert settings.get("tagPref.data") == "all"
