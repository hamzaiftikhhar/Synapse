"""Normalize extracted text before chunking."""

from __future__ import annotations

import re


def clean_text(text: str) -> str:
    """Collapse whitespace and strip control characters."""
    text = text.replace("\x00", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
