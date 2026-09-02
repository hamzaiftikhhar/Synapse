"""Intent & Entity service — application entry point for message NLU."""

from __future__ import annotations

import logging
import time
from typing import Any

from django.conf import settings

from apps.clinics.models import Clinic
from apps.chatbot.nlu.base import NLUError, NLUProvider
from apps.chatbot.nlu.classifier import classify_message
from apps.chatbot.nlu.resolvers import resolve_entities
from apps.chatbot.nlu.schemas import NLUResult, parse_nlu_payload
from apps.chatbot.nlu.timings import NLUTimings

logger = logging.getLogger(__name__)


class IntentEntityService:
    """
    Classify user messages into structured intent/entities/routing flags.

    Callers use this class only — never import Gemini/OpenAI SDKs.
    """

    def __init__(self, provider: NLUProvider | None = None) -> None:
        self._provider = provider

    def analyze(
        self,
        *,
        clinic: Clinic,
        message: str,
        conversation_context: dict[str, Any] | None = None,
        session=None,
        message_obj=None,
        log_usage: bool = True,
    ) -> NLUResult:
        text = (message or "").strip()
        if not text:
            raise NLUError("Message is empty")

        started = time.perf_counter()
        raw: dict[str, Any] | None = None
        if self._provider is None and getattr(settings, "NLU_TIER1_ENABLED", True):
            from apps.chatbot.nlu.tier1 import try_catalog_fast_path

            raw = try_catalog_fast_path(clinic, text)
        if raw is None:
            try:
                raw = classify_message(
                    message=text,
                    conversation_context=conversation_context,
                    provider=self._provider,
                )
            except NLUError:
                raise
            except Exception as exc:
                raise NLUError(str(exc)) from exc

        latency_ms = int((time.perf_counter() - started) * 1000)
        usage = raw.pop("_usage", {}) if isinstance(raw, dict) else {}
        timings_raw = raw.pop("_timings", {}) if isinstance(raw, dict) else {}
        classifier_source = raw.pop("_classifier_source", "unknown")

        # Phase 45 bug found during audit: Tier 1 sources ("tier1_insurance"
        # etc.) fell through this check unrecognized, so a Tier 1 hit (zero
        # LLM tokens, zero real API call) got its provider/model silently
        # overwritten to the real LLM provider below and then logged to
        # AIUsageLog as if it were a genuine (0-token) "openai" call —
        # polluting usage/cost analytics and making Tier 1's actual bypass
        # rate unmeasurable from that table. rules_fast/strong/fallback are
        # the pre-existing non-LLM sources; classifier_source.startswith("tier1_")
        # covers every current and future Tier 1 category by construction,
        # not by naming each one here.
        is_non_llm_source = classifier_source.startswith("tier1_") or classifier_source in {
            "rules_fast",
            "rules_strong",
            "rules_fallback",
        }
        provider_name = classifier_source
        model_name = getattr(self._provider, "model_name", "") if self._provider else ""
        if is_non_llm_source:
            model_name = classifier_source
        elif not model_name:
            from apps.chatbot.nlu.factory import get_nlu_provider

            p = get_nlu_provider()
            provider_name = p.provider_name
            model_name = p.model_name

        result = parse_nlu_payload(
            raw,
            provider=provider_name,
            model=model_name,
        )
        result = _apply_confidence_threshold(result)

        t0 = time.perf_counter()
        result.resolved_ids = resolve_entities(clinic, result.entities)
        entity_ms = (time.perf_counter() - t0) * 1000

        timings = _build_timings(timings_raw, entity_ms, latency_ms)
        timings.classifier_source = str(classifier_source)
        result.timings = timings

        if log_usage and not is_non_llm_source:
            self._log_usage(
                clinic=clinic,
                session=session,
                message_obj=message_obj,
                provider_name=provider_name,
                model_name=model_name,
                usage=usage if isinstance(usage, dict) else {},
                latency_ms=latency_ms,
                intent=result.intent.value,
            )

        logger.info(
            "NLU clinic=%s intent=%s confidence=%.2f source=%s "
            "total_ms=%.0f api_call_ms=%.0f local_ms=%.0f tokens_in=%s",
            clinic.id,
            result.intent.value,
            result.confidence,
            classifier_source,
            result.timings.total_ms,
            result.timings.api_call_ms,
            result.timings.non_api_ms,
            result.timings.prompt_tokens,
        )
        return result

    @staticmethod # staticmethod is a method that is bound to the class rather than the instance of the class.
    def _log_usage( # this is a method that is used to log the usage of the intent classification.
        *,
        clinic: Clinic,
        session,
        message_obj,
        provider_name: str,
        model_name: str,
        usage: dict[str, Any],
        latency_ms: int,
        intent: str,
    ) -> None:
        try:
            from apps.ai.models import AIOperation, AIProvider, AIUsageLog

            provider_map = {
                "gemini": AIProvider.GEMINI,
                "openai": AIProvider.OPENAI,
                "openai_fallback": AIProvider.OPENAI,
            }
            prompt_tokens = int(usage.get("prompt_tokens") or 0)
            completion_tokens = int(usage.get("completion_tokens") or 0)
            total_tokens = int(
                usage.get("total_tokens") or (prompt_tokens + completion_tokens)
            )
            from apps.ai.pricing import estimate_usd, usd_to_microcents

            AIUsageLog.objects.create(
                clinic=clinic,
                session=session,
                message=message_obj,
                provider=provider_map.get(provider_name, AIProvider.GEMINI),
                operation=AIOperation.INTENT_CLASSIFICATION,
                model=model_name[:50],
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                latency_ms=latency_ms,
                cost_microcents=usd_to_microcents(
                    estimate_usd(
                        model=model_name,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                    )
                ),
                metadata={"intent": intent},
            )
        except Exception:
            logger.exception("Failed to write AIUsageLog for intent classification")


def _apply_confidence_threshold(result: NLUResult) -> NLUResult:
    threshold = getattr(settings, "NLU_CONFIDENCE_THRESHOLD", 0.75)
    if (
        result.confidence < threshold
        and not result.is_emergency
        and not result.can_respond_directly
        and not result.clarification_needed
    ):
        result.clarification_needed = True
        result.clarification_question = (
            "I'm not fully sure what you need — could you tell me a bit more?"
        )
        result.reasoning_short = (
            result.reasoning_short or "Low confidence — asking for clarification"
        )
    return result


def _build_timings(
    raw: dict[str, Any],
    entity_ms: float,
    fallback_total_ms: int,
) -> NLUTimings:
    fields = NLUTimings.__dataclass_fields__
    values: dict[str, Any] = {}
    for key in fields:
        default = fields[key].default
        val = raw.get(key, default)
        if key == "classifier_source":
            values[key] = str(val or "")
        elif isinstance(default, int):
            values[key] = int(val or 0)
        else:
            values[key] = float(val or 0.0)
    timings = NLUTimings(**values)
    timings.entity_resolution_ms = entity_ms
    if not timings.total_ms:
        timings.total_ms = float(fallback_total_ms)
    return timings
