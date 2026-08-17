"""Large file ingestion: chunked/resumable uploads + catalog parsing.

Protocol:
  POST /api/ingest/init        -> {"upload_id", "chunk_size", ...}
  PUT  /api/ingest/{id}/chunk/{index}   (raw bytes body)
  GET  /api/ingest/{id}/status -> {"received": [0,1,2,...]}  (resume support)
  POST /api/ingest/{id}/complete -> assembles file, spawns parse job

Files are stored in data/uploads/<upload_id>/ as chunk parts, then
assembled and parsed (Keepa xlsx, CDQ xlsx, Amazon template xlsm,
CSV/JSON/NDJSON) in a background thread, writing products to the DB
and running the compliance engine on each row.
"""
from __future__ import annotations

import threading
import uuid
from pathlib import Path

import storage
from compliance import evaluate_product, overall_score, overall_severity
from parsers import parse_catalog

UPLOAD_DIR = storage.UPLOAD_DIR
DEFAULT_CHUNK_SIZE = 4 * 1024 * 1024  # 4 MB


def init_upload(filename: str, total_size: int, chunk_size: int | None = None) -> dict:
    chunk_size = chunk_size or DEFAULT_CHUNK_SIZE
    upload_id = uuid.uuid4().hex[:12]
    upload_dir = UPLOAD_DIR / upload_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    storage.create_file(upload_id, filename, total_size, chunk_size)
    return {
        "upload_id": upload_id,
        "chunk_size": chunk_size,
        "total_chunks": (total_size + chunk_size - 1) // chunk_size if total_size > 0 else 0,
        "filename": filename,
        "status": "uploading",
    }


def _upload_dir(upload_id: str) -> Path:
    d = UPLOAD_DIR / upload_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_chunk(upload_id: str, index: int, data: bytes) -> dict:
    meta = storage.get_file_by_upload(upload_id)
    if not meta:
        raise KeyError(f"Unknown upload_id {upload_id}")
    if meta["status"] != "uploading":
        raise ValueError(f"Upload {upload_id} already finalised (status={meta['status']})")
    part = _upload_dir(upload_id) / f"chunk_{index:06d}.part"
    part.write_bytes(data)
    received = set(meta["received_chunks"])
    received.add(index)
    storage.update_file(upload_id, received_chunks=sorted(received))
    total = meta["total_size"]
    chunk_size = meta["chunk_size"]
    total_chunks = (total + chunk_size - 1) // chunk_size if total > 0 else 0
    return {
        "upload_id": upload_id,
        "received": sorted(received),
        "progress": round(len(received) / max(total_chunks, 1) * 100, 1),
    }


def upload_status(upload_id: str) -> dict:
    meta = storage.get_file_by_upload(upload_id)
    if not meta:
        raise KeyError(f"Unknown upload_id {upload_id}")
    total = meta["total_size"]
    chunk_size = meta["chunk_size"]
    total_chunks = (total + chunk_size - 1) // chunk_size if total > 0 else 0
    return {
        "upload_id": upload_id,
        "filename": meta["filename"],
        "total_size": total,
        "chunk_size": chunk_size,
        "total_chunks": total_chunks,
        "received": meta["received_chunks"],
        "status": meta["status"],
    }


def assemble(upload_id: str) -> Path:
    """Concatenate received chunk parts into the final file. Returns path."""
    meta = storage.get_file_by_upload(upload_id)
    if not meta:
        raise KeyError(f"Unknown upload_id {upload_id}")
    received = sorted(meta["received_chunks"])
    if not received:
        raise ValueError("No chunks received")
    # Verify contiguity
    expected = list(range(received[0], received[-1] + 1))
    if received != expected:
        raise ValueError(f"Gap in chunks: missing {sorted(set(expected) - set(received))}")
    # Keep the original extension so format-aware parsers (openpyxl etc.)
    # can sniff the file type — a bare .bin name breaks them.
    ext = Path(meta["filename"]).suffix or ".bin"
    final_path = _upload_dir(upload_id) / f"final{ext}"
    with open(final_path, "wb") as out:
        for idx in received:
            part = _upload_dir(upload_id) / f"chunk_{idx:06d}.part"
            with open(part, "rb") as f:
                out.write(f.read())
    return final_path


def complete_upload(upload_id: str) -> dict:
    meta = storage.get_file_by_upload(upload_id)
    if not meta:
        raise KeyError(f"Unknown upload_id {upload_id}")
    if meta["status"] != "uploading":
        raise ValueError(f"Upload {upload_id} already finalised")
    total = meta["total_size"]
    received = meta["received_chunks"]
    chunk_size = meta["chunk_size"]
    total_chunks = (total + chunk_size - 1) // chunk_size if total > 0 else 0
    if total_chunks > 0 and len(received) != total_chunks:
        raise ValueError(f"Incomplete upload: {len(received)}/{total_chunks} chunks")
    path = assemble(upload_id)
    actual = path.stat().st_size
    if actual != total:
        raise ValueError(f"Size mismatch: expected {total}, got {actual}")
    storage.update_file(upload_id, status="ready")
    job_id = storage.create_job("parse_catalog", None)
    storage.update_job(job_id, status="running", progress=0, message="Parsing catalog…")
    threading.Thread(target=_parse_job, args=(job_id, upload_id, path), daemon=True).start()
    return {"upload_id": upload_id, "job_id": job_id, "status": "parsing", "path": str(path)}


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------
def _parse_job(job_id: int, upload_id: str, path: Path) -> None:
    meta = storage.get_file_by_upload(upload_id)
    filename = meta["filename"] if meta else "catalog"
    file_id = meta["id"] if meta else None
    try:
        rows = parse_catalog(path, filename)
        total = len(rows)
        storage.update_job(job_id, progress=0, message=f"Parsed {total} rows — ingesting…")
        for i, row in enumerate(rows):
            try:
                pid = storage.create_product(
                    sku=row["sku"], name=row["name"], category=row["category"],
                    market=row["market"], attributes=row["attributes"], source="file",
                    file_id=file_id,
                )
                run_compliance(pid)
            except Exception as exc:
                storage.update_job(job_id, message=f"Row {i + 1} skipped: {exc}")
            if i % 25 == 0:
                storage.update_job(job_id, progress=round(i / max(total, 1) * 100, 1))
        storage.update_job(job_id, status="done", progress=100,
                           message=f"Ingested {total} products with compliance checks.")
        storage.update_file(upload_id, status="done", record_count=total)
    except Exception as exc:
        storage.update_job(job_id, status="error", message=str(exc))
        storage.update_file(upload_id, status="error", error=str(exc))


def run_compliance(product_id: int) -> dict:
    """Run the compliance engine over a product and persist results."""
    product = storage.get_product(product_id)
    if not product:
        raise KeyError(f"Product {product_id} not found")
    results = evaluate_product(product)
    storage.clear_checks(product_id)
    for res in results:
        storage.save_check(
            product_id=product_id, regulation=res.code, status=res.status,
            severity=res.severity, score=res.score, findings=res.findings,
        )
    return {
        "product_id": product_id,
        "overall_score": overall_score(results),
        "overall_severity": overall_severity(results),
        "regulation_count": len(results),
        "regulations": [r.code for r in results],
    }
