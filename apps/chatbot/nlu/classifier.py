"""Classifier with safety/phatic/booking fast-path, OpenAI-primary, circuit-aware secondary."""

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
from apps.chatbot.nlu.gemini_provider import GeminiNLUProvider
from apps.chatbot.nlu.openai_provider import OpenAINLUProvider
from apps.chatbot.nlu.rules import try_rule_classify
from apps.chatbot.nlu.timings import NLUTimings
from apps.chatbot.providers import circuit_breaker

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

    safety → rules_fast (phatic/hours/booking) → [optional rules_strong]
    → primary LLM → secondary LLM (circuit-aware) → rules_fallback / clarify
    """
    started = time.perf_counter()
    # Cap catalog noise in NLU context
    if conversation_context:
        conversation_context = dict(conversation_context)
        catalog = conversation_context.get("document_catalog")
        if isinstance(catalog, str) and len(catalog) > 600:
            conversation_context["document_catalog"] = catalog[:600]
        services = conversation_context.get("services")
        if isinstance(services, str) and len(services) > 300:
            conversation_context["services"] = services[:300]
        # Drop bulky history blobs and booking drafts from Small LLM.
        # Leftover booking.date was being copied into entities.date.
        for key in ("history", "messages", "turns", "booking"):
            conversation_context.pop(key, None)

    if getattr(settings, "NLU_ENABLE_RULES", True):
        safety = try_rule_classify(message, tier="safety")
        if safety is not None:
            return _finalize_rules(safety, started, message=message)
        if has_symptom_cues(message) and extract_emergency_symptoms(message):
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
                message=message,
            )

        fast = try_rule_classify(message, tier="fast")
        if fast is not None:
            return _finalize_rules(fast, started, message=message)

        if getattr(settings, "NLU_RULES_BEFORE_LLM", False):
            strong = try_rule_classify(message, tier="strong")
            if strong is not None:
                return _finalize_rules(strong, started, message=message)

    timeout = float(getattr(settings, "NLU_API_TIMEOUT_SECONDS", 3.5))
    last_error: NLUError | None = None

    # Ordered provider attempts: configured primary, then secondary / mini fallback
    attempts = _provider_attempts(provider)
    for attempt in attempts:
        name = attempt["name"]
        if not circuit_breaker.is_available(name):
            logger.info("NLU skip provider=%s circuit_open", name)
            continue
        try:
            attempt_timeout = attempt.get("timeout")
            if attempt_timeout is None:
                attempt_timeout = timeout
            raw = attempt["provider"].classify(
                message=message,
                conversation_context=conversation_context,
                timeout=min(timeout, float(attempt_timeout)),
            )
            if isinstance(raw, dict):
                raw.setdefault("_classifier_source", name)
                raw["entities"] = merge_entities(
                    raw.get("entities") if isinstance(raw.get("entities"), dict) else {},
                    extract_entities(message),
                )
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
            circuit_breaker.record_success(name)
            return raw
        except NLUError as exc:
            last_error = exc
            circuit_breaker.record_failure(name, str(exc))
            logger.warning(
                "NLU provider %s failed (timeout=%s): %s",
                name,
                _is_timeout_error(exc),
                exc,
            )

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
            message=message,
        )

    if getattr(settings, "NLU_ENABLE_RULES", True):
        fallback_rule = try_rule_classify(message, tier="fallback")
        if fallback_rule is not None:
            logger.info("NLU using rules fallback after provider failure")
            return _finalize_rules(fallback_rule, started, message=message)

    logger.info("NLU returning clarify fallback after provider failure: %s", last_error)
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
            "_degraded": True,
        },
        started,
        message=message,
    )


def _provider_attempts(override: NLUProvider | None) -> list[dict[str, Any]]:
    """Build primary → secondary → mini-fallback chain."""
    if override is not None:
        return [{"name": override.provider_name, "provider": override, "timeout": None}]

    attempts: list[dict[str, Any]] = []
    primary = get_nlu_provider()
    attempts.append({"name": primary.provider_name, "provider": primary, "timeout": None})

    # If primary is openai nano, add mini as same-vendor accuracy/latency fallback
    if primary.provider_name == "openai" and settings.OPENAI_API_KEY:
        fb_model = getattr(settings, "NLU_FALLBACK_MODEL", "gpt-4.1-mini")
        if fb_model and fb_model != getattr(settings, "NLU_MODEL", ""):
            attempts.append(
                {
                    "name": "openai_fallback",
                    "provider": OpenAINLUProvider(
                        model_name=fb_model, api_key=settings.OPENAI_API_KEY
                    ),
                    "timeout": min(
                        float(getattr(settings, "NLU_API_TIMEOUT_SECONDS", 3.5)), 3.0
                    ),
                }
            )

    secondary = str(getattr(settings, "NLU_SECONDARY_PROVIDER", "") or "").lower().strip()
    if secondary == "gemini" and getattr(settings, "GOOGLE_API_KEY", ""):
        key = settings.GOOGLE_API_KEY
        # Skip obviously invalid AI Studio keys to avoid burning the budget
        if key.startswith("AIza"):
            model = getattr(settings, "NLU_SECONDARY_MODEL", "gemini-2.0-flash-lite")
            attempts.append(
                {
                    "name": "gemini",
                    "provider": GeminiNLUProvider(model_name=model, api_key=key),
                    "timeout": min(
                        float(getattr(settings, "NLU_API_TIMEOUT_SECONDS", 3.5)), 3.0
                    ),
                }
            )

    # Deduplicate by name
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for a in attempts:
        if a["name"] in seen:
            continue
        seen.add(a["name"])
        out.append(a)
    return out


def _finalize_rules(
    payload: dict[str, Any],
    started: float,
    *,
    message: str = "",
) -> dict[str, Any]:
    elapsed = (time.perf_counter() - started) * 1000
    source = payload.pop("_classifier_source", "rules")
    payload["_classifier_source"] = source
    # Always merge local date/time/etc. — rules historically returned empty entities.
    payload["entities"] = merge_entities(
        payload.get("entities") if isinstance(payload.get("entities"), dict) else {},
        extract_entities(message) if message else {},
    )
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
