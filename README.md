# 📄 DocFlow — AI Document Intelligence & Workflow Platform

Final integrated product for the ZYROO AI/ML Internship (Week 6). One reliable system that takes a document from upload to final report:

**Upload → Validate → OCR/Text → Classify → Extract → Store → Verify → Anomaly check → AI analysis → Workflow decision → Review / Approve / Reject → Audit → Search & Report**

## Features
- Safe uploads: type, size and magic-byte integrity checks, generated storage names, path-traversal protection
- Digital PDF reading, automatic OCR fallback for scanned PDFs and images (Tesseract)
- TF-IDF + Logistic Regression classifier (invoice, receipt, purchase order, resume, contract) with confidence and an `unknown` fallback
- Category-specific field extraction with extraction-confidence score
- Validation (required fields, dates, email, **arithmetic checks**) and anomaly detection (repeated identifiers, unusual/high amounts)
- Workflow engine: `processing → approved / pending_review / failed`, manual review, reject-with-reason, reopen, retry
- SHA-256 duplicate detection — duplicates are never reprocessed
- RAG assistant with chunking, retrieval, source references, and an honest "not enough information" answer; every question is logged
- Full audit trail, search/filter, CSV export, dashboard with processing times
- Optional FastAPI layer, Dockerfile, test-suite (39 tests)

## Project structure
```
app.py            Streamlit UI (Dashboard, Upload, Documents, Review Queue, Assistant, Audit Trail)
api.py            Optional REST API (FastAPI)
core/
  config.py       Settings from environment / .env
  storage.py      File validation, hashing, safe paths
  processing.py   PDF text + OCR
  classifier.py   ML classification
  extraction.py   Field extraction per document type
  validation.py   Required-field, format and arithmetic checks
  anomaly.py      Duplicate identifiers / unusual amounts
  workflow.py     States, transitions, routing rules, review
  rag.py          Chunking, retrieval, grounded answers
  analysis.py     Short AI analysis summary
  database.py     SQLite (documents, chunks, audit, assistant log)
  pipeline.py     Orchestrates the whole flow, single & batch
scripts/make_samples.py   Builds sample documents for every test case
tests/            pytest suite
sample_docs/      Ready-made documents to try in the app
```

## Install & run (fresh environment)
```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate        macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # Windows: copy .env.example .env
streamlit run app.py            # opens http://localhost:8501
```
**OCR needs Tesseract installed** (only for scanned files): Windows – <https://github.com/UB-Mannheim/tesseract/wiki> (then set `TESSERACT_CMD` in `.env` if it is not on PATH); Ubuntu – `sudo apt install tesseract-ocr`; macOS – `brew install tesseract`. Digital PDFs and `.txt` files work without it.

Optional API: `uvicorn api:app --reload` → interactive docs at <http://127.0.0.1:8000/docs>.
Docker: `docker compose up --build` (UI on 8501, API on 8000).

## Configuration (`.env`)
| Variable | Purpose | Default |
|---|---|---|
| `DOCFLOW_MAX_FILE_MB` | Upload size limit | 10 |
| `DOCFLOW_MIN_CLASSIFY_CONF` | Below this → manual review | 0.45 |
| `DOCFLOW_MIN_EXTRACT_CONF` | Below this → manual review | 0.50 |
| `DOCFLOW_HIGH_AMOUNT` | Totals at/above this are flagged | 50000 |
| `DOCFLOW_DATA_DIR` / `DOCFLOW_DB_PATH` | Where files and the DB live | `./data` |
| `DOCFLOW_API_KEY` | Require `X-API-Key` on the REST API | off |
| `ANTHROPIC_API_KEY` | Optional external AI for assistant answers | off |
| `TESSERACT_CMD` | Path to tesseract if not on PATH | auto |

Secrets stay in `.env`, which is git-ignored. Only use documents you are permitted to process, especially if you enable an external AI service (retrieved excerpts are sent to it).

## Supported document types and fields
| Type | Fields extracted | Required |
|---|---|---|
| Invoice | number, date, due date, vendor, bill-to, subtotal, tax, total | number, date, vendor, total |
| Receipt | merchant, date, receipt no., payment method, subtotal, tax, total | merchant, date, total |
| Purchase order | PO no., order/delivery date, supplier, buyer, ship-to, amounts | PO no., date, supplier, total |
| Resume | name, email, phone, skills, education | name, email, skills |
| Contract | parties, effective date, term, governing law, value | parties, effective date |

## Workflow rules
A document is **auto-approved** only if classification and extraction confidence are above threshold, there are no validation errors, and no anomalies. Otherwise it goes to **Needs review** with the reasons listed. Reviewers approve, or reject (a reason is mandatory). Approved/rejected documents can be reopened. Failed documents can be retried. Invalid transitions (e.g. approved → rejected) are blocked. Every change is written to the audit trail.

## Final architecture
```
UI (Streamlit) ─┐
API (FastAPI) ──┼─► pipeline ─► processing/OCR ─► classifier ─► extraction ─► validation ─► anomaly ─► workflow
                │        │                                                                         │
                │        └─► storage (files, hashes) ─► database (SQLite) ◄── audit ◄──────────────┘
                └──────────► RAG (chunks → TF-IDF retrieval → grounded answer + sources)
```

## Testing
```bash
python scripts/make_samples.py   # regenerate sample_docs/
python -m pytest -q
```
Covered: clean PDF, scanned image/PDF (OCR), every document type, missing fields, duplicate file, repeated identifier, unsupported type, corrupted/fake files, low-confidence classification, arithmetic mismatch, invalid transition, mixed-success batch, restart persistence, answerable and unanswerable assistant questions, cross-document questions, path traversal, size limits, metrics, API status codes and auth, UI smoke test.

## API
| Method | Path | Purpose |
|---|---|---|
| POST | `/documents` | Upload & process (multipart `file`) |
| GET | `/documents?status=&category=&q=` | List / search |
| GET | `/documents/{id}` | Details |
| POST | `/documents/{id}/review` | `{decision: approve\|reject, reviewer, note}` |
| GET | `/documents/{id}/audit` | Audit history |
| POST | `/ask` | `{question}` → grounded answer + sources |
| GET | `/metrics` · `/health` | Dashboard numbers / liveness |

Errors: 401 bad key, 404 unknown id, 409 invalid transition, 415 unsupported type, 422 invalid request/file.

## Known limitations & future work
- Classifier is trained on built-in seed phrases; train it on real labelled documents for production accuracy.
- Extraction is rule-based (regex) and tuned to common English layouts; unusual layouts will land in manual review.
- Retrieval uses TF-IDF rather than neural embeddings (no model download, fast, fully local). `core/rag.py` is the single place to swap in sentence-transformers or a vector DB.
- No user login; the reviewer name is free text. Add authentication before exposing the app publicly.
- SQLite suits a single server; move to PostgreSQL for multi-user deployments.

## Demo script
1. **Upload** `sample_docs/invoice_clean.pdf` → auto-approved. 2. Upload `invoice_scanned.png` → OCR. 3. Upload `invoice_arithmetic_mismatch.pdf` → flagged. 4. Re-upload `invoice_copy.pdf` → duplicate caught. 5. **Assistant**: "What is the total due on invoice INV-1001?" then "What is the capital of France?". 6. **Review Queue** → approve/reject. 7. **Audit Trail**, **Documents** search, **Dashboard**.
