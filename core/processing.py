"""Text extraction: digital PDFs, scanned PDFs / images via OCR, plain text."""
from __future__ import annotations

import io
import re
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

from . import config
from .errors import ExtractionError

MIN_DIGITAL_CHARS = 40  # below this a PDF page is treated as scanned


@dataclass
class TextResult:
    text: str
    method: str  # "digital", "ocr", "plain"
    pages: int = 1


def clean_text(text: str) -> str:
    text = text.replace("\r", "\n").replace("\x0c", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _ocr_image(img) -> str:
    try:
        import pytesseract

        if config.TESSERACT_CMD:
            pytesseract.pytesseract.tesseract_cmd = config.TESSERACT_CMD
        return pytesseract.image_to_string(img)
    except ImportError as exc:
        raise ExtractionError("OCR is not installed (pip install pytesseract).", "ocr_missing") from exc
    except Exception as exc:  # TesseractNotFoundError and friends
        raise ExtractionError(
            "OCR engine (Tesseract) is not available on this machine. Install it to read scanned files.",
            "ocr_missing",
        ) from exc


def _ocr_pdf(path: Path) -> tuple[str, int]:
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:
        raise ExtractionError("Scanned PDFs need pypdfium2 (pip install pypdfium2).", "ocr_missing") from exc
    try:
        pdf = pdfium.PdfDocument(str(path))
        parts = []
        for page in pdf:
            bitmap = page.render(scale=2.5)
            parts.append(_ocr_image(bitmap.to_pil()))
        return "\n".join(parts), len(pdf)
    except ExtractionError:
        raise
    except Exception as exc:
        raise ExtractionError("Could not render the PDF for OCR.", "unreadable") from exc


def extract_text(path: Path, ext: str) -> TextResult:
    """Return cleaned text for a stored file, choosing digital reading or OCR automatically."""
    if ext == ".txt":
        raw = path.read_bytes().decode("utf-8", errors="replace")
        return TextResult(clean_text(raw), "plain")

    if ext in {".png", ".jpg", ".jpeg"}:
        try:
            from PIL import Image

            with Image.open(path) as img:
                img.load()
                text = _ocr_image(img.convert("L"))
        except ExtractionError:
            raise
        except Exception as exc:
            raise ExtractionError("The image could not be opened or read.", "unreadable") from exc
        return TextResult(clean_text(text), "ocr")

    if ext == ".pdf":
        try:
            reader = PdfReader(io.BytesIO(path.read_bytes()))
            if reader.is_encrypted:
                raise ExtractionError("The PDF is password protected.", "unreadable")
            pages = len(reader.pages)
            text = "\n".join((p.extract_text() or "") for p in reader.pages)
        except ExtractionError:
            raise
        except Exception as exc:
            raise ExtractionError("The PDF is corrupted or unreadable.", "unreadable") from exc
        if len(text.strip()) >= MIN_DIGITAL_CHARS:
            return TextResult(clean_text(text), "digital", pages)
        ocr_text, pages = _ocr_pdf(path)
        return TextResult(clean_text(ocr_text), "ocr", pages)

    raise ExtractionError(f"Unsupported type {ext}.", "unsupported_type")
