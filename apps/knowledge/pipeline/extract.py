"""Extract plain text from uploaded files (PDF today; extend as needed)."""

from __future__ import annotations

from pathlib import Path


class ExtractionError(Exception):
    pass


def extract_text(*, file_path: Path, file_type: str) -> str:
    normalized = file_type.lower().lstrip(".")
    if normalized == "pdf":
        return _extract_pdf(file_path)
    raise ExtractionError(f"Unsupported file type: {file_type}")


def _extract_pdf(file_path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ExtractionError("pypdf is not installed") from exc

    reader = PdfReader(str(file_path))
    pages: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        if text.strip():
            pages.append(text)
    if not pages:
        raise ExtractionError("No text could be extracted from PDF")
    return "\n\n".join(pages)
