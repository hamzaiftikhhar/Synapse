"""Extract plain text from uploaded files — page-aware (PDF, CSV, XLSX).

Why this file exists
--------------------
Reading a file is a different job from cleaning, chunking, or embedding.
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
    if normalized in {"csv", "xlsx"}:
        return _extract_tabular_pages(file_path, normalized)
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


# Reuses apps.importer's CSV/XLSX parsing (headers, rows) rather than a
# second copy — that module already handles BOM/encoding, malformed
# workbooks, and the max-rows/max-columns/max-file-size guards. This is a
# different downstream use, though: the importer turns rows into structured
# entity fields (a Doctor, a Service); this turns them into readable text
# for chunking/embedding, so a row like {"Question": "...", "Answer": "..."}
# becomes a small "Question: ...\nAnswer: ..." block rather than a mapped
# record. XLS (legacy binary Excel) isn't supported — apps.importer doesn't
# support it either, and adding a second Excel library for a rare, aging
# format isn't justified by anything actually needed here.
def _extract_tabular_pages(file_path: Path, file_type: str) -> list[PageText]:
    from apps.importer.services.parser import ParserError, parse_csv, parse_xlsx

    if not file_path.is_file():
        raise ExtractionError(f"File not found: {file_path}")

    raw_bytes = file_path.read_bytes()
    try:
        table = parse_csv(raw_bytes) if file_type == "csv" else parse_xlsx(raw_bytes)
    except ParserError as exc:
        raise ExtractionError(str(exc)) from exc

    blocks: list[str] = []
    for row in table.rows:
        lines = [f"{header}: {value}" for header, value in row.items() if value]
        if lines:
            blocks.append("\n".join(lines))

    if not blocks:
        raise ExtractionError("No text could be extracted from file (no non-empty rows).")

    # The whole table is one "page" — downstream chunking already handles
    # splitting long text, exactly as it does for a long PDF page.
    return [PageText(page_number=1, text="\n\n".join(blocks))]
