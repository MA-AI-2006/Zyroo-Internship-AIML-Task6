"""End-to-end tests mirroring the Week 6 'Required Test Cases'."""
import shutil

import pytest
from PIL import Image

from core import database, pipeline, rag, storage, workflow
from core.errors import TransitionError

HAS_TESSERACT = shutil.which("tesseract") is not None


def doc_of(res):
    return database.get_document(res["doc_id"])


# 1. Clean digital PDF ---------------------------------------------------------
def test_clean_digital_pdf_is_auto_approved(upload):
    res = upload("invoice")
    doc = doc_of(res)
    assert res["ok"] and doc["status"] == "approved"
    assert doc["category"] == "invoice"
    assert doc["text_method"] == "digital"
    assert doc["fields"]["invoice_number"] == "INV-1001"
    assert doc["fields"]["total"] == 220.0
    assert doc["validation"] == [] and doc["anomalies"] == []


# 2. Scanned document requiring OCR --------------------------------------------
@pytest.mark.skipif(not HAS_TESSERACT, reason="Tesseract not installed")
def test_scanned_image_uses_ocr(upload):
    res = upload("scanned")
    doc = doc_of(res)
    assert doc["text_method"] == "ocr"
    assert doc["category"] == "invoice"
    assert "INV" in (doc["fields"].get("invoice_number") or "")


@pytest.mark.skipif(not HAS_TESSERACT, reason="Tesseract not installed")
def test_scanned_pdf_uses_ocr(samples, tmp_path):
    pdf_path = tmp_path / "scan.pdf"
    Image.open(samples["scanned"]).convert("RGB").save(pdf_path)
    res = pipeline.process_upload("scan.pdf", pdf_path.read_bytes())
    assert doc_of(res)["text_method"] == "ocr"


# 3. Each supported type -------------------------------------------------------
@pytest.mark.parametrize("key,category,field", [
    ("receipt", "receipt", "total"),
    ("resume", "resume", "email"),
    ("contract", "contract", "effective_date"),
    ("po", "purchase_order", "po_number"),
])
def test_supported_document_types(upload, key, category, field):
    doc = doc_of(upload(key))
    assert doc["category"] == category
    assert doc["fields"][field]


def test_resume_skills_extracted(upload):
    skills = doc_of(upload("resume"))["fields"]["skills"]
    assert "python" in skills and "streamlit" in skills


# 4. Missing required fields ---------------------------------------------------
def test_missing_fields_route_to_review(upload):
    doc = doc_of(upload("invoice_missing"))
    assert doc["status"] == "pending_review"
    assert any(v["code"] == "missing_field" for v in doc["validation"])


# 5. Duplicate document / repeated identifier ----------------------------------
def test_duplicate_file_is_not_reprocessed(upload):
    first = upload("invoice")
    second = upload("invoice_copy")
    assert second["duplicate"] and second["doc_id"] == first["doc_id"]
    assert database.metrics()["total"] == 1
    assert database.metrics()["duplicates"] == 1


def test_repeated_identifier_flags_anomaly(upload):
    upload("invoice")
    doc = doc_of(upload("invoice_dup_id"))
    assert doc["status"] == "pending_review"
    assert any(a["code"] == "duplicate_identifier" for a in doc["anomalies"])


# 6. Unsupported file type -----------------------------------------------------
def test_unsupported_file_type(upload):
    res = upload("unsupported")
    assert not res["ok"] and "Unsupported" in res["message"]
    assert doc_of(res)["status"] == "failed"


# 7. Corrupted / unreadable ----------------------------------------------------
def test_corrupted_pdf_gives_friendly_error(upload):
    res = upload("corrupted")
    assert not res["ok"]
    assert "Traceback" not in res["message"]
    assert "corrupted" in res["message"].lower() or "unreadable" in res["message"].lower()


def test_fake_png_is_rejected(upload):
    res = upload("fake_image")
    assert not res["ok"] and "does not look like" in res["message"]


# 8. Low-confidence classification --------------------------------------------
def test_low_confidence_goes_to_review(upload):
    doc = doc_of(upload("unknown"))
    assert doc["category"] == "unknown"
    assert doc["status"] == "pending_review"


# 9. Arithmetic mismatch -------------------------------------------------------
def test_arithmetic_mismatch_detected(upload):
    doc = doc_of(upload("invoice_mismatch"))
    assert any(v["code"] == "arithmetic_mismatch" for v in doc["validation"])
    assert doc["status"] == "pending_review"


# 10. Invalid workflow transition ---------------------------------------------
def test_invalid_transition_is_blocked(upload):
    res = upload("invoice")  # auto-approved
    with pytest.raises(TransitionError):
        workflow.transition(res["doc_id"], "rejected", "tester")
    with pytest.raises(TransitionError):
        workflow.review(res["doc_id"], "approve", "tester")


def test_rejection_needs_reason_and_audit_is_recorded(upload):
    res = upload("invoice_missing")
    with pytest.raises(TransitionError):
        workflow.review(res["doc_id"], "reject", "reviewer")
    workflow.review(res["doc_id"], "reject", "reviewer", "Incomplete invoice")
    assert doc_of(res)["status"] == "rejected"
    actions = [(a["action"], a["to_status"]) for a in database.get_audit(res["doc_id"])]
    assert ("status_change", "rejected") in actions


def test_reopen_after_decision(upload):
    res = upload("invoice_missing")
    workflow.review(res["doc_id"], "approve", "reviewer")
    workflow.transition(res["doc_id"], "pending_review", "reviewer", "reopen")
    assert doc_of(res)["status"] == "pending_review"


# 11. Mixed-success batch ------------------------------------------------------
def test_mixed_batch_keeps_going(samples):
    names = ["invoice", "corrupted", "receipt", "unsupported", "invoice_copy", "resume"]
    files = [(samples[n].name, samples[n].read_bytes()) for n in names]
    results = pipeline.process_batch(files)
    assert [r["ok"] for r in results] == [True, False, True, False, True, True]
    assert results[4]["duplicate"]


# 12. Restart with stored records ---------------------------------------------
def test_records_survive_restart(upload):
    res = upload("invoice")
    rag._cache.update(key=None, vec=None, matrix=None, chunks=[])  # simulate fresh process
    database.init_db()
    assert database.get_document(res["doc_id"])["fields"]["invoice_number"] == "INV-1001"
    assert rag.ask("What is the invoice number?").answered


# 13/14. Assistant: answerable and unanswerable --------------------------------
def test_assistant_answers_from_document(upload):
    upload("invoice")
    ans = rag.ask("What is the total due on invoice INV-1001?")
    assert ans.answered and "220.00" in ans.text
    assert any("invoice_clean" in h.doc_name for h in ans.hits)


def test_assistant_admits_when_unknown(upload):
    upload("invoice")
    ans = rag.ask("What is the capital of France?")
    assert not ans.answered
    assert ans.text == rag.NO_ANSWER
    assert database.get_question_log()[0]["answered"] == 0  # failure is recorded, not hidden


def test_assistant_with_no_documents():
    assert not rag.ask("What is the total?").answered


def test_cross_document_question(upload):
    upload("invoice")
    upload("po")
    upload("receipt")
    ans = rag.ask("What are the totals on the invoice and the purchase order?")
    assert ans.answered and len({h.doc_id for h in ans.hits}) >= 2


def test_shared_word_alone_is_not_enough(upload):
    upload("invoice")
    ans = rag.ask("How many employees does Acme have?")
    assert not ans.answered


def test_short_supplier_question(upload):
    upload("po")
    ans = rag.ask("Who is the supplier?")
    assert ans.answered and "Initech" in ans.text


# Security / storage -----------------------------------------------------------
def test_path_traversal_blocked():
    with pytest.raises(Exception):
        storage.safe_path("../../etc/passwd")


def test_stored_names_are_generated(upload):
    doc = doc_of(upload("invoice"))
    assert doc["stored_name"] != doc["original_name"] and len(doc["stored_name"]) > 30


def test_display_name_is_sanitised():
    assert storage.clean_display_name("../../evil<script>.pdf") == "evil_script_.pdf"


def test_oversized_file_rejected(monkeypatch):
    from core import config
    monkeypatch.setattr(config, "MAX_FILE_BYTES", 10)
    res = pipeline.process_upload("big.txt", b"x" * 50)
    assert not res["ok"] and "larger" in res["message"]


# Dashboard metrics ------------------------------------------------------------
def test_dashboard_metrics(upload):
    for k in ("invoice", "invoice_missing", "corrupted", "invoice_copy"):
        upload(k)
    m = database.metrics()
    assert m["total"] == 3 and m["failed"] == 1 and m["duplicates"] == 1
    assert m["by_status"].get("approved") == 1 and m["by_status"].get("pending_review") == 1
    assert m["avg_ms"] is not None


def test_retry_failed_document_after_fix(upload):
    res = upload("corrupted")
    retry = pipeline.reprocess(res["doc_id"] or 0)
    assert not retry["ok"]  # still corrupted, but handled gracefully
