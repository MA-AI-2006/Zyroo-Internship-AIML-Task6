"""Workflow engine: states, allowed transitions, routing rules and review actions."""
from __future__ import annotations

from . import config, database
from .errors import NotFoundError, TransitionError

STATES = ["processing", "pending_review", "approved", "rejected", "failed"]

ALLOWED = {
    "processing": {"approved", "pending_review", "failed"},
    "pending_review": {"approved", "rejected"},
    "approved": {"pending_review"},     # reopen
    "rejected": {"pending_review"},     # reopen
    "failed": {"processing"},           # retry
}

STATUS_LABELS = {
    "processing": "Processing",
    "pending_review": "Needs review",
    "approved": "Approved",
    "rejected": "Rejected",
    "failed": "Failed",
}


def decide(category: str, class_conf: float, extract_conf: float, validation: list[dict], anomalies: list[dict]) -> tuple[str, str]:
    """Apply routing rules. Returns (next_status, human-readable reason)."""
    reasons = []
    if category == "unknown":
        reasons.append("document type could not be determined")
    elif class_conf < config.MIN_CLASSIFY_CONFIDENCE:
        reasons.append(f"low classification confidence ({class_conf:.0%})")
    if category != "unknown" and extract_conf < config.MIN_EXTRACT_CONFIDENCE:
        reasons.append(f"low extraction confidence ({extract_conf:.0%})")
    errors = [v for v in validation if v["severity"] == "error"]
    if errors:
        reasons.append(f"{len(errors)} validation error(s)")
    if anomalies:
        reasons.append(f"{len(anomalies)} anomaly flag(s)")
    if reasons:
        return "pending_review", "Manual review required: " + "; ".join(reasons) + "."
    return "approved", "Auto-approved: all checks passed."


def transition(doc_id: int, new_status: str, actor: str, note: str = "") -> dict:
    doc = database.get_document(doc_id)
    if not doc:
        raise NotFoundError(f"Document #{doc_id} was not found.")
    current = doc["status"]
    if new_status not in STATES:
        raise TransitionError(f"Unknown status '{new_status}'.")
    if new_status not in ALLOWED.get(current, set()):
        raise TransitionError(
            f"Cannot move a document from '{STATUS_LABELS.get(current, current)}' to '{STATUS_LABELS.get(new_status, new_status)}'."
        )
    database.update_document(doc_id, status=new_status)
    database.log_audit(doc_id, actor, "status_change", current, new_status, note)
    return database.get_document(doc_id)


def review(doc_id: int, decision: str, actor: str, note: str = "") -> dict:
    """Reviewer action: 'approve' or 'reject'. Rejections must carry a reason."""
    if decision not in ("approve", "reject"):
        raise TransitionError("Decision must be 'approve' or 'reject'.")
    if decision == "reject" and not note.strip():
        raise TransitionError("Please add a reason when rejecting a document.", "note_required")
    target = "approved" if decision == "approve" else "rejected"
    return transition(doc_id, target, actor, note or "Approved by reviewer")
