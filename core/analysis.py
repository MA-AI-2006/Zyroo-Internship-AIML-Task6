"""Short AI analysis of a processed document (local template summary, optional LLM)."""
from __future__ import annotations

from . import config


def summarize(category: str, fields: dict, validation: list[dict], anomalies: list[dict], decision_reason: str) -> str:
    label = category.replace("_", " ")
    bits = []
    if category in ("invoice", "receipt", "purchase_order"):
        who = fields.get("vendor") or fields.get("merchant") or fields.get("supplier") or "an unknown party"
        total = fields.get("total")
        amount = f" totalling {total:,.2f}" if isinstance(total, (int, float)) else ""
        bits.append(f"This looks like a {label} from {who}{amount}.")
    elif category == "resume":
        skills = fields.get("skills") or []
        bits.append(f"This looks like a resume for {fields.get('name') or 'an unnamed candidate'}"
                    + (f" with skills in {', '.join(skills[:5])}." if skills else "."))
    elif category == "contract":
        parties = fields.get("parties") or []
        bits.append("This looks like a contract" + (f" between {' and '.join(parties)}." if parties else "."))
    else:
        bits.append("The document type could not be determined confidently.")
    errs = [v["message"] for v in validation if v["severity"] == "error"]
    if errs:
        bits.append("Issues: " + " ".join(errs[:3]))
    if anomalies:
        bits.append("Flags: " + " ".join(a["message"] for a in anomalies[:2]))
    bits.append(decision_reason)
    return " ".join(bits)
