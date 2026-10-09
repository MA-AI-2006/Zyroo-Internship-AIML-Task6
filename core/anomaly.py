"""Anomaly detection: repeated identifiers and unusual amounts."""
from __future__ import annotations

from statistics import median

from . import config, database


def detect(doc_id: int, category: str, fields: dict, identifier: str | None) -> list[dict]:
    out: list[dict] = []
    if identifier:
        for other in database.docs_with_identifier(category, identifier, doc_id):
            out.append({
                "code": "duplicate_identifier",
                "message": f"Identifier {identifier} already appears in document #{other['id']} ({other['original_name']}).",
            })
    total = fields.get("total") if fields else None
    if isinstance(total, (int, float)):
        if total >= config.HIGH_AMOUNT_THRESHOLD:
            out.append({"code": "high_amount", "message": f"Total {total:,.2f} is above the review threshold ({config.HIGH_AMOUNT_THRESHOLD:,.0f})."})
        peers = database.category_amounts(category, doc_id)
        if len(peers) >= 3:
            med = median(peers)
            if med > 0 and total > 5 * med:
                out.append({"code": "unusual_amount", "message": f"Total {total:,.2f} is more than 5x the typical {category.replace('_', ' ')} ({med:,.2f})."})
    return out
