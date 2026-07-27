"""Production-oriented RAG chunking — structure + sentence aware, no embeddings.

Pipeline stage only. Does not call OpenAI / Hugging Face / LangChain.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings

from apps.knowledge.pipeline.chunk_blocks import BlockKind, TextBlock, build_blocks
from apps.knowledge.pipeline.chunk_sentences import (
    join_sentences,
    split_sentences,
    take_overlap_sentences,
)
from apps.knowledge.pipeline.extract import PageText


@dataclass(frozen=True)
class TextChunk:
    chunk_number: int
    content: str
    heading: str = ""
    page_start: int | None = None
    page_end: int | None = None
    token_count: int | None = None
    chunk_type: str = "paragraph"  # paragraph | list | heading | mixed
    page_number: int | None = None  # alias of page_start (API back-compat)


@dataclass(frozen=True)
class _Unit:
    """A size-bounded piece ready to pack into a chunk."""

    text: str
    kind: BlockKind
    heading: str
    page_start: int
    page_end: int


def chunk_pages(pages: list[PageText]) -> list[TextChunk]:
    """
    Data in:  cleaned PageText list
    Data out: ordered TextChunk list with heading + page span + type
    """
    size = settings.KNOWLEDGE_CHUNK_SIZE
    overlap = settings.KNOWLEDGE_CHUNK_OVERLAP
    min_chars = int(getattr(settings, "KNOWLEDGE_CHUNK_MIN_CHARS", 40))
    _validate(size, overlap)

    blocks = build_blocks(pages)
    if not blocks:
        return []

    units = _blocks_to_units(blocks, size=size, overlap=overlap)
    raw = _pack_units_into_chunks(units, size=size, overlap_chars=overlap)
    return _finalize(raw, min_chars=min_chars)


def chunk_text(text: str) -> list[TextChunk]:
    return chunk_pages([PageText(page_number=1, text=text)])


def _blocks_to_units(
    blocks: list[TextBlock],
    *,
    size: int,
    overlap: int,
) -> list[_Unit]:
    """Expand blocks into units that each fit under `size` when possible."""
    units: list[_Unit] = []
    current_heading = ""

    for block in blocks:
        if block.kind == BlockKind.HEADING:
            current_heading = block.heading or block.text
            continue

        heading = block.heading or current_heading
        pages = (block.page_start, block.page_end)

        if len(block.text) <= size:
            units.append(
                _Unit(block.text, block.kind, heading, pages[0], pages[1])
            )
            continue

        if block.kind == BlockKind.LIST:
            items = [ln.strip() for ln in block.text.split("\n") if ln.strip()]
            for text in _group_strings(items, size, sep="\n"):
                if len(text) <= size:
                    units.append(_Unit(text, block.kind, heading, *pages))
                else:
                    for hard in _hard_windows(text, size, overlap):
                        units.append(_Unit(hard, block.kind, heading, *pages))
            continue

        sentences = split_sentences(block.text)
        for text in _group_strings(sentences, size, sep=" "):
            if len(text) <= size:
                units.append(_Unit(text, BlockKind.PARAGRAPH, heading, *pages))
            else:
                for hard in _hard_windows(text, size, overlap):
                    units.append(
                        _Unit(hard, BlockKind.PARAGRAPH, heading, *pages)
                    )

    return units


def _group_strings(parts: list[str], size: int, *, sep: str) -> list[str]:
    groups: list[str] = []
    buf: list[str] = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if len(part) > size:
            if buf:
                groups.append(sep.join(buf))
                buf = []
            groups.append(part)
            continue
        candidate = sep.join(buf + [part]) if buf else part
        if len(candidate) <= size:
            buf.append(part)
        else:
            if buf:
                groups.append(sep.join(buf))
            buf = [part]
    if buf:
        groups.append(sep.join(buf))
    return groups


def _pack_units_into_chunks(
    units: list[_Unit],
    *,
    size: int,
    overlap_chars: int,
) -> list[TextChunk]:
    chunks: list[TextChunk] = []
    buf: list[_Unit] = []
    overlap_prefix = ""

    def buf_text() -> str:
        body = "\n\n".join(u.text for u in buf)
        if overlap_prefix and body:
            return f"{overlap_prefix}\n\n{body}"
        return overlap_prefix or body

    def emit() -> None:
        nonlocal overlap_prefix, buf
        content = buf_text().strip()
        if not content or not buf:
            buf = []
            overlap_prefix = ""
            return
        heading = next((u.heading for u in buf if u.heading), "")
        page_start = buf[0].page_start
        page_end = buf[-1].page_end
        kinds = [u.kind for u in buf]
        chunks.append(
            TextChunk(
                chunk_number=len(chunks),
                content=content,
                heading=heading,
                page_start=page_start,
                page_end=page_end,
                page_number=page_start,
                token_count=_approx_tokens(content),
                chunk_type=_resolve_type(kinds),
            )
        )
        # Sentence-based overlap for the next chunk
        overlap_prefix = join_sentences(
            take_overlap_sentences(split_sentences(content), overlap_chars)
        )
        buf = []

    for unit in units:
        tentative_buf = buf + [unit]
        body = "\n\n".join(u.text for u in tentative_buf)
        tentative = (
            f"{overlap_prefix}\n\n{body}".strip() if overlap_prefix else body
        )
        if len(tentative) <= size:
            buf.append(unit)
            continue

        if buf:
            emit()
            # Retry unit against fresh buffer (+ new overlap prefix)
            body = unit.text
            tentative = (
                f"{overlap_prefix}\n\n{body}".strip() if overlap_prefix else body
            )
            if len(tentative) <= size:
                buf.append(unit)
                continue
            # Overlap + unit too big — drop overlap for this unit
            overlap_prefix = ""
            buf.append(unit)
            if len(unit.text) > size:
                # Should be rare (units are pre-sized); emit alone
                emit()
            continue

        # Empty buffer but unit alone (maybe with leftover overlap) too big
        overlap_prefix = ""
        buf.append(unit)
        emit()

    if buf:
        emit()
    return chunks


def _hard_windows(text: str, size: int, overlap: int) -> list[str]:
    """Last resort: break on whitespace, never mid-word when possible."""
    pieces: list[str] = []
    start = 0
    length = len(text)
    while start < length:
        end = min(start + size, length)
        if end < length:
            space = text.rfind(" ", start, end)
            if space > start + size // 3:
                end = space
        piece = text[start:end].strip()
        if piece:
            pieces.append(piece)
        if end >= length:
            break
        next_start = max(end - overlap, start + 1) if overlap else end
        if next_start < length and not text[next_start].isspace():
            space = text.find(" ", next_start, min(next_start + 50, length))
            if space != -1:
                next_start = space + 1
        start = next_start
    return pieces


def _resolve_type(kinds: list[BlockKind]) -> str:
    unique = set(kinds)
    if not unique:
        return "paragraph"
    if unique == {BlockKind.LIST}:
        return "list"
    if unique == {BlockKind.HEADING}:
        return "heading"
    if unique == {BlockKind.PARAGRAPH}:
        return "paragraph"
    return "mixed"


def _finalize(chunks: list[TextChunk], *, min_chars: int) -> list[TextChunk]:
    kept: list[TextChunk] = []
    for ch in chunks:
        content = ch.content.strip()
        if not content:
            continue
        if len(content) < min_chars and ch.chunk_type != "heading":
            continue
        kept.append(
            TextChunk(
                chunk_number=len(kept),
                content=content,
                heading=ch.heading,
                page_start=ch.page_start,
                page_end=ch.page_end or ch.page_start,
                page_number=ch.page_start,
                token_count=_approx_tokens(content),
                chunk_type=ch.chunk_type,
            )
        )
    return kept


def _validate(size: int, overlap: int) -> None:
    if size <= 0:
        raise ValueError("KNOWLEDGE_CHUNK_SIZE must be positive")
    if overlap < 0 or overlap >= size:
        raise ValueError("KNOWLEDGE_CHUNK_OVERLAP must be >= 0 and < chunk size")


def _approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)
