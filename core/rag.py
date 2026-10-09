"""Retrieval-augmented assistant: chunking, TF-IDF semantic-ish retrieval, grounded answers.

Answers only come from stored document text. If nothing relevant is retrieved the assistant
says so instead of guessing. Optionally an LLM (Anthropic) can phrase the answer from the
retrieved chunks only - enabled by setting ANTHROPIC_API_KEY.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from . import config, database

NO_ANSWER = "I couldn't find enough information in the available documents to answer that."

_cache: dict = {"key": None, "vec": None, "matrix": None, "chunks": []}


def chunk_text(text: str, size: int | None = None, overlap: int | None = None) -> list[str]:
    size = size or config.CHUNK_WORDS
    overlap = config.CHUNK_OVERLAP if overlap is None else overlap
    words = text.split()
    if not words:
        return []
    step = max(1, size - overlap)
    chunks = []
    for start in range(0, len(words), step):
        piece = words[start:start + size]
        if piece:
            chunks.append(" ".join(piece))
        if start + size >= len(words):
            break
    return chunks


def index_document(doc_id: int, text: str) -> int:
    chunks = chunk_text(text)
    database.replace_chunks(doc_id, chunks)
    _cache["key"] = None  # invalidate
    return len(chunks)


def _ensure_index() -> bool:
    chunks = database.all_chunks()
    key = (len(chunks), chunks[-1]["id"] if chunks else 0)
    if key == _cache["key"]:
        return bool(chunks)
    if not chunks:
        _cache.update(key=key, vec=None, matrix=None, chunks=[])
        return False
    vec = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), sublinear_tf=True)
    matrix = vec.fit_transform([c["text"] for c in chunks])
    _cache.update(key=key, vec=vec, matrix=matrix, chunks=chunks)
    return True


@dataclass
class Hit:
    doc_id: int
    doc_name: str
    chunk_idx: int
    text: str
    score: float


@dataclass
class Answer:
    text: str
    answered: bool
    hits: list[Hit] = field(default_factory=list)
    top_score: float = 0.0
    mode: str = "extractive"


def retrieve(question: str, k: int | None = None) -> list[Hit]:
    k = k or config.RAG_TOP_K
    if not _ensure_index():
        return []
    qv = _cache["vec"].transform([question])
    sims = cosine_similarity(qv, _cache["matrix"]).ravel()
    order = sims.argsort()[::-1][: k * 3]
    hits: list[Hit] = []
    per_doc: dict[int, int] = {}
    for i in order:
        if sims[i] <= 0:
            continue
        c = _cache["chunks"][i]
        if per_doc.get(c["doc_id"], 0) >= 2:  # keep results diverse across documents
            continue
        per_doc[c["doc_id"]] = per_doc.get(c["doc_id"], 0) + 1
        hits.append(Hit(c["doc_id"], c["original_name"], c["idx"], c["text"], float(sims[i])))
        if len(hits) >= k:
            break
    return hits


def _stem(word: str) -> str:
    return word[:-1] if len(word) > 3 and word.endswith("s") and not word.endswith("ss") else word


def _terms(text: str) -> set[str]:
    return {_stem(w) for w in re.findall(r"[a-z0-9\-]+", text.lower()) if w not in ENGLISH_STOP_WORDS and len(w) > 1}


def _best_sentences(question: str, text: str, n: int = 2) -> list[str]:
    terms = _terms(question)
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if len(s.strip()) > 3]
    scored = sorted(sentences, key=lambda s: -len(terms & _terms(s)))
    return [s for s in scored[:n] if terms & _terms(s)] or sentences[:1]


def _llm_answer(question: str, hits: list[Hit]) -> str | None:
    if not config.ANTHROPIC_API_KEY:
        return None
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        context = "\n\n".join(f"[{h.doc_name} #{h.doc_id}] {h.text}" for h in hits)
        msg = client.messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=400,
            system=(
                "Answer ONLY from the provided document excerpts. Cite the document name in brackets. "
                f"If the excerpts do not contain the answer, reply exactly: {NO_ANSWER}"
            ),
            messages=[{"role": "user", "content": f"Excerpts:\n{context}\n\nQuestion: {question}"}],
        )
        return "".join(b.text for b in msg.content if getattr(b, "text", None)).strip() or None
    except Exception:
        return None  # fall back to the local extractive answer


def ask(question: str) -> Answer:
    question = (question or "").strip()
    if len(question) < 3:
        return Answer("Please type a question about your documents.", False)
    hits = retrieve(question)
    top = hits[0].score if hits else 0.0
    # Require both semantic similarity and at least one shared meaningful term.
    qterms = _terms(question)
    relevant = [h for h in hits if h.score >= config.RAG_MIN_SCORE and qterms & _terms(h.text)]
    # Coverage guard: most of the question's meaningful words must appear in the evidence,
    # otherwise one shared word (e.g. a company name) could make an unanswerable question look answerable.
    covered = set().union(*(_terms(h.text) for h in relevant)) if relevant else set()
    coverage = len(qterms & covered) / len(qterms) if qterms else 0.0
    if not relevant or coverage < config.RAG_MIN_COVERAGE:
        relevant = []
    if not relevant:
        database.log_question(question, False, top, [])
        return Answer(NO_ANSWER, False, hits, top)

    llm = _llm_answer(question, relevant)
    if llm and NO_ANSWER not in llm:
        database.log_question(question, True, top, [h.doc_name for h in relevant])
        return Answer(llm, True, relevant, top, "llm")
    if llm:
        database.log_question(question, False, top, [])
        return Answer(NO_ANSWER, False, relevant, top, "llm")

    lines, seen = [], set()
    for h in relevant:
        for s in _best_sentences(question, h.text):
            if s not in seen:
                seen.add(s)
                lines.append(f"- {s}  \n  <sub>source: {h.doc_name} (#{h.doc_id})</sub>")
    database.log_question(question, True, top, sorted({h.doc_name for h in relevant}))
    return Answer("\n".join(lines), True, relevant, top)
