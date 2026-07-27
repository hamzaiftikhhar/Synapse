"""Structural block detection for RAG chunking (no LLM).

Classifies lines into headings / lists / body / noise and groups them
into cross-page blocks that carry the nearest heading.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from enum import Enum

from apps.knowledge.pipeline.extract import PageText


class BlockKind(str, Enum):
    HEADING = "heading"
    LIST = "list"
    PARAGRAPH = "paragraph"


@dataclass(frozen=True)
class TextBlock:
    """A structural unit ready to pack into chunks."""

    kind: BlockKind
    text: str
    page_start: int
    page_end: int
    heading: str  # nearest heading at start of this block


# Minimum confidence (0–10 scale) required to classify a line as a heading.
_HEADING_CONFIDENCE_THRESHOLD = 3

# Single-word section titles common in academic PDFs (not generic nouns like "Learning").
_KNOWN_SINGLE_WORD_SECTIONS = frozenset(
    {
        "abstract",
        "introduction",
        "conclusion",
        "references",
        "bibliography",
        "acknowledgments",
        "acknowledgements",
        "appendix",
        "discussion",
        "methodology",
        "experiments",
        "background",
        "preliminaries",
        "summary",
    }
)

_RE_MD_HEADING = re.compile(r"^(#{1,6})\s+\S+")
_RE_NUMBERED_SECTION = re.compile(
    r"^(\d+(?:\.\d+){0,4})[.)]?\s+([A-Za-z].*)$"
)
_RE_BULLET = re.compile(r"^([•\-\*\u2022▪◦])\s+\S+")
_RE_PAGE_NUMBER = re.compile(
    r"^(?:page\s+)?\d+(?:\s*(?:of|/)\s*\d+)?$",
    re.IGNORECASE,
)
_RE_ONLY_PUNCT = re.compile(r"^[\W_]+$", re.UNICODE)
_RE_CAPTION = re.compile(
    r"^(?:table|figure|fig\.?)\s+\d+",
    re.IGNORECASE,
)
_RE_METRIC_TOKEN = re.compile(
    r"\b(?:mrr@?\d*|recall@?\d*|precision@?\d*|f1@?\d*|bleu@?\d*|"
    r"accuracy|f1|bleu|rouge|ndcg|map@?\d*|doc\s*len\.?|method)\b",
    re.IGNORECASE,
)
_RE_ABBREV_TOKEN = re.compile(r"^[A-Z]{1,3}\d*$")
_RE_SHORT_CODE_TOKEN = re.compile(r"^[A-Z]{1,2}[A-Za-z0-9]{0,2}$")
_RE_MODEL_NAME = re.compile(
    r"(?:gpt|llama|chatgpt|bert|roberta|t5|claude)[\w.-]*\d",
    re.IGNORECASE,
)
_RE_AUTHOR_SUFFIX = re.compile(r"\.{2,}\s*$")
_RE_MULTI_COMMA = re.compile(r",\s*[A-Z]")


def build_blocks(pages: list[PageText]) -> list[TextBlock]:
    """
    Flatten cleaned pages into structural blocks.

    Cross-page: a paragraph or list may span page_start..page_end.
    """
    if not pages:
        return []

    noise_lines = _detect_repeated_margins(pages)
    annotated = _annotate_lines(pages, noise_lines)
    return _group_blocks(annotated)


def _detect_repeated_margins(pages: list[PageText]) -> set[str]:
    """Lines that appear as first/last content on many pages → header/footer noise."""
    if len(pages) < 2:
        return set()

    tops: list[str] = []
    bottoms: list[str] = []
    for page in pages:
        lines = [ln.strip() for ln in page.text.split("\n") if ln.strip()]
        if not lines:
            continue
        tops.append(_normalize_margin(lines[0]))
        bottoms.append(_normalize_margin(lines[-1]))

    threshold = max(2, (len(pages) + 1) // 2)
    noise: set[str] = set()
    for counter in (Counter(tops), Counter(bottoms)):
        for line, count in counter.items():
            if line and count >= threshold and len(line) <= 80:
                noise.add(line)
    return noise


def _normalize_margin(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip().lower()


@dataclass
class _Line:
    text: str
    page: int
    role: str  # heading | list | body | blank | noise


@dataclass(frozen=True)
class _HeadingContext:
    """Surrounding lines used for heading confidence scoring."""

    prev_blank: bool
    next_blank: bool
    next_text: str | None
    in_references: bool


def _annotate_lines(pages: list[PageText], noise_lines: set[str]) -> list[_Line]:
    out: list[_Line] = []
    in_references = False

    # Flatten to (page, text) first so we can peek prev/next across the doc.
    flat: list[tuple[int, str]] = []
    for page in pages:
        for raw in page.text.split("\n"):
            flat.append((page.page_number, raw.strip()))

    for idx, (page_num, text) in enumerate(flat):
        if not text:
            out.append(_Line(text="", page=page_num, role="blank"))
            continue

        if _is_noise(text, noise_lines):
            out.append(_Line(text=text, page=page_num, role="noise"))
            continue

        if _is_list_item(text):
            out.append(_Line(text=text, page=page_num, role="list"))
            continue

        ctx = _heading_context(flat, idx, in_references)
        if _is_heading(text, ctx):
            out.append(_Line(text=text, page=page_num, role="heading"))
            if _is_references_section_heading(text):
                in_references = True
            continue

        out.append(_Line(text=text, page=page_num, role="body"))

    return out


def _heading_context(
    flat: list[tuple[int, str]],
    idx: int,
    in_references: bool,
) -> _HeadingContext:
    prev_blank = idx == 0 or not flat[idx - 1][1]
    next_text: str | None = None
    next_blank = True
    for j in range(idx + 1, len(flat)):
        nxt = flat[j][1]
        if not nxt:
            continue
        next_text = nxt
        next_blank = False
        break
    else:
        next_blank = True
    return _HeadingContext(
        prev_blank=prev_blank,
        next_blank=next_blank,
        next_text=next_text,
        in_references=in_references,
    )


def _is_noise(text: str, noise_lines: set[str]) -> bool:
    if _RE_PAGE_NUMBER.match(text):
        return True
    if _RE_ONLY_PUNCT.match(text):
        return True
    alnum = sum(ch.isalnum() for ch in text)
    if len(text) <= 3 and alnum == 0:
        return True
    if _normalize_margin(text) in noise_lines:
        return True
    return False


# ── Heading rejection heuristics ───────────────────────────────────────────


def _looks_like_caption(text: str) -> bool:
    """Table/Figure labels are captions, not section headings."""
    return bool(_RE_CAPTION.match(text.strip()))


def _looks_like_author_line(text: str) -> bool:
    """
    Bibliography author lines: comma-separated names or 'Name Name...' tails.

    Rejects: 'Tianqi Chen, Bing Xu', 'Pradeep Dasigi...'
    """
    if _RE_AUTHOR_SUFFIX.search(text):
        return True
    if text.count(",") >= 2:
        return True
    if text.count(",") == 1 and _RE_MULTI_COMMA.search(text):
        # "First Last, First Last" pattern
        parts = [p.strip() for p in text.split(",")]
        if len(parts) >= 2 and all(_looks_like_person_name(p) for p in parts[:2]):
            return True
    # "Tianqi Chen" alone with no section marker — often author in references
    words = text.split()
    if 2 <= len(words) <= 4 and _looks_like_person_name(text):
        if not _RE_NUMBERED_SECTION.match(text) and not _RE_MD_HEADING.match(text):
            if text.endswith(".") or "..." in text:
                return True
    return False


def _looks_like_person_name(text: str) -> bool:
    """Two+ capitalized tokens typical of personal names."""
    tokens = [t for t in re.split(r"[\s,]+", text) if t]
    if len(tokens) < 2:
        return False
    caps = 0
    for tok in tokens[:4]:
        core = re.sub(r"[^A-Za-z]", "", tok)
        if len(core) >= 2 and core[0].isupper():
            caps += 1
    return caps >= 2


def _looks_like_numeric_line(text: str) -> bool:
    """
    Rows dominated by numbers / K-suffix counts.

    Rejects: '40K 30K 10K 90K', '88.3 91.5 79.4'
    """
    tokens = text.split()
    if not tokens:
        return False
    numeric = 0
    for tok in tokens:
        core = tok.strip(".,;:%")
        if re.fullmatch(r"[\d.]+[KkMmBb%]?", core):
            numeric += 1
        elif re.fullmatch(r"\d+\.\d+", core):
            numeric += 1
    if len(tokens) >= 3 and numeric / len(tokens) >= 0.5:
        return True
    if len(tokens) >= 2 and numeric == len(tokens):
        return True
    return False


def _is_abbrev_like_token(token: str) -> bool:
    """Short OCR/table codes: SE1, LE3, LEi, LEn."""
    core = token.rstrip(".,;:")
    if len(core) > 5:
        return False
    if _RE_ABBREV_TOKEN.match(core):
        return True
    if _RE_SHORT_CODE_TOKEN.match(core) and not core.islower():
        return True
    return False


def _looks_like_abbrev_token_line(text: str) -> bool:
    """
    OCR / table abbreviations: 'LE1 LEi LEn', 'SE1', 'SE3 LE3'.

    Most tokens are 1–3 letters + optional digit.
    """
    tokens = text.split()
    if not tokens or len(tokens) > 8:
        return False
    abbrev = sum(1 for t in tokens if _is_abbrev_like_token(t))
    if abbrev >= 2 and abbrev / len(tokens) >= 0.5:
        return True
    if len(tokens) == 1 and _is_abbrev_like_token(tokens[0]):
        return True
    return False


def _looks_like_table_row(text: str) -> bool:
    """
    Table rows: metric headers, dataset rows, model comparison lines.

    Rejects: 'Dataset Doc Len. Method MRR@10', 'Qasper, MultifieldQA, 2WikiMQA'
    """
    if _looks_like_numeric_line(text):
        return True
    if _RE_METRIC_TOKEN.search(text) and text.count(" ") >= 2:
        return True
    # Multiple dataset-like CamelCase tokens with commas
    camel_tokens = re.findall(r"\b[A-Z][a-zA-Z0-9]*[A-Z][a-zA-Z0-9]*\b", text)
    if text.count(",") >= 2 and len(camel_tokens) >= 2:
        return True
    if _RE_MODEL_NAME.search(text):
        return True
    # Stage III. 40K 30K — roman numeral label + numeric tail
    if re.match(r"^Stage\s+[IVXLC]+\.", text, re.IGNORECASE) and _looks_like_numeric_line(
        re.sub(r"^Stage\s+[IVXLC]+\.\s*", "", text, flags=re.IGNORECASE)
    ):
        return True
    # Many short tokens (column layout) without sentence structure
    tokens = text.split()
    if len(tokens) >= 5:
        short = sum(1 for t in tokens if len(t) <= 6)
        if short / len(tokens) >= 0.7 and not text.endswith("."):
            if _RE_METRIC_TOKEN.search(text) or _looks_like_numeric_line(text):
                return True
    return False


def _is_references_section_heading(text: str) -> bool:
    """True when this heading opens the references/bibliography section."""
    normalized = _strip_heading_markers(text).strip().lower()
    normalized = re.sub(r"[^\w\s]", "", normalized).strip()
    return normalized in {"references", "bibliography", "works cited"}


# ── Heading confidence scoring ───────────────────────────────────────────────


def _heading_confidence(text: str, ctx: _HeadingContext) -> int:
    """
    Deterministic score — higher means more likely a real section heading.

    Positive: markdown, numbered sections, ALL CAPS titles, layout cues.
    Negative: tables, authors, captions, numeric rows, references tail.
    """
    score = 0
    stripped = text.strip()

    if ctx.in_references:
        return -10

    # Hard rejects (strong negative)
    if _looks_like_caption(stripped):
        return -5
    if _looks_like_author_line(stripped):
        return -5
    if _looks_like_table_row(stripped):
        return -5
    if _looks_like_numeric_line(stripped):
        return -4
    if _looks_like_abbrev_token_line(stripped):
        return -4
    if stripped.count(",") >= 3:
        score -= 3
    elif stripped.count(",") >= 2:
        score -= 2

    # Positive signals
    if _RE_MD_HEADING.match(stripped):
        score += 4

    section_match = _RE_NUMBERED_SECTION.match(stripped)
    if section_match:
        title = section_match.group(2)
        if len(title) <= 80 and not _looks_like_table_row(stripped):
            score += 4
        if _is_title_case(title) or title.isupper():
            score += 1

    letters = [c for c in stripped if c.isalpha()]
    if letters and all(c.isupper() for c in letters) and 2 <= len(stripped) <= 80:
        if not _looks_like_abbrev_token_line(stripped):
            score += 3

    words = stripped.split()
    if len(words) == 1:
        if stripped.lower() in _KNOWN_SINGLE_WORD_SECTIONS:
            score += 3
        elif _is_title_case(stripped):
            # Single generic nouns ('Learning') are weak — do not boost
            score -= 1
    elif (
        not stripped.endswith((".", "?", "!"))
        and 2 <= len(words) <= 8
        and len(stripped) <= 70
        and _is_title_case(stripped)
    ):
        score += 2

    # Layout: headings often sit between blank lines
    if ctx.prev_blank:
        score += 1
    if ctx.next_blank:
        score += 1

    # Followed by paragraph-length body (not another table row)
    if ctx.next_text and len(ctx.next_text) > 60:
        if not _looks_like_table_row(ctx.next_text):
            score += 1

    # Trailing numeric cluster (e.g. 'Stage III. 40K 30K')
    trailing = stripped.split()[-4:]
    if len(trailing) >= 3 and sum(
        1 for t in trailing if re.match(r"^[\d.]+[KkMm%]?$", t)
    ) >= 2:
        score -= 3

    return score


def _is_heading(text: str, ctx: _HeadingContext) -> bool:
    if len(text) > 120:
        return False
    if _RE_BULLET.match(text):
        return False
    return _heading_confidence(text, ctx) >= _HEADING_CONFIDENCE_THRESHOLD


def _looks_like_list_sentence(text: str) -> bool:
    return bool(re.match(r"^\d+[.)]\s+.+\.$", text)) and len(text) > 60


def _is_title_case(text: str) -> bool:
    words = [w for w in re.split(r"\s+", text) if w]
    if not words:
        return False
    ok = 0
    for w in words:
        core = re.sub(r"[^A-Za-z]", "", w)
        if not core:
            return False
        if core[0].isupper():
            ok += 1
        elif core.lower() in {"a", "an", "the", "of", "and", "or", "for", "to", "in", "on"}:
            ok += 1
        else:
            return False
    return ok >= max(1, len(words) - 1)


def _is_list_item(text: str) -> bool:
    if _RE_BULLET.match(text):
        return True
    if re.match(r"^\d+[.)]\s+\S+", text) and not re.match(r"^\d+\.\d+", text):
        if _looks_like_list_sentence(text):
            return True
        if len(text) > 80:
            return True
        remainder = re.sub(r"^\d+[.)]\s+", "", text)
        if not _is_title_case(remainder):
            return True
    return False


def _group_blocks(lines: list[_Line]) -> list[TextBlock]:
    blocks: list[TextBlock] = []
    current_heading = ""
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]
        if line.role in {"blank", "noise"}:
            i += 1
            continue

        if line.role == "heading":
            current_heading = _strip_heading_markers(line.text)
            blocks.append(
                TextBlock(
                    kind=BlockKind.HEADING,
                    text=current_heading,
                    page_start=line.page,
                    page_end=line.page,
                    heading=current_heading,
                )
            )
            i += 1
            continue

        if line.role == "list":
            page_start = line.page
            page_end = line.page
            parts = [line.text]
            i += 1
            while i < n:
                nxt = lines[i]
                if nxt.role == "noise":
                    i += 1
                    continue
                if nxt.role == "blank":
                    j = i + 1
                    while j < n and lines[j].role in {"blank", "noise"}:
                        j += 1
                    if j < n and lines[j].role == "list":
                        i = j
                        continue
                    break
                if nxt.role != "list":
                    break
                parts.append(nxt.text)
                page_end = nxt.page
                i += 1
            blocks.append(
                TextBlock(
                    kind=BlockKind.LIST,
                    text="\n".join(parts),
                    page_start=page_start,
                    page_end=page_end,
                    heading=current_heading,
                )
            )
            continue

        page_start = line.page
        page_end = line.page
        parts = [line.text]
        i += 1
        while i < n:
            nxt = lines[i]
            if nxt.role == "noise":
                i += 1
                continue
            if nxt.role == "blank":
                break
            if nxt.role in {"heading", "list"}:
                break
            parts.append(nxt.text)
            page_end = nxt.page
            i += 1
        text = _join_paragraph_lines(parts)
        if text:
            blocks.append(
                TextBlock(
                    kind=BlockKind.PARAGRAPH,
                    text=text,
                    page_start=page_start,
                    page_end=page_end,
                    heading=current_heading,
                )
            )

    return blocks


def _strip_heading_markers(text: str) -> str:
    text = re.sub(r"^#{1,6}\s+", "", text)
    # Strip leading section numbers for display context
    text = re.sub(r"^\d+(?:\.\d+){0,4}[.)]?\s+", "", text)
    return text.strip()


def _join_paragraph_lines(parts: list[str]) -> str:
    if not parts:
        return ""
    out = parts[0]
    for nxt in parts[1:]:
        if out.endswith("-") and nxt and nxt[0].islower():
            out = out[:-1] + nxt
        else:
            out = f"{out} {nxt}"
    return re.sub(r"[ \t]+", " ", out).strip()
