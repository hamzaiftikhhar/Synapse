"""Execution lanes for the tiered chat orchestrator."""

from __future__ import annotations

from enum import Enum
from typing import Any

from apps.chatbot.nlu.schemas import Intent, NLUResult, Route


class Lane(str, Enum):
    DIRECT = "direct"
    SQL_FAST = "sql_fast"
    BOOKING = "booking"
    VECTOR_RAG = "vector_rag"
    CLARIFY = "clarify"


_SQL_INTENTS = frozenset(
    {
        Intent.CLINIC_HOURS,
        Intent.CLINIC_LOCATION,
        Intent.INSURANCE_ACCEPTED,
        Intent.INSURANCE_VERIFICATION,
        Intent.DOCTOR_SEARCH,
        Intent.DOCTOR_AVAILABILITY,
        Intent.SERVICES_OFFERED,
        Intent.PRICING,
        Intent.CANCEL_APPOINTMENT,
    }
)

_DIRECT_INTENTS = frozenset(
    {
        Intent.GREETING,
        Intent.FAREWELL,
        Intent.OFF_TOPIC,
        Intent.EMERGENCY,
    }
)


def resolve_lane(
    *,
    nlu: NLUResult,
    route: Route,
    is_booking_intent: bool,
    soft_medical: bool,
    needs_vector: bool,
    doc_match: bool,
) -> Lane:
    """Pick the execution lane. Large LLM is only used for VECTOR_RAG."""
    if nlu.is_emergency or nlu.intent == Intent.EMERGENCY or route == Route.EMERGENCY:
        return Lane.DIRECT

    if is_booking_intent:
        return Lane.BOOKING

    # Document / FAQ / medical-with-docs → RAG
    if needs_vector or doc_match or nlu.intent == Intent.FAQ:
        return Lane.VECTOR_RAG

    if soft_medical:
        # Soft specialty recommend without Large LLM when no doc match
        return Lane.SQL_FAST if nlu.needs_sql else Lane.DIRECT

    if route == Route.CLARIFY or nlu.clarification_needed or nlu.intent == Intent.UNKNOWN:
        # Prefer SQL if heuristics/flags already set
        if nlu.needs_sql and nlu.intent in _SQL_INTENTS:
            return Lane.SQL_FAST
        return Lane.CLARIFY

    if nlu.intent in _DIRECT_INTENTS or (
        route == Route.DIRECT_RESPONSE and not nlu.needs_sql and not needs_vector
    ):
        return Lane.DIRECT

    if nlu.needs_sql or nlu.intent in _SQL_INTENTS:
        return Lane.SQL_FAST

    if nlu.needs_llm and not needs_vector:
        # Contract: never Large LLM without vector — treat as SQL or clarify
        if nlu.needs_sql:
            return Lane.SQL_FAST
        return Lane.CLARIFY

    return Lane.CLARIFY
