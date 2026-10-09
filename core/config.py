"""Central configuration. Values come from environment variables / a .env file."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


DATA_DIR = Path(os.getenv("DOCFLOW_DATA_DIR", BASE_DIR / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = Path(os.getenv("DOCFLOW_DB_PATH", DATA_DIR / "docflow.db"))

MAX_FILE_MB = _int("DOCFLOW_MAX_FILE_MB", 10)
MAX_FILE_BYTES = MAX_FILE_MB * 1024 * 1024
ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".txt"}

# Confidence thresholds (0-1)
MIN_CLASSIFY_CONFIDENCE = _float("DOCFLOW_MIN_CLASSIFY_CONF", 0.45)
MIN_EXTRACT_CONFIDENCE = _float("DOCFLOW_MIN_EXTRACT_CONF", 0.50)
AMOUNT_TOLERANCE = _float("DOCFLOW_AMOUNT_TOLERANCE", 0.02)
HIGH_AMOUNT_THRESHOLD = _float("DOCFLOW_HIGH_AMOUNT", 50000.0)

# RAG
RAG_TOP_K = _int("DOCFLOW_RAG_TOP_K", 4)
RAG_MIN_SCORE = _float("DOCFLOW_RAG_MIN_SCORE", 0.08)
RAG_MIN_COVERAGE = _float("DOCFLOW_RAG_MIN_COVERAGE", 0.6)
CHUNK_WORDS = _int("DOCFLOW_CHUNK_WORDS", 120)
CHUNK_OVERLAP = _int("DOCFLOW_CHUNK_OVERLAP", 25)

# Optional external LLM (kept out of source code; leave blank to stay fully local)
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5")

# Optional API protection
API_KEY = os.getenv("DOCFLOW_API_KEY", "")

# OCR
TESSERACT_CMD = os.getenv("TESSERACT_CMD", "")


def ensure_dirs() -> None:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
