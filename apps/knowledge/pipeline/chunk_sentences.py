"""Sentence splitting and sentence-based overlap (no external tokenizer)."""

from __future__ import annotations

import re

# Split after .?! when followed by whitespace + capital/quote/digit
_SENTENCE_END = re.compile(
    r"(?<=[.!?])\s+(?=[\"'“(\[]?[A-Z0-9])"
)

# Common abbreviations that should not end a sentence
_ABBREV = re.compile(
    r"\b(?:Dr|Mr|Mrs|Ms|Jr|Sr|vs|etc|approx|dept|est|fig|eq|"
    r"e\.g|i\.e|U\.S|U\.K|No)\.",
    re.IGNORECASE,
)


def split_sentences(text: str) -> list[str]:
    """
    Deterministic sentence split.

    Prefers punctuation boundaries; never returns empty strings.
    """
    text = text.strip()
    if not text:
        return []

    # Protect abbreviations by temporarily replacing their periods
    protected: list[str] = []

    def _protect(match: re.Match[str]) -> str:
        protected.append(match.group(0))
        return f"__ABBREV{len(protected) - 1}__"

    safe = _ABBREV.sub(_protect, text)
    parts = _SENTENCE_END.split(safe)
    sentences: list[str] = []
    for part in parts:
        restored = part
        for idx, original in enumerate(protected):
            restored = restored.replace(f"__ABBREV{idx}__", original)
        restored = restored.strip()
        if restored:
            sentences.append(restored)
    return sentences or [text]


def take_overlap_sentences(sentences: list[str], max_chars: int) -> list[str]:
    """
    Take complete trailing sentences whose total length fits max_chars.

    Used as semantic overlap when starting the next chunk.
    """
    if max_chars <= 0 or not sentences:
        return []
    chosen: list[str] = []
    total = 0
    for sentence in reversed(sentences):
        extra = len(sentence) + (1 if chosen else 0)
        if total + extra > max_chars and chosen:
            break
        if total + extra > max_chars and not chosen:
            # Single sentence longer than overlap budget — skip overlap
            break
        chosen.insert(0, sentence)
        total += extra
    return chosen


def join_sentences(sentences: list[str]) -> str:
    return " ".join(s.strip() for s in sentences if s.strip())
