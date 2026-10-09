"""Validation: required fields, formats and arithmetic consistency."""
from __future__ import annotations

import re
from datetime import datetime

from . import config
from .extraction import REQUIRED_FIELDS

DATE_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%m-%d-%Y", "%d/%m/%y", "%m/%d/%y",
                "%b %d, %Y", "%b %d %Y", "%B %d, %Y", "%B %d %Y", "%d %b %Y", "%d %B %Y"]


def parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.replace(".", "").strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _issue(severity: str, code: str, message: str) -> dict:
    return {"severity": severity, "code": code, "message": message}


def validate(category: str, fields: dict) -> list[dict]:
    """Return a list of issues. severity is 'error' (forces review) or 'warning'."""
    issues: list[dict] = []
    if not fields:
        return issues

    for name in REQUIRED_FIELDS.get(category, []):
        if fields.get(name) in (None, "", [], {}):
            issues.append(_issue("error", "missing_field", f"Required field '{name}' is missing."))

    for key in ("date", "due_date", "delivery_date", "effective_date"):
        if fields.get(key) and parse_date(fields[key]) is None:
            issues.append(_issue("warning", "bad_date", f"Could not understand date in '{key}': {fields[key]}"))

    d, due = parse_date(fields.get("date")), parse_date(fields.get("due_date"))
    if d and due and due < d:
        issues.append(_issue("error", "date_order", "Due date is earlier than the document date."))

    if category == "resume" and fields.get("email") and not re.fullmatch(r"[\w.+-]+@[\w-]+\.[\w.-]+", fields["email"]):
        issues.append(_issue("error", "bad_email", "Email address looks invalid."))

    total = fields.get("total")
    if isinstance(total, (int, float)) and total <= 0:
        issues.append(_issue("error", "bad_total", "Total must be greater than zero."))

    sub, tax, items = fields.get("subtotal"), fields.get("tax"), fields.get("line_items_sum")
    tol = config.AMOUNT_TOLERANCE
    if all(isinstance(x, (int, float)) for x in (sub, total)):
        expected = sub + (tax if isinstance(tax, (int, float)) else 0.0)
        if abs(expected - total) > max(tol, 0.005 * total):
            issues.append(_issue(
                "error", "arithmetic_mismatch",
                f"Subtotal ({sub:,.2f}) + tax ({(tax or 0):,.2f}) = {expected:,.2f}, but total says {total:,.2f}.",
            ))
    if isinstance(items, (int, float)) and isinstance(sub, (int, float)) and abs(items - sub) > max(tol, 0.005 * sub):
        issues.append(_issue("error", "line_items_mismatch", f"Line items add up to {items:,.2f} but subtotal is {sub:,.2f}."))
    elif isinstance(items, (int, float)) and sub is None and isinstance(total, (int, float)) and tax is None \
            and abs(items - total) > max(tol, 0.005 * total):
        issues.append(_issue("warning", "line_items_mismatch", f"Line items add up to {items:,.2f} but total is {total:,.2f}."))
    return issues
