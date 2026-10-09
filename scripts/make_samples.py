"""Generate sample documents covering every Week 6 test case.

    python scripts/make_samples.py            # writes to sample_docs/
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

INVOICE = """Acme Supplies Ltd
Invoice Number: INV-1001
Invoice Date: 2026-09-01
Due Date: 2026-09-30
Bill To: Zyroo Technologies
Vendor: Acme Supplies Ltd
Item 1 Laptop stand 2 x 50.00 100.00
Item 2 USB hub 1 x 100.00 100.00
Subtotal: 200.00
Tax (10%): 20.00
Total Due: 220.00
Payment terms net 30. Remit to Acme Supplies Ltd bank account."""

INVOICE_DUP_ID = INVOICE.replace("Zyroo Technologies", "Beta Traders").replace("200.00", "300.00").replace("220.00", "330.00").replace("30.00 ", "30.00 ").replace("Tax (10%): 20.00", "Tax (10%): 30.00")

INVOICE_MISSING = """Invoice
Bill To: Zyroo Technologies
Subtotal: 80.00
Payment terms net 30. Please pay within 30 days."""

INVOICE_MISMATCH = """Globex Corporation
Invoice Number: INV-2002
Invoice Date: 2026-09-05
Due Date: 2026-10-05
Bill To: Zyroo Technologies
Vendor: Globex Corporation
Item 1 Consulting hours 500.00
Subtotal: 500.00
Tax (10%): 50.00
Total Due: 900.00
Payment terms net 30."""

RECEIPT = """Green Market Store
Receipt No: R-77421
Date: 2026-09-10
Cashier: Sara
Items purchased:
Item 1 Rice 5kg 12.00
Item 2 Milk 3.50
Subtotal: 15.50
Tax: 0.50
Total Paid: 16.00
Paid by card. Visa ending 4242. Thank you for shopping, come again!"""

RESUME = """Ayesha Khan
ayesha.khan@example.com
+92 300 1234567
Profile Summary
Second-year student with experience in Python, machine learning and data analysis.
Education
Bachelor of Science in Artificial Intelligence, University
Skills
Python, SQL, pandas, scikit-learn, Streamlit, Git
Projects
Document classifier, internship project on NLP.
References available on request. GitHub: github.com/ayesha"""

CONTRACT = """SERVICE AGREEMENT
This agreement is made between Zyroo Technologies and Northwind Pvt Ltd.
Effective Date: 2026-08-01
Term of agreement: 12 months
Scope of work: software development services.
Confidentiality: both parties shall keep information confidential.
Governing law: Laws of Pakistan.
Termination clause: either party may terminate with 30 days notice. Breach of obligations
makes the party liable to indemnify the other. Signature of both parties below."""

PURCHASE_ORDER = """PURCHASE ORDER
PO Number: PO-5001
Order Date: 2026-09-12
Delivery Date: 2026-09-26
Supplier: Initech Hardware
Buyer: Zyroo Procurement
Ship To: Zyroo Technologies, Lahore
Item 1 Monitors 8 x 100.00 800.00
Item 2 Keyboards 4 x 50.00 200.00
Subtotal: 1000.00
Tax: 100.00
PO Total: 1100.00
Approved by: Finance. Authorized signature on file."""

UNKNOWN = "Lorem ipsum dolor sit amet, consectetur adipiscing elit. The quick brown fox jumps over the lazy dog near the river bank."

NOTES = (
    "Project Falcon notes: the shuttle departs at 9am from the main gate. "
    "The warranty on the Laptop stand covers two years. Contact support@acme.example for service."
)


def pdf(path: Path, text: str) -> None:
    c = canvas.Canvas(str(path), pagesize=A4)
    y = 800
    for line in text.splitlines():
        c.setFont("Helvetica", 11)
        c.drawString(50, y, line)
        y -= 18
    c.save()


def image(path: Path, text: str) -> None:
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 26)
    except OSError:
        font = ImageFont.load_default(size=26)
    lines = text.splitlines()
    img = Image.new("RGB", (1400, 60 + 42 * len(lines)), "white")
    d = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        d.text((40, 30 + 42 * i), line, fill="black", font=font)
    img.save(path)


def build(out: Path) -> dict[str, Path]:
    out.mkdir(parents=True, exist_ok=True)
    f = {}
    def add(key, name):
        f[key] = out / name
        return f[key]
    pdf(add("invoice", "invoice_clean.pdf"), INVOICE)
    (out / "invoice_copy.pdf").write_bytes((out / "invoice_clean.pdf").read_bytes()); f["invoice_copy"] = out / "invoice_copy.pdf"
    pdf(add("invoice_dup_id", "invoice_same_number.pdf"), INVOICE_DUP_ID)
    pdf(add("invoice_missing", "invoice_missing_fields.pdf"), INVOICE_MISSING)
    pdf(add("invoice_mismatch", "invoice_arithmetic_mismatch.pdf"), INVOICE_MISMATCH)
    pdf(add("receipt", "receipt.pdf"), RECEIPT)
    pdf(add("resume", "resume.pdf"), RESUME)
    pdf(add("contract", "contract.pdf"), CONTRACT)
    pdf(add("po", "purchase_order.pdf"), PURCHASE_ORDER)
    pdf(add("notes", "project_notes.pdf"), NOTES)
    image(add("scanned", "invoice_scanned.png"), INVOICE.replace("INV-1001", "INV-3003").replace("Zyroo Technologies", "Scan Customer"))
    add("unknown", "random_text.txt").write_text(UNKNOWN)
    add("unsupported", "report.docx").write_bytes(b"PK\x03\x04 not really a docx")
    add("corrupted", "corrupted.pdf").write_bytes(b"%PDF-1.4\n\x00\x01garbage that is not a pdf at all\xff\xfe")
    add("fake_image", "fake.png").write_bytes(b"this is not a png")
    return f


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "sample_docs"
    files = build(target)
    print(f"Created {len(files)} sample files in {target}")
