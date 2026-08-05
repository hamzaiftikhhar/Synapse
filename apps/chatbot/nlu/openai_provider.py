"""OpenAI NLU provider (swap via NLU_PROVIDER=openai)."""

from __future__ import annotations

import logging
import time
from typing import Any

from django.conf import settings

from apps.chatbot.nlu.base import NLUError
from apps.chatbot.nlu.json_utils import parse_json_response
from apps.chatbot.nlu.prompts import build_user_prompt, get_system_prompt
from apps.chatbot.nlu.timings import NLUTimings

logger = logging.getLogger(__name__)


class OpenAINLUProvider:
    """OpenAI chat completions structured JSON classifier."""

    provider_name = "openai"

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
            raise NLUError("OPENAI_API_KEY is not configured")

        try:
            from openai import OpenAI
        except ImportError as exc:
            raise NLUError("openai package is not installed") from exc

        timings = NLUTimings()
        total_start = time.perf_counter()

        t0 = time.perf_counter()
        system_prompt = get_system_prompt()
        user_prompt = build_user_prompt(message, conversation_context)
        timings.prompt_construction_ms = (time.perf_counter() - t0) * 1000
        timings.system_chars = len(system_prompt)
        timings.prompt_chars = len(system_prompt) + len(user_prompt)

        from apps.chatbot.nlu.deadline import run_with_deadline

        request_timeout = float(
            timeout if timeout is not None else getattr(settings, "NLU_API_TIMEOUT_SECONDS", 3.5)
        )
        client = OpenAI(api_key=self._api_key, timeout=request_timeout)

        t0 = time.perf_counter()

        def _do_request():
            return client.chat.completions.create(
                model=self.model_name,
                temperature=0.1,
                max_tokens=256,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )

        try:
            response = run_with_deadline(_do_request, seconds=request_timeout)
        except TimeoutError as exc:
            timings.api_call_ms = (time.perf_counter() - t0) * 1000
            raise NLUError(f"OpenAI API timed out after {request_timeout}s") from exc
        except Exception as exc:
            logger.exception("OpenAI NLU classify failed")
            if "timeout" in str(exc).lower():
                raise NLUError(f"OpenAI API timed out after {request_timeout}s") from exc
            raise NLUError(str(exc)) from exc
        timings.api_call_ms = (time.perf_counter() - t0) * 1000

        t0 = time.perf_counter()
        choice = response.choices[0].message.content or ""
        data = parse_json_response(choice)
        timings.nlu_json_parse_ms = (time.perf_counter() - t0) * 1000

        usage = response.usage
        timings.prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        timings.completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        timings.total_tokens = int(getattr(usage, "total_tokens", 0) or 0)
        timings.total_ms = (time.perf_counter() - total_start) * 1000

        data["_usage"] = {
            "prompt_tokens": timings.prompt_tokens,
            "completion_tokens": timings.completion_tokens,
            "total_tokens": timings.total_tokens,
        }
        data["_timings"] = timings.to_dict()
        data["_classifier_source"] = self.provider_name

        logger.info(
            "OpenAI NLU timing model=%s prompt_build=%.1fms api_call=%.1fms "
            "nlu_parse=%.1fms total=%.1fms tokens_in=%s tokens_out=%s",
            self.model_name,
            timings.prompt_construction_ms,
            timings.api_call_ms,
            timings.nlu_json_parse_ms,
            timings.total_ms,
            timings.prompt_tokens,
            timings.completion_tokens,
        )
        return data
