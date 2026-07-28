"""OpenAI NLU provider (swap via NLU_PROVIDER=openai)."""

from __future__ import annotations

import logging
from typing import Any

from apps.chatbot.nlu.base import NLUError
from apps.chatbot.nlu.json_utils import parse_json_response
from apps.chatbot.nlu.prompts import SYSTEM_PROMPT, build_user_prompt

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
    ) -> dict[str, Any]:
        if not self._api_key:
            raise NLUError("OPENAI_API_KEY is not configured")

        try:
            from openai import OpenAI
        except ImportError as exc:
            raise NLUError("openai package is not installed") from exc

        client = OpenAI(api_key=self._api_key)
        user_prompt = build_user_prompt(message, conversation_context)

        try:
            response = client.chat.completions.create(
                model=self.model_name,
                temperature=0.1,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
            )
        except Exception as exc:
            logger.exception("OpenAI NLU classify failed")
            raise NLUError(str(exc)) from exc

        choice = response.choices[0].message.content or ""
        data = parse_json_response(choice)
        usage = response.usage
        data["_usage"] = {
            "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
            "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
            "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
        }
        return data
