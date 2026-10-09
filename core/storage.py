"""File validation and safe storage: type/size/integrity checks, hashing, safe paths."""
from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import Path

from . import config
from .errors import FileValidationError

MAGIC = {
    ".pdf": [b"%PDF-"],
    ".png": [b"\x89PNG\r\n\x1a\n"],
    ".jpg": [b"\xff\xd8\xff"],
    ".jpeg": [b"\xff\xd8\xff"],
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def clean_display_name(name: str) -> str:
    """Strip any directory part and unsafe characters (display only, never used as a path)."""
    base = re.split(r"[\\/]", name or "")[-1]
    base = re.sub(r"[^\w.\- ()]", "_", base).strip(" .")
    return (base or "document")[:120]


def validate_upload(filename: str, data: bytes) -> str:
    """Return the lower-case extension if the file passes basic checks, else raise."""
    if not data:
        raise FileValidationError("The file is empty.")
    ext = Path(clean_display_name(filename)).suffix.lower()
    if ext not in config.ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(config.ALLOWED_EXTENSIONS))
        raise FileValidationError(
            f"Unsupported file type '{ext or 'none'}'. Allowed types: {allowed}.", "unsupported_type"
        )
    if len(data) > config.MAX_FILE_BYTES:
        raise FileValidationError(
            f"File is larger than the {config.MAX_FILE_MB} MB limit.", "too_large"
        )
    signatures = MAGIC.get(ext)
    if signatures and not any(data.startswith(sig) for sig in signatures):
        raise FileValidationError(
            f"The file content does not look like a real {ext[1:].upper()} file (corrupted or renamed).",
            "corrupted",
        )
    if ext == ".txt":
        if b"\x00" in data[:2048]:
            raise FileValidationError("The text file contains binary data.", "corrupted")
    return ext


def save_file(data: bytes, ext: str) -> tuple[str, Path]:
    """Store bytes under a generated name inside UPLOAD_DIR. Returns (stored_name, path)."""
    config.ensure_dirs()
    stored_name = f"{uuid.uuid4().hex}{ext}"
    path = safe_path(stored_name)
    path.write_bytes(data)
    return stored_name, path


def safe_path(stored_name: str) -> Path:
    """Resolve a stored name inside UPLOAD_DIR, refusing any traversal attempt."""
    root = config.UPLOAD_DIR.resolve()
    path = (root / stored_name).resolve()
    if root != path.parent:
        raise FileValidationError("Unsafe file path.", "unsafe_path")
    return path
