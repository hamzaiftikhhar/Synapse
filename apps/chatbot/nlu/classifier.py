"""Classifier with safety/phatic fast-path, Small-LLM-first, and fallback."""

from __future__ import annotations

import logging
import time
from typing import Any

from django.conf import settings

from apps.chatbot.nlu.base import NLUError, NLUProvider
from apps.chatbot.nlu.entity_extract import (
    extract_entities,
    extract_emergency_symptoms,
    has_symptom_cues,
    merge_entities,
)
from apps.chatbot.nlu.factory import get_nlu_provider
from apps.chatbot.nlu.openai_provider import OpenAINLUProvider
from apps.chatbot.nlu.rules import try_rule_classify
from apps.chatbot.nlu.timings import NLUTimings

logger = logging.getLogger(__name__)

_TIMEOUT_CLARIFY = (
    "I want to make sure I help with the right thing. "
    "Would you like to find a doctor, book an appointment, "
    "check clinic hours, or ask about insurance?"
)


def classify_message(
    *,
    message: str,
    conversation_context: dict[str, Any] | None = None,
    provider: NLUProvider | None = None,
) -> dict[str, Any]:
    """
    Classify a message:

    safety (emergency) → rules_fast (phatic) → [optional rules_strong]
    → Small LLM → OpenAI fallback (incl. timeout) → rules_fallback / clarify
    """
    started = time.perf_counter()

    if getattr(settings, "NLU_ENABLE_RULES", True):
        # Gate A — emergency / narrative cardiac (fail-closed, never wait on LLM)
        safety = try_rule_classify(message, tier="safety")
        if safety is not None:
            return _finalize_rules(safety, started)
        if has_symptom_cues(message) and extract_emergency_symptoms(message):
            # Extra narrative emergency catch even if strong regex missed phrasing
            symptoms = extract_emergency_symptoms(message)
            return _finalize_rules(
                {
                    "intent": "emergency",
                    "secondary_intents": [],
                    "confidence": 0.98,
                    "entities": {**extract_entities(message), "symptom": symptoms},
                    "needs_sql": False,
                    "needs_vector": False,
                    "needs_llm": False,
                    "can_respond_directly": True,
                    "is_emergency": True,
                    "is_off_topic": False,
                    "clarification_needed": False,
                    "clarification_question": None,
                    "reasoning_short": "Emergency narrative (safety gate)",
                    "_classifier_source": "rules_safety",
                },
                started,
            )

        # Gate B — phatic only
        fast = try_rule_classify(message, tier="fast")
        if fast is not None:
            return _finalize_rules(fast, started)

        # Strong semantic rules only when explicitly enabled (default: False)
        if getattr(settings, "NLU_RULES_BEFORE_LLM", False):
            strong = try_rule_classify(message, tier="strong")
            if strong is not None:
                return _finalize_rules(strong, started)

    primary = provider or get_nlu_provider()
    timeout = float(getattr(settings, "NLU_API_TIMEOUT_SECONDS", 3.5))
    last_error: NLUError | None = None

    try:
        raw = primary.classify(
            message=message,
            conversation_context=conversation_context,
            timeout=timeout,
        )
        if isinstance(raw, dict):
            raw.setdefault("_classifier_source", primary.provider_name)
            raw["entities"] = merge_entities(
                raw.get("entities") if isinstance(raw.get("entities"), dict) else {},
                extract_entities(message),
            )
            # Fail-closed: elevate emergency if cue present but LLM missed it
            if has_symptom_cues(message) and not raw.get("is_emergency"):
                symptoms = extract_emergency_symptoms(message)
                if symptoms or has_symptom_cues(message):
                    raw["intent"] = "emergency"
                    raw["is_emergency"] = True
                    raw["can_respond_directly"] = True
                    raw["needs_sql"] = False
                    raw["needs_vector"] = False
                    raw["needs_llm"] = False
                    ents = raw.get("entities") if isinstance(raw.get("entities"), dict) else {}
                    ents["symptom"] = symptoms or ents.get("symptom")
                    raw["entities"] = ents
        return raw
    except NLUError as exc:
        last_error = exc
        logger.warning(
            "NLU provider %s failed (timeout=%s): %s",
            primary.provider_name,
            _is_timeout_error(exc),
            exc,
        )

    allow_timeout_fallback = bool(
        getattr(settings, "NLU_FALLBACK_ON_TIMEOUT", True)
    )
    if (
        primary.provider_name == "gemini"
        and settings.OPENAI_API_KEY
        and getattr(settings, "NLU_FALLBACK_OPENAI", True)
        and (allow_timeout_fallback or not _is_timeout_error(last_error))
    ):
        fallback_model = getattr(settings, "NLU_FALLBACK_MODEL", "gpt-4.1-mini")
        logger.info("NLU falling back to OpenAI model=%s", fallback_model)
        try:
            fb = OpenAINLUProvider(
                model_name=fallback_model,
                api_key=settings.OPENAI_API_KEY,
            )
            # Shorter budget on fallback to stay under client timeout
            fb_timeout = min(timeout, 3.0)
            raw = fb.classify(
                message=message,
                conversation_context=conversation_context,
                timeout=fb_timeout,
            )
            if isinstance(raw, dict):
                raw["_classifier_source"] = "openai_fallback"
                raw["entities"] = merge_entities(
                    raw.get("entities") if isinstance(raw.get("entities"), dict) else {},
                    extract_entities(message),
                )
                if has_symptom_cues(message):
                    raw["intent"] = "emergency"
                    raw["is_emergency"] = True
                    raw["can_respond_directly"] = True
            return raw
        except NLUError as exc:
            last_error = exc
            logger.warning("OpenAI NLU fallback failed: %s", exc)

    # Safety again after provider failure (chest-pressure should never clarify)
    if has_symptom_cues(message):
        symptoms = extract_emergency_symptoms(message)
        return _finalize_rules(
            {
                "intent": "emergency",
                "secondary_intents": [],
                "confidence": 0.95,
                "entities": {**extract_entities(message), "symptom": symptoms or None},
                "needs_sql": False,
                "needs_vector": False,
                "needs_llm": False,
                "can_respond_directly": True,
                "is_emergency": True,
                "is_off_topic": False,
                "clarification_needed": False,
                "clarification_question": None,
                "reasoning_short": "Emergency after NLU failure (safety gate)",
                "_classifier_source": "rules_safety",
            },
            started,
        )

    if getattr(settings, "NLU_ENABLE_RULES", True):
        fallback_rule = try_rule_classify(message, tier="fallback")
        if fallback_rule is not None:
            logger.info("NLU using rules fallback after provider failure")
            return _finalize_rules(fallback_rule, started)

    logger.info("NLU returning clarify fallback after provider failure")
    return _finalize_rules(
        {
            "intent": "unknown",
            "secondary_intents": [],
            "confidence": 0.5,
            "entities": extract_entities(message),
            "needs_sql": False,
            "needs_vector": False,
            "needs_llm": False,
            "can_respond_directly": False,
            "is_emergency": False,
            "is_off_topic": False,
            "clarification_needed": True,
            "clarification_question": _TIMEOUT_CLARIFY,
            "reasoning_short": "Provider timeout/error — clarification fallback",
            "_classifier_source": "rules_fallback",
        },
        started,
    )


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


def _is_timeout_error(exc: NLUError | None) -> bool:
    if exc is None:
        return False
    msg = str(exc).lower()
    return "timeout" in msg or "timed out" in msg
