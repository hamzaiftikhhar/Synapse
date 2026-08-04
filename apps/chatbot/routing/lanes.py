"""Execution lanes for the tiered chat orchestrator."""

from __future__ import annotations

from enum import Enum

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

# Intents eligible for SQL → vector hybrid when SQL is empty/thin
HYBRID_SQL_INTENTS = frozenset(
    {
        Intent.SERVICES_OFFERED,
        Intent.PRICING,
        Intent.INSURANCE_ACCEPTED,
        Intent.INSURANCE_VERIFICATION,
        Intent.FAQ,
        Intent.MEDICAL_QUESTION,
        Intent.UNKNOWN,
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
    has_catalog: bool = False,
    prefer_vector: bool = False,
    prefer_clarify: bool = False,
) -> Lane:
    """Pick the execution lane. Large LLM is only used for VECTOR_RAG."""
    if nlu.is_emergency or nlu.intent == Intent.EMERGENCY or route == Route.EMERGENCY:
        return Lane.DIRECT

    if is_booking_intent:
        return Lane.BOOKING

    if prefer_clarify and not has_catalog and not needs_vector and not nlu.needs_sql:
        return Lane.CLARIFY

    # Confidence / recovery: prefer vector when policy says so and docs exist
    if prefer_vector and has_catalog and not is_booking_intent:
        if nlu.needs_sql and nlu.intent in _SQL_INTENTS and not doc_match and not needs_vector:
            return Lane.SQL_FAST
        return Lane.VECTOR_RAG

    # FAQ / policy / PDF-matched / medical-with-docs → RAG (before SQL steal)
    if needs_vector or nlu.intent == Intent.FAQ or (doc_match and soft_medical):
        # Hybrid: SQL + vector when both flagged (engine runs SQL then RAG)
        if nlu.needs_sql and nlu.intent in _SQL_INTENTS and not doc_match:
            # Prefer SQL first for pure structured facts; engine may escalate
            return Lane.SQL_FAST
        return Lane.VECTOR_RAG

    # Structured clinic facts prefer SQL — never Large LLM alone
    if nlu.intent in _SQL_INTENTS and not needs_vector:
        return Lane.SQL_FAST

    if soft_medical:
        # Soft specialty recommend without Large LLM when no doc match
        return Lane.SQL_FAST if nlu.needs_sql else Lane.DIRECT

    if nlu.intent in _DIRECT_INTENTS or (
        route == Route.DIRECT_RESPONSE and not nlu.needs_sql and not needs_vector
    ):
        return Lane.DIRECT

    if route == Route.CLARIFY or nlu.clarification_needed or nlu.intent == Intent.UNKNOWN:
        if nlu.needs_sql:
            return Lane.SQL_FAST
        # Recover to RAG only when docs *match* or policy prefers vector — not merely because
        # the clinic owns PDFs (that stole greetings/farewells into vector_rag).
        if needs_vector or prefer_vector or doc_match:
            return Lane.VECTOR_RAG
        if prefer_clarify or not has_catalog:
            return Lane.CLARIFY
        return Lane.CLARIFY

    if nlu.needs_sql:
        return Lane.SQL_FAST

    if doc_match or (has_catalog and needs_vector):
        return Lane.VECTOR_RAG

    # Contract: never Large LLM without vector
    if nlu.needs_llm and not needs_vector:
        if nlu.needs_sql:
            return Lane.SQL_FAST
        if has_catalog:
            return Lane.VECTOR_RAG
        return Lane.CLARIFY

    if has_catalog and nlu.intent in {Intent.UNKNOWN, Intent.FAQ, Intent.MEDICAL_QUESTION}:
        if needs_vector or prefer_vector or doc_match or nlu.intent != Intent.UNKNOWN:
            return Lane.VECTOR_RAG

    return Lane.CLARIFY
