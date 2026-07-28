"""Gemini NLU provider via Google AI Studio REST API (no heavy SDK)."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

from apps.chatbot.nlu.base import NLUError
from apps.chatbot.nlu.json_utils import parse_json_response
from apps.chatbot.nlu.prompts import SYSTEM_PROMPT, build_user_prompt

logger = logging.getLogger(__name__)

_GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "{model}:generateContent?key={api_key}"
)


class GeminiNLUProvider:
    """Google Gemini structured JSON classifier (HTTP)."""

    provider_name = "gemini"

    def __init__(self, *, model_name: str, api_key: str) -> None:
        self.model_name = model_name
        self._api_key = api_key

    def classify(
        self,
        *,
        message: str,
        conversation_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self._api_key:
            raise NLUError("GOOGLE_API_KEY is not configured")

        user_prompt = build_user_prompt(message, conversation_context)
        payload = {
            "systemInstruction": {
                "parts": [{"text": SYSTEM_PROMPT}],
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": user_prompt}],
                }
            ],
            "generationConfig": {
                "temperature": 0.1,
                "responseMimeType": "application/json",
            },
        }

        url = _GEMINI_URL.format(model=self.model_name, api_key=self._api_key)
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                raw_body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            logger.error("Gemini NLU HTTP %s: %s", exc.code, detail)
            raise NLUError(f"Gemini API error {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise NLUError(f"Gemini API connection failed: {exc}") from exc

        try:
            envelope = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise NLUError("Gemini returned non-JSON envelope") from exc

        text = _extract_text(envelope)
        data = parse_json_response(text)

        usage_meta = envelope.get("usageMetadata") or {}
        data["_usage"] = {
            "prompt_tokens": int(usage_meta.get("promptTokenCount") or 0),
            "completion_tokens": int(usage_meta.get("candidatesTokenCount") or 0),
            "total_tokens": int(usage_meta.get("totalTokenCount") or 0),
        }
        return data


def _extract_text(envelope: dict[str, Any]) -> str:
    candidates = envelope.get("candidates") or []
    if not candidates:
        raise NLUError("Gemini returned no candidates")
    parts = (((candidates[0] or {}).get("content") or {}).get("parts")) or []
    texts = [p.get("text", "") for p in parts if isinstance(p, dict)]
    text = "".join(texts).strip()
    if not text:
        raise NLUError("Gemini returned empty content")
    return text
