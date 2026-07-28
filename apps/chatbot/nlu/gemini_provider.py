"""Gemini NLU provider via Google AI Studio REST API (no heavy SDK)."""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any

from django.conf import settings

from apps.chatbot.nlu.base import NLUError
from apps.chatbot.nlu.deadline import run_with_deadline
from apps.chatbot.nlu.json_utils import parse_json_response
from apps.chatbot.nlu.prompts import get_system_prompt, build_user_prompt
from apps.chatbot.nlu.timings import NLUTimings

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
        timeout: float | None = None,
    ) -> dict[str, Any]:
        if not self._api_key:
            raise NLUError("GOOGLE_API_KEY is not configured")

        if not self._api_key.startswith("AIza"):
            logger.warning(
                "GOOGLE_API_KEY does not start with 'AIza' — ensure it is from "
                "https://aistudio.google.com/apikey"
            )

        timings = NLUTimings()
        total_start = time.perf_counter()

        t0 = time.perf_counter()
        system_prompt = get_system_prompt()
        user_prompt = build_user_prompt(message, conversation_context)
        timings.prompt_construction_ms = (time.perf_counter() - t0) * 1000
        timings.system_chars = len(system_prompt)
        timings.prompt_chars = len(system_prompt) + len(user_prompt)

        payload = {
            "systemInstruction": {
                "parts": [{"text": system_prompt}],
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
                "maxOutputTokens": 256,
            },
        }

        t0 = time.perf_counter()
        url = _GEMINI_URL.format(model=self.model_name, api_key=self._api_key)
        body = json.dumps(payload).encode("utf-8")
        timings.payload_serialization_ms = (time.perf_counter() - t0) * 1000

        request = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        request_timeout = float(
            timeout if timeout is not None else getattr(settings, "NLU_API_TIMEOUT_SECONDS", 2.5)
        )

        def _do_request() -> str:
            with urllib.request.urlopen(request, timeout=request_timeout) as response:
                return response.read().decode("utf-8")

        try:
            t0 = time.perf_counter()
            # Hard wall-clock deadline — urllib alone can hang >20s on slow Gemini streams.
            raw_body = run_with_deadline(_do_request, seconds=request_timeout)
            timings.api_call_ms = (time.perf_counter() - t0) * 1000
            timings.response_read_ms = 0.0
        except TimeoutError as exc:
            timings.api_call_ms = (time.perf_counter() - t0) * 1000
            raise NLUError(f"Gemini API timed out after {request_timeout}s") from exc
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            logger.error("Gemini NLU HTTP %s: %s", exc.code, detail[:500])
            if exc.code == 429:
                raise NLUError(
                    f"Gemini quota exceeded for model {self.model_name!r}. "
                    "Try a flash/lite model or NLU_PROVIDER=openai. "
                    f"Detail: {detail[:300]}"
                ) from exc
            raise NLUError(f"Gemini API error {exc.code}: {detail[:500]}") from exc
        except urllib.error.URLError as exc:
            reason = str(getattr(exc, "reason", exc)).lower()
            if "timed out" in reason or "timeout" in reason:
                raise NLUError(f"Gemini API timed out after {request_timeout}s") from exc
            raise NLUError(f"Gemini API connection failed: {exc}") from exc

        t0 = time.perf_counter()
        try:
            envelope = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise NLUError("Gemini returned non-JSON envelope") from exc
        timings.envelope_parse_ms = (time.perf_counter() - t0) * 1000

        t0 = time.perf_counter()
        text = _extract_text(envelope)
        data = parse_json_response(text)
        timings.nlu_json_parse_ms = (time.perf_counter() - t0) * 1000

        usage_meta = envelope.get("usageMetadata") or {}
        timings.prompt_tokens = int(usage_meta.get("promptTokenCount") or 0)
        timings.completion_tokens = int(usage_meta.get("candidatesTokenCount") or 0)
        timings.total_tokens = int(usage_meta.get("totalTokenCount") or 0)
        timings.total_ms = (time.perf_counter() - total_start) * 1000

        data["_usage"] = {
            "prompt_tokens": timings.prompt_tokens,
            "completion_tokens": timings.completion_tokens,
            "total_tokens": timings.total_tokens,
        }
        data["_timings"] = timings.to_dict()
        data["_classifier_source"] = self.provider_name

        logger.info(
            "Gemini NLU timing model=%s prompt_build=%.1fms serialize=%.1fms "
            "api_call=%.1fms read=%.1fms envelope=%.1fms nlu_parse=%.1fms "
            "total=%.1fms tokens_in=%s tokens_out=%s prompt_chars=%s",
            self.model_name,
            timings.prompt_construction_ms,
            timings.payload_serialization_ms,
            timings.api_call_ms,
            timings.response_read_ms,
            timings.envelope_parse_ms,
            timings.nlu_json_parse_ms,
            timings.total_ms,
            timings.prompt_tokens,
            timings.completion_tokens,
            timings.prompt_chars,
        )
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
