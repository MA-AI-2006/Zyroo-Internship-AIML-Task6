"""Document classifier: TF-IDF + Logistic Regression trained on built-in seed phrases.

The model is trained once per process (cached) so Streamlit reruns stay fast.
Replace SEED_PHRASES with your own labelled data for better accuracy.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from functools import lru_cache

from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline

from . import config

CATEGORIES = ["invoice", "receipt", "resume", "contract", "purchase_order"]

SEED_PHRASES: dict[str, list[str]] = {
    "invoice": [
        "invoice number", "invoice date", "due date", "bill to", "amount due", "subtotal", "tax",
        "total due", "payment terms net 30", "remit to", "invoice no", "balance due", "unit price quantity",
        "please pay within", "vendor", "billing address", "grand total", "description of services",
    ],
    "receipt": [
        "receipt", "thank you for shopping", "cashier", "paid by cash", "card ending", "change due",
        "store", "transaction id", "payment received", "visa", "mastercard", "items purchased", "total paid",
        "come again", "receipt no", "pos terminal", "tendered", "served by",
    ],
    "resume": [
        "curriculum vitae", "resume", "work experience", "education", "skills", "objective", "references",
        "bachelor of science", "university", "projects", "certifications", "languages", "profile summary",
        "internship", "python machine learning", "linkedin", "github", "responsibilities", "gpa",
    ],
    "contract": [
        "agreement", "this agreement is made", "party of the first part", "terms and conditions", "hereby",
        "governing law", "termination clause", "confidentiality", "effective date", "witness whereof",
        "obligations", "liability", "indemnify", "signature of both parties", "jurisdiction", "term of agreement",
        "scope of work", "breach",
    ],
    "purchase_order": [
        "purchase order", "po number", "ship to", "order date", "delivery date", "requested by", "buyer",
        "supplier", "item code", "order quantity", "approved by", "shipping method", "po total", "vendor id",
        "purchase order no", "deliver to", "authorized signature", "requisition",
    ],
}


def _build_training_data(n_per_class: int = 90, seed: int = 7) -> tuple[list[str], list[str]]:
    rng = random.Random(seed)
    texts, labels = [], []
    for label, phrases in SEED_PHRASES.items():
        for _ in range(n_per_class):
            k = rng.randint(4, min(10, len(phrases)))
            texts.append(" ".join(rng.sample(phrases, k)))
            labels.append(label)
    return texts, labels


@lru_cache(maxsize=1)
def _model():
    texts, labels = _build_training_data()
    model = make_pipeline(
        TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, lowercase=True),
        LogisticRegression(max_iter=1000, C=8.0),
    )
    model.fit(texts, labels)
    return model


@dataclass
class Classification:
    label: str
    confidence: float
    scores: dict[str, float]
    low_confidence: bool


def classify(text: str) -> Classification:
    """Return the best category. Falls back to 'unknown' below the confidence threshold."""
    if not text or len(text.split()) < 3:
        return Classification("unknown", 0.0, {}, True)
    model = _model()
    probs = model.predict_proba([text])[0]
    scores = {c: float(p) for c, p in zip(model.classes_, probs)}
    best = max(scores, key=scores.get)
    conf = scores[best]
    # Keyword evidence: a text with no vocabulary overlap should never look confident.
    vocab = model.named_steps["tfidfvectorizer"].vocabulary_
    words = {w.strip(".,:;()#") for w in text.lower().split()}
    overlap = sum(1 for w in words if w in vocab and w not in ENGLISH_STOP_WORDS)
    if overlap < 3:
        conf = min(conf, 0.30)
    low = conf < config.MIN_CLASSIFY_CONFIDENCE
    label = "unknown" if low and conf <= 0.30 else str(best)
    return Classification(label, round(conf, 3), {str(k): v for k, v in scores.items()}, low)
