"""Tests for backend/parsers.py's .docx/.pdf/.xlsb catalog parsing —
previously untested, which is exactly how their missing dependencies
(python-docx, pdfplumber, pyxlsb) went unnoticed for so long.
"""
from __future__ import annotations

import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR / "backend"))

import parsers


def test_parse_catalog_docx_round_trip(tmp_path):
    import docx

    doc = docx.Document()
    table = doc.add_table(rows=2, cols=2)
    table.rows[0].cells[0].text = "SKU"
    table.rows[0].cells[1].text = "Title"
    table.rows[1].cells[0].text = "ABC-123"
    table.rows[1].cells[1].text = "Widget"
    docx_path = tmp_path / "catalog.docx"
    doc.save(docx_path)

    rows = parsers.parse_catalog(docx_path, "catalog.docx")

    assert len(rows) == 1
    assert rows[0]["sku"] == "ABC-123"


def test_parse_catalog_pdf_missing_or_malformed_degrades_to_empty(tmp_path):
    """Not a real PDF (building a genuine one needs a PDF-writer dependency
    this project doesn't otherwise need) — proves the defensive try/except
    around the pdfplumber import+parse degrades to [] instead of raising,
    which is the behavior that actually matters for a corrupt upload."""
    bad_pdf = tmp_path / "not-a-real.pdf"
    bad_pdf.write_bytes(b"%PDF-1.4 not actually a valid pdf")

    rows = parsers.parse_catalog(bad_pdf, "not-a-real.pdf")

    assert rows == []


def test_pdfplumber_is_actually_importable():
    """The dependency itself must be installed — this is what was missing."""
    import pdfplumber  # noqa: F401


def test_pyxlsb_is_actually_importable():
    import pyxlsb  # noqa: F401


def test_parse_catalog_xlsb_malformed_degrades_to_empty_not_raises(tmp_path):
    """_parse_xlsb's import used to be unguarded — a missing pyxlsb would
    raise ModuleNotFoundError straight out of parse_catalog. Now wrapped to
    match the pdf/docx parsers' defensive pattern; a malformed file (or a
    missing package) must degrade to [] instead of propagating."""
    bad_xlsb = tmp_path / "not-a-real.xlsb"
    bad_xlsb.write_bytes(b"not a real xlsb file")

    rows = parsers.parse_catalog(bad_xlsb, "not-a-real.xlsb")

    assert rows == []
