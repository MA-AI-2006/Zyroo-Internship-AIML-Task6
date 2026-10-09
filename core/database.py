"""SQLite persistence: documents, text chunks, audit trail and assistant log."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    original_name TEXT NOT NULL,
    stored_name TEXT,
    ext TEXT,
    sha256 TEXT UNIQUE,
    size INTEGER,
    uploaded_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    status TEXT NOT NULL,
    category TEXT,
    class_conf REAL,
    extract_conf REAL,
    text TEXT,
    text_method TEXT,
    pages INTEGER,
    fields_json TEXT,
    validation_json TEXT,
    anomalies_json TEXT,
    analysis TEXT,
    identifier TEXT,
    workflow_reason TEXT,
    error TEXT,
    processing_ms INTEGER,
    timings_json TEXT
);
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    idx INTEGER NOT NULL,
    text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id INTEGER,
    ts TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    from_status TEXT,
    to_status TEXT,
    detail TEXT
);
CREATE TABLE IF NOT EXISTS assistant_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    question TEXT NOT NULL,
    answered INTEGER NOT NULL,
    top_score REAL,
    sources TEXT
);
CREATE INDEX IF NOT EXISTS idx_docs_status ON documents(status);
CREATE INDEX IF NOT EXISTS idx_docs_identifier ON documents(identifier);
CREATE INDEX IF NOT EXISTS idx_audit_doc ON audit(doc_id);
"""

JSON_COLS = {"fields_json": "fields", "validation_json": "validation", "anomalies_json": "anomalies", "timings_json": "timings"}


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


@contextmanager
def connect():
    config.ensure_dirs()
    conn = sqlite3.connect(config.DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


def _row(row: sqlite3.Row | None, include_text: bool = True) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    for col, name in JSON_COLS.items():
        raw = d.pop(col, None)
        d[name] = json.loads(raw) if raw else ({} if name in ("fields", "timings") else [])
    if not include_text:
        d.pop("text", None)
    return d


# ---------- documents ----------
def find_by_hash(sha: str) -> dict | None:
    with connect() as conn:
        return _row(conn.execute("SELECT * FROM documents WHERE sha256=?", (sha,)).fetchone())


def create_document(original_name: str, stored_name: str | None, ext: str, sha: str, size: int, status: str = "processing") -> int:
    ts = now()
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO documents (original_name, stored_name, ext, sha256, size, uploaded_at, updated_at, status)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (original_name, stored_name, ext, sha, size, ts, ts, status),
        )
        return int(cur.lastrowid)


def update_document(doc_id: int, **values) -> None:
    sets, params = [], []
    for key, val in values.items():
        if key in ("fields", "validation", "anomalies", "timings"):
            key = key + "_json"
            val = json.dumps(val, default=str)
        sets.append(f"{key}=?")
        params.append(val)
    sets.append("updated_at=?")
    params.append(now())
    params.append(doc_id)
    with connect() as conn:
        conn.execute(f"UPDATE documents SET {', '.join(sets)} WHERE id=?", params)


def get_document(doc_id: int) -> dict | None:
    with connect() as conn:
        return _row(conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone())


def list_documents(status: str | None = None, category: str | None = None, query: str | None = None, limit: int = 500) -> list[dict]:
    sql, params = "SELECT * FROM documents WHERE 1=1", []
    if status and status != "all":
        sql += " AND status=?"
        params.append(status)
    if category and category != "all":
        sql += " AND category=?"
        params.append(category)
    if query:
        like = f"%{query.strip()}%"
        sql += " AND (original_name LIKE ? OR text LIKE ? OR identifier LIKE ? OR fields_json LIKE ?)"
        params += [like, like, like, like]
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    with connect() as conn:
        return [_row(r, include_text=False) for r in conn.execute(sql, params).fetchall()]


def docs_with_identifier(category: str, identifier: str, exclude_id: int) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, original_name, status FROM documents WHERE category=? AND identifier=? AND id<>?",
            (category, identifier, exclude_id),
        ).fetchall()
        return [dict(r) for r in rows]


def category_amounts(category: str, exclude_id: int) -> list[float]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT fields_json FROM documents WHERE category=? AND id<>? AND fields_json IS NOT NULL",
            (category, exclude_id),
        ).fetchall()
    out = []
    for r in rows:
        total = json.loads(r["fields_json"]).get("total")
        if isinstance(total, (int, float)):
            out.append(float(total))
    return out


# ---------- chunks ----------
def replace_chunks(doc_id: int, chunks: list[str]) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM chunks WHERE doc_id=?", (doc_id,))
        conn.executemany("INSERT INTO chunks (doc_id, idx, text) VALUES (?,?,?)", [(doc_id, i, c) for i, c in enumerate(chunks)])


def all_chunks() -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT c.id, c.doc_id, c.idx, c.text, d.original_name FROM chunks c JOIN documents d ON d.id=c.doc_id"
            " WHERE d.status NOT IN ('failed','rejected') ORDER BY c.id"
        ).fetchall()
        return [dict(r) for r in rows]


# ---------- audit ----------
def log_audit(doc_id: int | None, actor: str, action: str, from_status: str | None = None, to_status: str | None = None, detail: str = "") -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO audit (doc_id, ts, actor, action, from_status, to_status, detail) VALUES (?,?,?,?,?,?,?)",
            (doc_id, now(), actor, action, from_status, to_status, detail),
        )


def get_audit(doc_id: int | None = None, limit: int = 200, action: str | None = None) -> list[dict]:
    sql = (
        "SELECT a.*, d.original_name FROM audit a LEFT JOIN documents d ON d.id=a.doc_id WHERE 1=1"
    )
    params: list = []
    if doc_id is not None:
        sql += " AND a.doc_id=?"
        params.append(doc_id)
    if action:
        sql += " AND a.action=?"
        params.append(action)
    sql += " ORDER BY a.id DESC LIMIT ?"
    params.append(limit)
    with connect() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


# ---------- assistant log ----------
def log_question(question: str, answered: bool, top_score: float, sources: list[str]) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO assistant_log (ts, question, answered, top_score, sources) VALUES (?,?,?,?,?)",
            (now(), question, int(answered), top_score, json.dumps(sources)),
        )


def get_question_log(limit: int = 100) -> list[dict]:
    with connect() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM assistant_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]


# ---------- metrics ----------
def metrics() -> dict:
    with connect() as conn:
        q = lambda sql, p=(): conn.execute(sql, p).fetchall()  # noqa: E731
        total = q("SELECT COUNT(*) c FROM documents")[0]["c"]
        by_status = {r["status"]: r["c"] for r in q("SELECT status, COUNT(*) c FROM documents GROUP BY status")}
        by_type = {(r["category"] or "unclassified"): r["c"] for r in q("SELECT category, COUNT(*) c FROM documents GROUP BY category")}
        docs = q("SELECT validation_json, anomalies_json, processing_ms FROM documents")
        val_issues = sum(1 for r in docs if r["validation_json"] and json.loads(r["validation_json"]))
        anomalies = sum(1 for r in docs if r["anomalies_json"] and json.loads(r["anomalies_json"]))
        times = [r["processing_ms"] for r in docs if r["processing_ms"]]
        duplicates = q("SELECT COUNT(*) c FROM audit WHERE action='duplicate_upload'")[0]["c"]
        questions = q("SELECT COUNT(*) c, COALESCE(SUM(answered),0) a FROM assistant_log")[0]
    return {
        "total": total,
        "by_status": by_status,
        "by_type": by_type,
        "validation_issues": val_issues,
        "anomalies": anomalies,
        "duplicates": duplicates,
        "failed": by_status.get("failed", 0),
        "avg_ms": round(sum(times) / len(times)) if times else None,
        "max_ms": max(times) if times else None,
        "questions": questions["c"],
        "questions_answered": questions["a"],
    }
