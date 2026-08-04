"""Confidence-banded routing policy — recovery depth without inventing SQL lanes.

Bands (defaults; overridable via settings):
  >= high   Trust structured SQL / direct / booking decisions
  mid–high  SQL first; allow hybrid RAG if docs exist and answer may be thin
  low–mid   Prefer vector when catalog + knowledge; else clarify (never invent services)
  < low     Catalog + knowledge → vector once; else clarify
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from django.conf import settings

from apps.chatbot.nlu.schemas import Intent, NLUResult


class ConfidenceBand(str, Enum):
    HIGH = "high"
    MID = "mid"
    LOW = "low"
    VERY_LOW = "very_low"


@dataclass(frozen=True)
class ConfidencePolicyResult:
    nlu: NLUResult
    band: ConfidenceBand
    allow_hybrid: bool
    prefer_vector: bool
    prefer_clarify: bool
    reasoning: str


_SQL_TRUST = frozenset(
    {
        Intent.CLINIC_HOURS,
        Intent.CLINIC_LOCATION,
        Intent.INSURANCE_ACCEPTED,
        Intent.INSURANCE_VERIFICATION,
        Intent.DOCTOR_SEARCH,
        Intent.DOCTOR_AVAILABILITY,
        Intent.SERVICES_OFFERED,
        Intent.PRICING,
    }
)

_DIRECT_TRUST = frozenset(
    {
        Intent.GREETING,
        Intent.FAREWELL,
        Intent.OFF_TOPIC,
        Intent.EMERGENCY,
    }
)


def confidence_thresholds() -> tuple[float, float, float]:
    high = float(getattr(settings, "CHAT_CONFIDENCE_HIGH", 0.90))
    mid = float(getattr(settings, "CHAT_CONFIDENCE_MID", 0.70))
    low = float(getattr(settings, "CHAT_CONFIDENCE_LOW", 0.45))
    return high, mid, low


def band_for_confidence(confidence: float) -> ConfidenceBand:
    high, mid, low = confidence_thresholds()
    if confidence >= high:
        return ConfidenceBand.HIGH
    if confidence >= mid:
        return ConfidenceBand.MID
    if confidence >= low:
        return ConfidenceBand.LOW
    return ConfidenceBand.VERY_LOW


def apply_confidence_policy(
    nlu: NLUResult,
    *,
    has_catalog: bool = False,
    service_hit: bool = False,
    knowledge_q: bool = False,
) -> ConfidencePolicyResult:
    """
    Adjust routing flags from calibrated confidence.

    Does not invent intents from fuzzy service hits.
    service_hit is retained for hybrid hints only when intent is already SQL-trusted.
    """
    band = band_for_confidence(float(nlu.confidence or 0.0))
    needs_sql = bool(nlu.needs_sql)
    needs_vector = bool(nlu.needs_vector)
    needs_llm = bool(nlu.needs_llm)
    clarification_needed = bool(nlu.clarification_needed)
    intent = nlu.intent
    allow_hybrid = False
    prefer_vector = False
    prefer_clarify = False
    reason = f"band={band.value}"

    if intent in {Intent.EMERGENCY} or nlu.is_emergency:
        return ConfidencePolicyResult(
            nlu=nlu,
            band=band,
            allow_hybrid=False,
            prefer_vector=False,
            prefer_clarify=False,
            reasoning="emergency_trust",
        )

    if intent in _DIRECT_TRUST and band in {ConfidenceBand.HIGH, ConfidenceBand.MID}:
        return ConfidencePolicyResult(
            nlu=nlu,
            band=band,
            allow_hybrid=False,
            prefer_vector=False,
            prefer_clarify=False,
            reasoning="direct_trust",
        )

    if band == ConfidenceBand.HIGH:
        if intent in _SQL_TRUST:
            needs_vector = False if not knowledge_q else needs_vector
            needs_llm = needs_vector
            clarification_needed = False
            reason += "|trust_sql"
        allow_hybrid = bool(has_catalog and knowledge_q)

    elif band == ConfidenceBand.MID:
        if intent in _SQL_TRUST or needs_sql:
            allow_hybrid = bool(has_catalog)
            reason += "|sql_hybrid_ok"
        if intent in {Intent.UNKNOWN, Intent.FAQ} and has_catalog and knowledge_q:
            needs_vector = True
            needs_llm = True
            clarification_needed = False
            prefer_vector = True
            reason += "|mid_catalog_vector"
        elif intent == Intent.UNKNOWN and has_catalog and not knowledge_q:
            prefer_clarify = False
            reason += "|mid_unknown_hold"
        # Do NOT force SERVICES_OFFERED from service_hit at mid confidence

    elif band == ConfidenceBand.LOW:
        if has_catalog and (
            knowledge_q or intent == Intent.FAQ or intent == Intent.MEDICAL_QUESTION
        ):
            needs_vector = True
            needs_llm = True
            clarification_needed = False
            prefer_vector = True
            reason += "|low_prefer_vector"
        elif intent in _SQL_TRUST and needs_sql and float(nlu.confidence or 0) >= 0.70:
            # Only keep SQL when already high-ish structured intent — not timeout@0.5
            allow_hybrid = bool(has_catalog)
            clarification_needed = False
            reason += "|low_keep_sql"
        elif intent == Intent.UNKNOWN and has_catalog and knowledge_q:
            needs_vector = True
            needs_llm = True
            clarification_needed = False
            prefer_vector = True
            reason += "|low_unknown_knowledge"
        else:
            # Timeout / unknown / weak — clarify; never invent SQL from service_hit
            if intent == Intent.UNKNOWN or clarification_needed:
                prefer_clarify = True
                clarification_needed = True
                needs_sql = False
                reason += "|low_clarify"
            else:
                reason += "|low_hold"
        # Ignore unused service_hit for low-band invent
        _ = service_hit

    else:  # VERY_LOW
        if has_catalog and knowledge_q:
            needs_vector = True
            needs_llm = True
            clarification_needed = False
            prefer_vector = True
            intent = Intent.FAQ if intent == Intent.UNKNOWN else intent
            reason += "|vl_catalog_vector"
        elif intent in _SQL_TRUST and needs_sql and float(nlu.confidence or 0) >= 0.55:
            allow_hybrid = False
            clarification_needed = False
            reason += "|vl_weak_sql"
        else:
            clarification_needed = True
            prefer_clarify = True
            needs_sql = False
            reason += "|vl_clarify"

    if needs_llm and not needs_vector:
        needs_llm = False

    updated = NLUResult(
        intent=intent,
        secondary_intents=list(nlu.secondary_intents),
        confidence=nlu.confidence,
        entities=nlu.entities,
        resolved_ids=nlu.resolved_ids,
        needs_sql=needs_sql,
        needs_vector=needs_vector,
        needs_llm=needs_llm,
        can_respond_directly=nlu.can_respond_directly,
        is_emergency=nlu.is_emergency,
        is_off_topic=nlu.is_off_topic,
        clarification_needed=clarification_needed,
        clarification_question=nlu.clarification_question,
        reasoning_short=(nlu.reasoning_short or "") + f" | conf:{reason}",
        service_filter_mode=nlu.service_filter_mode,
        sql_tool=nlu.sql_tool,
        document_needed=bool(nlu.document_needed or needs_vector),
        provider=nlu.provider,
        model=nlu.model,
        timings=nlu.timings,
        raw=nlu.raw,
    )
    return ConfidencePolicyResult(
        nlu=updated,
        band=band,
        allow_hybrid=allow_hybrid,
        prefer_vector=prefer_vector,
        prefer_clarify=prefer_clarify,
        reasoning=reason,
    )


def confidence_meta(policy: ConfidencePolicyResult) -> dict[str, Any]:
    return {
        "confidence": policy.nlu.confidence,
        "confidence_band": policy.band.value,
        "allow_hybrid": policy.allow_hybrid,
        "prefer_vector": policy.prefer_vector,
        "prefer_clarify": policy.prefer_clarify,
        "confidence_reason": policy.reasoning,
    }
