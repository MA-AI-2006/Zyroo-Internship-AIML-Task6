"""Category-specific structured field extraction with a per-document confidence score."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

AMOUNT = r"\$?\s*([0-9]{1,3}(?:,[0-9]{3})+(?:\.\d{1,2})?|[0-9]+(?:\.\d{1,2})?)"
DATE = (
    r"(\d{4}-\d{2}-\d{2}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.? \d{1,2},? \d{4}|"
    r"\d{1,2} (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{4})"
)

# Fields required per category (also used by validation).
REQUIRED_FIELDS: dict[str, list[str]] = {
    "invoice": ["invoice_number", "date", "vendor", "total"],
    "receipt": ["merchant", "date", "total"],
    "purchase_order": ["po_number", "date", "supplier", "total"],
    "resume": ["name", "email", "skills"],
    "contract": ["parties", "effective_date"],
}


@dataclass
class Extraction:
    fields: dict
    confidence: float
    missing: list[str] = field(default_factory=list)


def _num(s: str | None) -> float | None:
    if s is None:
        return None
    try:
        return float(s.replace(",", "").replace("$", "").strip())
    except ValueError:
        return None


def _search(pattern: str, text: str, flags=re.I) -> str | None:
    m = re.search(pattern, text, flags)
    return m.group(1).strip() if m else None


def _first_line(text: str) -> str | None:
    for line in text.splitlines():
        line = line.strip()
        if len(line) > 2:
            return line[:80]
    return None


def _amount_after(label_pattern: str, text: str) -> float | None:
    """Find a money value after a label, e.g. 'Total: $1,200.00' (last match wins for totals)."""
    matches = re.findall(label_pattern + r"[^\n\d$]{0,20}" + AMOUNT, text, re.I)
    return _num(matches[-1]) if matches else None


def _line_items(text: str) -> float | None:
    """Sum of lines like 'Widget  2 x 10.00  20.00' is too brittle; sum 'Item ... amount' lines instead."""
    total, found = 0.0, False
    for line in text.splitlines():
        m = re.match(r"^\s*(?:item|line)[^\n]*?" + AMOUNT + r"\s*$", line, re.I)
        if m:
            val = _num(m.group(1))
            if val is not None:
                total += val
                found = True
    return round(total, 2) if found else None


def _extract_invoice(text: str) -> dict:
    return {
        "invoice_number": _search(r"invoice\s*(?:no\.?|number|#)\s*[:#]?\s*([A-Z0-9][A-Z0-9\-/]{2,})", text),
        "date": _search(r"(?:invoice\s*)?date\s*[:\-]?\s*" + DATE, text),
        "due_date": _search(r"due\s*date\s*[:\-]?\s*" + DATE, text),
        "vendor": _search(r"(?:vendor|from|seller|supplier)\s*[:\-]\s*([^\n]+)", text) or _first_line(text),
        "bill_to": _search(r"bill\s*to\s*[:\-]?\s*([^\n]+)", text),
        "subtotal": _amount_after(r"sub\s*-?\s*total", text),
        "tax": _amount_after(r"(?:tax|vat|gst)(?:\s*\(?\d+%?\)?)?", text),
        "total": _amount_after(r"(?:grand\s*total|total\s*due|amount\s*due|total)", text),
        "line_items_sum": _line_items(text),
    }


def _extract_receipt(text: str) -> dict:
    return {
        "merchant": _first_line(text),
        "date": _search(r"date\s*[:\-]?\s*" + DATE, text) or _search(DATE, text),
        "receipt_number": _search(r"(?:receipt|transaction)\s*(?:no\.?|number|id|#)\s*[:#]?\s*([A-Z0-9\-]{3,})", text),
        "payment_method": _search(r"(?:paid by|payment method|payment)\s*[:\-]?\s*(cash|card|visa|mastercard|credit card|debit card)", text),
        "subtotal": _amount_after(r"sub\s*-?\s*total", text),
        "tax": _amount_after(r"(?:tax|vat|gst)(?:\s*\(?\d+%?\)?)?", text),
        "total": _amount_after(r"(?:total\s*paid|grand\s*total|total)", text),
        "line_items_sum": _line_items(text),
    }


def _extract_po(text: str) -> dict:
    return {
        "po_number": _search(r"(?:purchase\s*order|po)\s*(?:no\.?|number|#)\s*[:#]?\s*([A-Z0-9][A-Z0-9\-/]{2,})", text),
        "date": _search(r"order\s*date\s*[:\-]?\s*" + DATE, text) or _search(r"date\s*[:\-]?\s*" + DATE, text),
        "delivery_date": _search(r"delivery\s*date\s*[:\-]?\s*" + DATE, text),
        "supplier": _search(r"(?:supplier|vendor)\s*[:\-]\s*([^\n]+)", text),
        "buyer": _search(r"(?:buyer|requested by)\s*[:\-]\s*([^\n]+)", text),
        "ship_to": _search(r"ship\s*to\s*[:\-]?\s*([^\n]+)", text),
        "subtotal": _amount_after(r"sub\s*-?\s*total", text),
        "tax": _amount_after(r"(?:tax|vat|gst)(?:\s*\(?\d+%?\)?)?", text),
        "total": _amount_after(r"(?:po\s*total|grand\s*total|total)", text),
        "line_items_sum": _line_items(text),
    }


KNOWN_SKILLS = [
    "python", "java", "c++", "javascript", "sql", "machine learning", "deep learning", "nlp", "tensorflow",
    "pytorch", "scikit-learn", "pandas", "numpy", "streamlit", "docker", "git", "excel", "data analysis",
    "computer vision", "react", "html", "css", "flask", "fastapi", "tableau", "power bi", "linux",
]


def _extract_resume(text: str) -> dict:
    low = text.lower()
    skills = sorted({s for s in KNOWN_SKILLS if re.search(r"(?<![a-z])" + re.escape(s) + r"(?![a-z])", low)})
    return {
        "name": _search(r"^(?:name\s*[:\-]\s*)?([A-Z][a-z]+(?: [A-Z][a-z]+){1,3})\s*$", text, re.M)
        or _search(r"name\s*[:\-]\s*([^\n]+)", text),
        "email": _search(r"([\w.+-]+@[\w-]+\.[\w.-]+)", text),
        "phone": _search(r"(\+?\d[\d\s\-()]{8,}\d)", text),
        "skills": skills,
        "education": _search(r"((?:bachelor|master|b\.?sc|m\.?sc|phd)[^\n]{0,80})", text),
    }


def _extract_contract(text: str) -> dict:
    parties = re.findall(r"between\s+(.+?)\s+and\s+(.+?)(?:[,.\n]|\(|$)", text, re.I | re.S)
    party_list = [p.strip() for p in parties[0]] if parties else []
    return {
        "parties": party_list,
        "effective_date": _search(r"effective\s*date\s*[:\-]?\s*" + DATE, text)
        or _search(r"(?:made|entered into)[^\n]*?(?:on|as of)\s*" + DATE, text),
        "term": _search(r"term\s*(?:of (?:this )?agreement)?\s*[:\-]\s*([^\n]+)", text),
        "governing_law": _search(r"governing\s*law\s*[:\-]?\s*([^\n.]+)", text),
        "contract_value": _amount_after(r"(?:contract value|total value|fee|amount)", text),
    }


EXTRACTORS = {
    "invoice": _extract_invoice,
    "receipt": _extract_receipt,
    "purchase_order": _extract_po,
    "resume": _extract_resume,
    "contract": _extract_contract,
}


def _present(v) -> bool:
    return v not in (None, "", [], {})


def extract_fields(category: str, text: str) -> Extraction:
    fn = EXTRACTORS.get(category)
    if not fn:
        return Extraction({}, 0.0, [])
    fields = fn(text)
    required = REQUIRED_FIELDS.get(category, [])
    missing = [f for f in required if not _present(fields.get(f))]
    optional = [k for k in fields if k not in required]
    req_score = (len(required) - len(missing)) / len(required) if required else 1.0
    opt_score = sum(_present(fields[k]) for k in optional) / len(optional) if optional else 1.0
    confidence = round(0.8 * req_score + 0.2 * opt_score, 3)
    return Extraction(fields, confidence, missing)


def identifier_for(category: str, fields: dict) -> str | None:
    """The business identifier used for 'repeated identifier' detection."""
    key = {"invoice": "invoice_number", "receipt": "receipt_number", "purchase_order": "po_number"}.get(category)
    val = fields.get(key) if key else None
    return str(val).upper() if val else None
