"""Split text into chunks — independent of embedding provider."""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings


@dataclass(frozen=True)
class TextChunk:
    chunk_number: int
    content: str
    page_number: int | None = None
    token_count: int | None = None


def chunk_text(text: str) -> list[TextChunk]:
    """
    Character-window chunking with overlap.

    Chunking strategy is decoupled from OpenAI — swap this module to change
    splitting without touching embed.py.
    """
    size = settings.KNOWLEDGE_CHUNK_SIZE
    overlap = settings.KNOWLEDGE_CHUNK_OVERLAP
    if size <= 0:
        raise ValueError("KNOWLEDGE_CHUNK_SIZE must be positive")
    if overlap >= size:
        raise ValueError("KNOWLEDGE_CHUNK_OVERLAP must be less than chunk size")

    chunks: list[TextChunk] = []
    start = 0
    number = 0
    text_len = len(text)

    while start < text_len:
        end = min(start + size, text_len)
        content = text[start:end].strip()
        if content:
            chunks.append(TextChunk(chunk_number=number, content=content))
            number += 1
        if end >= text_len:
            break
        start = end - overlap

    return chunks
