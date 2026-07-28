"""Intent & Entity service — application entry point for message NLU."""

from __future__ import annotations

import logging
import time
from typing import Any

from apps.clinics.models import Clinic
from apps.chatbot.nlu.base import NLUError, NLUProvider
from apps.chatbot.nlu.factory import get_nlu_provider
from apps.chatbot.nlu.resolvers import resolve_entities
from apps.chatbot.nlu.schemas import NLUResult, parse_nlu_payload

logger = logging.getLogger(__name__)


class IntentEntityService:
    """
    Classify user messages into structured intent/entities/routing flags.

    Callers use this class only — never import Gemini/OpenAI SDKs.
    """

    def __init__(self, provider: NLUProvider | None = None) -> None:
        self._provider = provider

    @property
    def provider(self) -> NLUProvider:
        return self._provider or get_nlu_provider()

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

        provider = self.provider
        started = time.perf_counter()
        try:
            raw = provider.classify(
                message=text,
                conversation_context=conversation_context,
            )
        except NLUError:
            raise
        except Exception as exc:
            raise NLUError(str(exc)) from exc

        latency_ms = int((time.perf_counter() - started) * 1000)
        usage = raw.pop("_usage", {}) if isinstance(raw, dict) else {}

        result = parse_nlu_payload(
            raw,
            provider=provider.provider_name,
            model=provider.model_name,
        )
        result.resolved_ids = resolve_entities(clinic, result.entities)

        if log_usage:
            self._log_usage(
                clinic=clinic,
                session=session,
                message_obj=message_obj,
                provider_name=provider.provider_name,
                model_name=provider.model_name,
                usage=usage if isinstance(usage, dict) else {},
                latency_ms=latency_ms,
                intent=result.intent.value,
            )

        logger.info(
            "NLU clinic=%s intent=%s confidence=%.2f provider=%s latency_ms=%s",
            clinic.id,
            result.intent.value,
            result.confidence,
            provider.provider_name,
            latency_ms,
        )
        return result

    @staticmethod
    def _log_usage(
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
            }
            prompt_tokens = int(usage.get("prompt_tokens") or 0)
            completion_tokens = int(usage.get("completion_tokens") or 0)
            total_tokens = int(
                usage.get("total_tokens") or (prompt_tokens + completion_tokens)
            )
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
                metadata={"intent": intent},
            )
        except Exception:
            logger.exception("Failed to write AIUsageLog for intent classification")
