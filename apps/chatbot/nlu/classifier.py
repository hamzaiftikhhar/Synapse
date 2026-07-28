"""Classifier with rules fast-path, timeout, retry, and provider fallback."""

from __future__ import annotations

import logging
import time
from typing import Any

from django.conf import settings

from apps.chatbot.nlu.base import NLUError, NLUProvider
from apps.chatbot.nlu.factory import get_nlu_provider
from apps.chatbot.nlu.openai_provider import OpenAINLUProvider
from apps.chatbot.nlu.rules import try_rule_classify
from apps.chatbot.nlu.timings import NLUTimings

logger = logging.getLogger(__name__)


def classify_message(
    *,
    message: str,
    conversation_context: dict[str, Any] | None = None,
    provider: NLUProvider | None = None,
) -> dict[str, Any]:
    """
    Classify a message: rules → LLM (timeout + retry) → OpenAI fallback → rules fallback.
    """
    started = time.perf_counter()

    if getattr(settings, "NLU_ENABLE_RULES", True):
        fast = try_rule_classify(message, tier="fast")
        if fast is not None:
            return _finalize_rules(fast, started)

        if getattr(settings, "NLU_RULES_BEFORE_LLM", True):
            strong = try_rule_classify(message, tier="strong")
            if strong is not None:
                return _finalize_rules(strong, started)

    primary = provider or get_nlu_provider()
    timeout = getattr(settings, "NLU_API_TIMEOUT_SECONDS", 8)
    last_error: NLUError | None = None

    for attempt in range(2):
        try:
            raw = primary.classify(
                message=message,
                conversation_context=conversation_context,
                timeout=timeout,
            )
            if isinstance(raw, dict):
                raw.setdefault("_classifier_source", primary.provider_name)
            return raw
        except NLUError as exc:
            last_error = exc
            is_timeout = _is_timeout_error(exc)
            logger.warning(
                "NLU provider %s attempt %s failed (timeout=%s): %s",
                primary.provider_name,
                attempt + 1,
                is_timeout,
                exc,
            )
            if not is_timeout and attempt == 0:
                break

    # OpenAI fallback when primary is Gemini
    if (
        primary.provider_name == "gemini"
        and settings.OPENAI_API_KEY
        and getattr(settings, "NLU_FALLBACK_OPENAI", True)
    ):
        fallback_model = getattr(
            settings, "NLU_FALLBACK_MODEL", "gpt-4o-mini"
        )
        logger.info("NLU falling back to OpenAI model=%s", fallback_model)
        try:
            fb = OpenAINLUProvider(
                model_name=fallback_model,
                api_key=settings.OPENAI_API_KEY,
            )
            raw = fb.classify(
                message=message,
                conversation_context=conversation_context,
                timeout=timeout,
            )
            if isinstance(raw, dict):
                raw["_classifier_source"] = "openai_fallback"
            return raw
        except NLUError as exc:
            last_error = exc
            logger.warning("OpenAI NLU fallback failed: %s", exc)

    if getattr(settings, "NLU_ENABLE_RULES", True):
        fallback_rule = try_rule_classify(message, tier="fallback")
        if fallback_rule is not None:
            logger.info("NLU using rules fallback after provider failure")
            return _finalize_rules(fallback_rule, started)

    raise last_error or NLUError("NLU classification failed")


def _finalize_rules(payload: dict[str, Any], started: float) -> dict[str, Any]:
    elapsed = (time.perf_counter() - started) * 1000
    source = payload.pop("_classifier_source", "rules")
    payload["_classifier_source"] = source
    payload["_usage"] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    payload["_timings"] = NLUTimings(
        api_call_ms=0.0,
        total_ms=elapsed,
        classifier_source=source,
    ).to_dict()
    return payload


def _is_timeout_error(exc: NLUError) -> bool:
    msg = str(exc).lower()
    return "timeout" in msg or "timed out" in msg
