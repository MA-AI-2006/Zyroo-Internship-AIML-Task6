"""Optional REST API:  uvicorn api:app --reload   (docs at http://127.0.0.1:8000/docs)"""
from __future__ import annotations

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from core import config, database, pipeline, rag, workflow
from core.errors import DocFlowError, NotFoundError

app = FastAPI(title="DocFlow API", version="1.0.0", description="Document Intelligence & Workflow Platform")
database.init_db()


def require_key(x_api_key: str | None = Header(default=None)) -> None:
    """If DOCFLOW_API_KEY is set, every request must send it in the X-API-Key header."""
    if config.API_KEY and x_api_key != config.API_KEY:
        raise HTTPException(status_code=401, detail="Missing or invalid API key.")


class ReviewRequest(BaseModel):
    decision: str = Field(pattern="^(approve|reject)$")
    reviewer: str = Field(min_length=1, max_length=60)
    note: str = Field(default="", max_length=500)


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/documents", dependencies=[Depends(require_key)])
async def upload(file: UploadFile = File(...)):
    data = await file.read(config.MAX_FILE_BYTES + 1)
    result = pipeline.process_upload(file.filename or "upload", data, actor="api")
    if not result["ok"]:
        code = 415 if "Unsupported" in result["message"] else 422
        raise HTTPException(status_code=code, detail=result["message"])
    return result


@app.get("/documents", dependencies=[Depends(require_key)])
def list_documents(status: str | None = None, category: str | None = None, q: str | None = None, limit: int = Query(100, le=500)):
    return database.list_documents(status, category, q, limit)


@app.get("/documents/{doc_id}", dependencies=[Depends(require_key)])
def get_document(doc_id: int):
    doc = database.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document #{doc_id} not found.")
    doc.pop("text", None)
    return doc


@app.post("/documents/{doc_id}/review", dependencies=[Depends(require_key)])
def review(doc_id: int, body: ReviewRequest):
    try:
        doc = workflow.review(doc_id, body.decision, body.reviewer, body.note)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except DocFlowError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    doc.pop("text", None)
    return doc


@app.get("/documents/{doc_id}/audit", dependencies=[Depends(require_key)])
def audit(doc_id: int):
    return database.get_audit(doc_id)


@app.post("/ask", dependencies=[Depends(require_key)])
def ask(body: AskRequest):
    ans = rag.ask(body.question)
    return {
        "answer": ans.text,
        "answered": ans.answered,
        "sources": [{"document_id": h.doc_id, "document": h.doc_name, "score": round(h.score, 3)} for h in ans.hits],
    }


@app.get("/metrics", dependencies=[Depends(require_key)])
def metrics():
    return database.metrics()
