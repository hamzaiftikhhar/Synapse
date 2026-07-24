"""Extract plain text from uploaded files — page-aware (PDF today).

Why this file exists
--------------------
Reading a PDF is a different job from cleaning, chunking, or embedding.
This module only turns a file on disk into ordered page texts.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class ExtractionError(Exception):
    pass


@dataclass(frozen=True)
class PageText:
    """One PDF page after extraction."""

    page_number: int  # 1-based
    text: str


def extract_pages(*, file_path: Path, file_type: str) -> list[PageText]:
    """
    Data in:  path to a stored PDF + file_type ("pdf")
    Data out: [{page_number: 1, text: "..."}, {page_number: 2, text: "..."}, ...]

    Empty / scanned pages (no extractable text) are skipped.
    Raises ExtractionError if no page yields text.
    """
    normalized = file_type.lower().lstrip(".")
    if normalized == "pdf":
        return _extract_pdf_pages(file_path)
    raise ExtractionError(f"Unsupported file type: {file_type}")


def extract_text(*, file_path: Path, file_type: str) -> str:
    """
    Backwards-compatible helper: all pages joined with blank lines.

    Prefer extract_pages() so page numbers are preserved for chunking.
    """
    pages = extract_pages(file_path=file_path, file_type=file_type)
    return "\n\n".join(p.text for p in pages)


def _extract_pdf_pages(file_path: Path) -> list[PageText]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ExtractionError("pypdf is not installed") from exc

    if not file_path.is_file():
        raise ExtractionError(f"File not found: {file_path}")

    try:
        reader = PdfReader(str(file_path))
    except Exception as exc:
        raise ExtractionError(f"Corrupted or unreadable PDF: {exc}") from exc

    pages: list[PageText] = []
    for index, page in enumerate(reader.pages):
        try:
            raw = page.extract_text() or ""
        except Exception:
            raw = ""
        text = raw.strip()
        if text:
            pages.append(PageText(page_number=index + 1, text=text))

    if not pages:
        raise ExtractionError(
            "No text could be extracted from PDF "
            "(scanned image-only PDFs are not supported yet)"
        )
    return pages
