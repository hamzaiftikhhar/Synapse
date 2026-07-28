"""Shared JSON extraction helpers for NLU providers."""

from __future__ import annotations

import json
import re
from typing import Any

from apps.chatbot.nlu.base import NLUError

_JSON_FENCE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


def parse_json_response(text: str) -> dict[str, Any]:
    """Parse model output into a dict, tolerating markdown fences."""
    if not text or not text.strip():
        raise NLUError("Empty NLU response from provider")

    cleaned = text.strip()
    fence = _JSON_FENCE.search(cleaned)
    if fence:
        cleaned = fence.group(1).strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise NLUError("NLU response is not valid JSON") from None
        try:
            data = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as exc:
            raise NLUError(f"Failed to parse NLU JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise NLUError("NLU JSON root must be an object")
    return data
