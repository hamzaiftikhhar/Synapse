"""Confidence-banded routing policy — Small-LLM trust without regex sprawl.

Bands (defaults; overridable via settings):
  >= high   Trust structured SQL / direct / booking decisions
  mid–high  SQL first; allow hybrid RAG if docs exist and answer may be thin
  low–mid   Prefer vector when catalog exists; else clarify or weak SQL
  < low     Catalog → vector once; else clarify

Regex/heuristics remain a thin fast-path; confidence decides recovery depth.
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

    Does not invent intents — only widens/narrows SQL vs vector vs clarify.
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

    # Hard trusts — never demote safety / greetings / booking commits
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
        # Trust SQL for structured facts; don't open RAG unless already flagged
        if intent in _SQL_TRUST:
            needs_vector = False if not knowledge_q else needs_vector
            needs_llm = needs_vector
            clarification_needed = False
            reason += "|trust_sql"
        allow_hybrid = bool(has_catalog and knowledge_q)

    elif band == ConfidenceBand.MID:
        # SQL + optional hybrid fallback when docs exist
        if intent in _SQL_TRUST or needs_sql:
            allow_hybrid = bool(has_catalog)
            reason += "|sql_hybrid_ok"
        if intent in {Intent.UNKNOWN, Intent.FAQ} and has_catalog and knowledge_q:
            needs_vector = True
            needs_llm = True
            clarification_needed = False
            prefer_vector = True
            reason += "|mid_catalog_vector"
        elif intent == Intent.UNKNOWN and has_catalog and not service_hit:
            # Mid unknown without knowledge speech-act: don't auto-RAG greetings/noise
            prefer_clarify = False
            reason += "|mid_unknown_hold"
        if service_hit and not knowledge_q:
            needs_sql = True
            intent = intent if intent in _SQL_TRUST else Intent.SERVICES_OFFERED
            clarification_needed = False

    elif band == ConfidenceBand.LOW:
        if has_catalog and (knowledge_q or intent == Intent.FAQ or intent == Intent.MEDICAL_QUESTION):
            needs_vector = True
            needs_llm = True
            clarification_needed = False
            prefer_vector = True
            reason += "|low_prefer_vector"
        elif intent in _SQL_TRUST and (needs_sql or service_hit):
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
            prefer_clarify = not has_catalog and intent == Intent.UNKNOWN
            if prefer_clarify:
                clarification_needed = True
                reason += "|low_clarify"
            else:
                reason += "|low_hold"

    else:  # VERY_LOW
        if has_catalog and knowledge_q:
            needs_vector = True
            needs_llm = True
            clarification_needed = False
            prefer_vector = True
            intent = Intent.FAQ if intent == Intent.UNKNOWN else intent
            reason += "|vl_catalog_vector"
        elif intent in _SQL_TRUST and needs_sql and float(nlu.confidence or 0) >= 0.35:
            # Weak but structured signal from rules — keep SQL
            allow_hybrid = False
            clarification_needed = False
            reason += "|vl_weak_sql"
        else:
            clarification_needed = True
            prefer_clarify = True
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
        provider=nlu.provider,
        model=nlu.model,
        timings=nlu.timings,
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
