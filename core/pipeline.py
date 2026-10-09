"""End-to-end pipeline:
Upload -> Validate -> OCR/Text -> Classify -> Extract -> Store -> Verify -> Anomaly -> AI analysis
-> Workflow decision -> (Review) -> Audit.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

from . import analysis, anomaly, classifier, database, extraction, processing, rag, storage, validation, workflow
from .errors import DocFlowError, FileValidationError

log = logging.getLogger("docflow")


def _timed(timings: dict, name: str, fn, *args):
    start = time.perf_counter()
    try:
        return fn(*args)
    finally:
        timings[name] = round((time.perf_counter() - start) * 1000)


def _fail(doc_id: int, actor: str, message: str, timings: dict | None = None) -> dict:
    before = (database.get_document(doc_id) or {}).get("status")
    database.update_document(doc_id, status="failed", error=message, timings=timings or {})
    database.log_audit(doc_id, actor, "processing_failed", before, "failed", message)
    return {"ok": False, "duplicate": False, "doc_id": doc_id, "status": "failed", "message": message}


def _run(doc_id: int, path: Path, ext: str, actor: str) -> dict:
    timings: dict = {}
    started = time.perf_counter()
    try:
        result = _timed(timings, "text_ms", processing.extract_text, path, ext)
        if len(result.text.split()) < 3:
            return _fail(doc_id, actor, "No readable text was found in this document.", timings)

        cls = _timed(timings, "classify_ms", classifier.classify, result.text)
        ext_result = _timed(timings, "extract_ms", extraction.extract_fields, cls.label, result.text)
        identifier = extraction.identifier_for(cls.label, ext_result.fields)

        issues = _timed(timings, "validate_ms", validation.validate, cls.label, ext_result.fields) if cls.label != "unknown" else []
        flags = _timed(timings, "anomaly_ms", anomaly.detect, doc_id, cls.label, ext_result.fields, identifier) if cls.label != "unknown" else []

        next_status, reason = workflow.decide(cls.label, cls.confidence, ext_result.confidence, issues, flags)
        summary = analysis.summarize(cls.label, ext_result.fields, issues, flags, reason)
        _timed(timings, "index_ms", rag.index_document, doc_id, result.text)

        timings["total_ms"] = round((time.perf_counter() - started) * 1000)
        database.update_document(
            doc_id, category=cls.label, class_conf=cls.confidence, extract_conf=ext_result.confidence,
            text=result.text, text_method=result.method, pages=result.pages, fields=ext_result.fields,
            validation=issues, anomalies=flags, analysis=summary, identifier=identifier,
            workflow_reason=reason, error=None, processing_ms=timings["total_ms"], timings=timings,
        )
        database.log_audit(doc_id, actor, "processed", "processing", None,
                           f"type={cls.label} ({cls.confidence:.0%}), text via {result.method}")
        workflow.transition(doc_id, next_status, "workflow-engine", reason)
        return {"ok": True, "duplicate": False, "doc_id": doc_id, "status": next_status, "message": reason}
    except DocFlowError as exc:
        return _fail(doc_id, actor, str(exc), timings)
    except Exception:  # never leak a traceback to the user
        log.exception("Unexpected failure processing document %s", doc_id)
        return _fail(doc_id, actor, "Something went wrong while processing this document.", timings)


def process_upload(filename: str, data: bytes, actor: str = "user") -> dict:
    """Process one uploaded file. Always returns a result dict instead of raising."""
    database.init_db()
    display = storage.clean_display_name(filename)
    sha = storage.sha256_bytes(data) if data else ""

    # Duplicate check first: never reprocess a document we already hold.
    if sha:
        existing = database.find_by_hash(sha)
        if existing:
            database.log_audit(existing["id"], actor, "duplicate_upload", detail=f"'{display}' matches existing document #{existing['id']}")
            return {"ok": True, "duplicate": True, "doc_id": existing["id"], "status": existing["status"],
                    "message": f"Duplicate of document #{existing['id']} ({existing['original_name']}); stored results were reused."}

    try:
        ext = storage.validate_upload(display, data)
    except FileValidationError as exc:
        if not sha:
            database.log_audit(None, actor, "upload_rejected", detail=f"{display}: {exc}")
            return {"ok": False, "duplicate": False, "doc_id": None, "status": "failed", "message": str(exc)}
        doc_id = database.create_document(display, None, Path(display).suffix.lower(), sha, len(data), "processing")
        database.log_audit(doc_id, actor, "uploaded", None, "processing", display)
        return _fail(doc_id, actor, str(exc))

    stored_name, path = storage.save_file(data, ext)
    doc_id = database.create_document(display, stored_name, ext, sha, len(data))
    database.log_audit(doc_id, actor, "uploaded", None, "processing", display)
    return _run(doc_id, path, ext, actor)


def process_batch(files: list[tuple[str, bytes]], actor: str = "user") -> list[dict]:
    """Process several files; one failure never stops the rest."""
    results = []
    for name, data in files:
        try:
            res = process_upload(name, data, actor)
        except Exception:
            log.exception("Batch item failed: %s", name)
            res = {"ok": False, "duplicate": False, "doc_id": None, "status": "failed",
                   "message": "Unexpected error while processing this file."}
        res["filename"] = name
        results.append(res)
    return results


def reprocess(doc_id: int, actor: str = "user") -> dict:
    doc = database.get_document(doc_id)
    if not doc:
        return {"ok": False, "message": f"Document #{doc_id} was not found.", "status": "failed", "doc_id": doc_id, "duplicate": False}
    if not doc.get("stored_name"):
        return {"ok": False, "message": "This upload was rejected and has no stored file to retry.", "status": doc["status"], "doc_id": doc_id, "duplicate": False}
    workflow.transition(doc_id, "processing", actor, "Retry requested")
    return _run(doc_id, storage.safe_path(doc["stored_name"]), doc["ext"], actor)
