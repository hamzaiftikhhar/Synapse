"""Normalize extracted text before chunking.

Why this file exists
--------------------
PDFs often contain odd whitespace and control characters.
Cleaning must not change medical meaning — only normalize shape.
"""

from __future__ import annotations

import re


def clean_text(text: str) -> str:
    """
    Data in:  raw page or document text
    Data out: cleaned text (paragraphs preserved)

    Rules:
    - strip null / control chars (keep \\n and \\t then normalize)
    - collapse runs of spaces/tabs on a line
    - collapse 3+ newlines → 2 (paragraph break)
    - do NOT rewrite clinical wording
    """
    if not text:
        return ""

    text = text.replace("\x00", "")
    # Drop other C0 controls except tab/newline/carriage return
    text = re.sub(r"[\x01-\x08\x0b\x0c\x0e-\x1f]", "", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Soft hyphen / form feed leftovers from PDFs
    text = text.replace("\u00ad", "").replace("\x0c", "\n")
    return text.strip()
