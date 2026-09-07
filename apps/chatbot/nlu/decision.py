"""Deterministic Decision Engine — maps NLU flags to routing routes."""

from __future__ import annotations

from apps.chatbot.nlu.schemas import Intent, NLUResult, Route, RouteDecision

EMERGENCY_SAFETY_MESSAGE = (
    "If you are experiencing a medical emergency, call emergency services "
    "(911 in the US) or go to the nearest emergency room immediately. "
    "This chatbot cannot provide emergency medical care."
)


def emergency_safety_message(message: str = "", symptom_hint: str = "") -> str:
    """The right safety message for an already-confirmed emergency —
    mental-health-specific (988 Suicide & Crisis Lifeline) if either the
    raw message or the NLU's own symptom entity names self-harm/suicide,
    otherwise the generic physical-emergency one (911).

    Single call site for this decision — both engine.py's live path and
    DecisionEngine.decide() (the offline eval battery) call this instead
    of independently re-deriving it, which is exactly how this stayed
    unreachable dead code before: response_templates.py had its own
    EMERGENCY_MENTAL_HEALTH-selection copy that engine.py's fast path
    never actually called.
    """
    from apps.chatbot.nlu.emergency_patterns import is_self_harm_mention
    from apps.chatbot.response_templates import get_response

    if is_self_harm_mention(message) or is_self_harm_mention(symptom_hint):
        return get_response("EMERGENCY_MENTAL_HEALTH")
    return EMERGENCY_SAFETY_MESSAGE


class DecisionEngine:
    """Local Python routing — no LLM calls."""

    @classmethod
    def decide(cls, nlu: NLUResult, message: str = "") -> RouteDecision:
        if nlu.is_emergency or nlu.intent == Intent.EMERGENCY:
            # `message` is the raw text when the caller has it (matches
            # engine.py's live check); entities.symptom is the fallback
            # for callers that only have the parsed NLU result.
            symptom_value = nlu.entities.symptom
            if isinstance(symptom_value, list):
                symptom_text = " ".join(s for s in symptom_value if isinstance(s, str))
            else:
                symptom_text = str(symptom_value or "")
            safety_message = emergency_safety_message(message, symptom_text)
            return RouteDecision(
                route=Route.EMERGENCY,
                needs_sql=False,
                needs_vector=False,
                needs_llm=False,
                nlu=nlu,
                safety_message=safety_message,
            )

        if nlu.clarification_needed and not (
            nlu.needs_vector or nlu.needs_sql or nlu.intent == Intent.FAQ
        ):
            return RouteDecision(
                route=Route.CLARIFY,
                needs_sql=False,
                needs_vector=False,
                needs_llm=False,
                nlu=nlu,
            )

        needs_sql = bool(nlu.needs_sql)
        needs_vector = bool(nlu.needs_vector)
        needs_llm = bool(nlu.needs_llm)

        # Contract: Large LLM only with vector — drop contradictory needs_llm
        if needs_llm and not needs_vector:
            needs_llm = False

        # High-confidence direct paths
        if nlu.can_respond_directly and not (needs_sql or needs_vector or needs_llm):
            return RouteDecision(
                route=Route.DIRECT_RESPONSE,
                needs_sql=False,
                needs_vector=False,
                needs_llm=False,
                nlu=nlu,
            )

        if nlu.intent in {Intent.GREETING, Intent.FAREWELL, Intent.OFF_TOPIC}:
            if nlu.confidence >= 0.7 and not (needs_sql or needs_vector):
                return RouteDecision(
                    route=Route.DIRECT_RESPONSE,
                    needs_sql=False,
                    needs_vector=False,
                    needs_llm=False,
                    nlu=nlu,
                )

        route = cls._route_from_flags(needs_sql, needs_vector, needs_llm)
        return RouteDecision(
            route=route,
            needs_sql=needs_sql,
            needs_vector=needs_vector,
            needs_llm=needs_llm,
            nlu=nlu,
        )

    @staticmethod
    def _route_from_flags(
        needs_sql: bool,
        needs_vector: bool,
        needs_llm: bool,
    ) -> Route:
        key = (needs_sql, needs_vector, needs_llm)
        mapping = {
            (False, False, False): Route.DIRECT_RESPONSE,
            (True, False, False): Route.SQL_ONLY,
            (False, True, False): Route.VECTOR_ONLY,
            (True, True, False): Route.SQL_VECTOR,
            (False, False, True): Route.LLM_ONLY,
            (True, False, True): Route.SQL_LLM,
            (False, True, True): Route.VECTOR_LLM,
            (True, True, True): Route.SQL_VECTOR_LLM,
        }
        return mapping[key]
