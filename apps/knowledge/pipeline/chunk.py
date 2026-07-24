"""Split cleaned page texts into ordered chunks — no embedding calls.

Why this file exists
--------------------
Chunking must stay independent of OpenAI / local models.
Swap this file to change split strategy without touching embed.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from django.conf import settings

from apps.knowledge.pipeline.extract import PageText


@dataclass(frozen=True)
class TextChunk:
    chunk_number: int
    content: str
    page_number: int | None = None
    token_count: int | None = None


def chunk_pages(pages: list[PageText]) -> list[TextChunk]:
    """
    Paragraph-aware chunking across pages.

    Data in:  [{page_number, text}, ...]  (already cleaned)
    Data out: [{chunk_number, content, page_number}, ...]

    Strategy:
    1. Split each page into paragraphs (blank-line separated)
    2. Pack paragraphs into windows of KNOWLEDGE_CHUNK_SIZE
    3. If one paragraph is longer than the window, fall back to
       sliding-window splits for that paragraph only
    4. Overlap applies when continuing a long paragraph split
    """
    size = settings.KNOWLEDGE_CHUNK_SIZE
    overlap = settings.KNOWLEDGE_CHUNK_OVERLAP
    _validate_window(size, overlap)

    chunks: list[TextChunk] = []
    number = 0

    for page in pages:
        paragraphs = _split_paragraphs(page.text)
        if not paragraphs:
            continue

        buffer = ""
        buffer_page = page.page_number

        for para in paragraphs:
            if len(para) > size:
                if buffer.strip():
                    chunks.append(
                        _make_chunk(number, buffer, buffer_page)
                    )
                    number += 1
                    buffer = ""

                for piece in _window_split(para, size, overlap):
                    chunks.append(_make_chunk(number, piece, page.page_number))
                    number += 1
                continue

            candidate = f"{buffer}\n\n{para}".strip() if buffer else para
            if len(candidate) <= size:
                buffer = candidate
                buffer_page = page.page_number
            else:
                if buffer.strip():
                    chunks.append(_make_chunk(number, buffer, buffer_page))
                    number += 1
                buffer = para
                buffer_page = page.page_number

        if buffer.strip():
            chunks.append(_make_chunk(number, buffer, buffer_page))
            number += 1

    return chunks


def chunk_text(text: str) -> list[TextChunk]:
    """Chunk a single blob of text as page 1 (legacy helper)."""
    return chunk_pages([PageText(page_number=1, text=text)])


def _make_chunk(number: int, content: str, page_number: int) -> TextChunk:
    cleaned = content.strip()
    return TextChunk(
        chunk_number=number,
        content=cleaned,
        page_number=page_number,
        token_count=_approx_tokens(cleaned),
    )


def _validate_window(size: int, overlap: int) -> None:
    if size <= 0:
        raise ValueError("KNOWLEDGE_CHUNK_SIZE must be positive")
    if overlap < 0 or overlap >= size:
        raise ValueError("KNOWLEDGE_CHUNK_OVERLAP must be >= 0 and < chunk size")


def _split_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


def _window_split(text: str, size: int, overlap: int) -> list[str]:
    pieces: list[str] = []
    start = 0
    length = len(text)
    while start < length:
        end = min(start + size, length)
        piece = text[start:end].strip()
        if piece:
            pieces.append(piece)
        if end >= length:
            break
        start = end - overlap
    return pieces


def _approx_tokens(text: str) -> int:
    """Rough token estimate (~4 chars/token) — not a tokenizer dependency."""
    return max(1, len(text) // 4)
