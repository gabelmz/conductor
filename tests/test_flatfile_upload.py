"""Flat File template upload: parse a user-supplied CSV/TSV template into a stored template."""
from __future__ import annotations

import threading

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import storage
from backend import flatfiles


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "conductor.db")
    monkeypatch.setattr(storage, "UPLOAD_DIR", tmp_path / "uploads")
    storage._local = threading.local()  # fresh per-thread conns for this DB
    storage.init_db()
    app = FastAPI()
    app.include_router(flatfiles.router)
    return TestClient(app)


TWO_ROW = ("Item Name,SKU,Price,Quantity\n"
           "item-name,sku,price,quantity\n"
           "Example Widget,EX-1,9.99,10\n")


def test_upload_two_row_template(client):
    resp = client.post("/api/flatfiles/upload",
                       files={"file": ("beauty-us.csv", TWO_ROW, "text/csv")})
    assert resp.status_code == 201
    t = resp.json()
    assert t["name"] == "beauty-us"
    assert t["product_type"] == "Uploaded"
    assert [c["key"] for c in t["columns"]] == ["item-name", "sku", "price", "quantity"]
    assert [c["label"] for c in t["columns"]] == ["Item Name", "SKU", "Price", "Quantity"]
    by_key = {c["key"]: c for c in t["columns"]}
    assert by_key["sku"]["required"] is True
    assert by_key["item-name"]["required"] is False
    assert by_key["item-name"]["example"] == "Example Widget"
    # persisted and listed
    assert any(x["id"] == t["id"] for x in client.get("/api/flatfiles").json())
    # and generates a valid CSV (label row + key row + data row)
    gen = client.post(f"/api/flatfiles/{t['id']}/generate",
                      json={"rows": [{"sku": "EX-1", "item-name": "Example Widget",
                                      "price": "9.99", "quantity": "10"}]})
    assert gen.status_code == 200
    csv_lines = gen.json()["csv"].strip().splitlines()
    assert csv_lines[0] == "Item Name,SKU,Price,Quantity"
    assert csv_lines[1] == "item-name,sku,price,quantity"


def test_upload_single_row_header_derives_keys(client):
    resp = client.post("/api/flatfiles/upload",
                       files={"file": ("keys-only.csv", "sku,item-name,price\n", "text/csv")})
    assert resp.status_code == 201
    t = resp.json()
    assert [c["key"] for c in t["columns"]] == ["sku", "item-name", "price"]
    assert [c["label"] for c in t["columns"]] == ["sku", "item-name", "price"]


def test_upload_tsv(client):
    tsv = "SKU\tItem Name\tPrice\nsku\titem-name\tprice\n"
    resp = client.post("/api/flatfiles/upload",
                       files={"file": ("t.tsv", tsv, "text/tab-separated-values")})
    assert resp.status_code == 201
    assert [c["key"] for c in resp.json()["columns"]] == ["sku", "item-name", "price"]


def test_upload_product_type_form_field(client):
    resp = client.post("/api/flatfiles/upload",
                       data={"product_type": "Beauty"},
                       files={"file": ("beauty.csv", "SKU,Price\nsku,price\n", "text/csv")})
    assert resp.status_code == 201
    assert resp.json()["product_type"] == "Beauty"


def test_upload_empty_rejected(client):
    resp = client.post("/api/flatfiles/upload",
                       files={"file": ("empty.csv", "\n", "text/csv")})
    assert resp.status_code == 400
