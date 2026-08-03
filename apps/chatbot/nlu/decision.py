"""Deterministic Decision Engine — maps NLU flags to routing routes."""

from __future__ import annotations

from apps.chatbot.nlu.schemas import Intent, NLUResult, Route, RouteDecision

EMERGENCY_SAFETY_MESSAGE = (
    "If you are experiencing a medical emergency, call emergency services "
    "(911 in the US) or go to the nearest emergency room immediately. "
    "This chatbot cannot provide emergency medical care."
)


class DecisionEngine:
    """Local Python routing — no LLM calls."""

    @classmethod
    def decide(cls, nlu: NLUResult) -> RouteDecision:
        if nlu.is_emergency or nlu.intent == Intent.EMERGENCY:
            return RouteDecision(
                route=Route.EMERGENCY,
                needs_sql=False,
                needs_vector=False,
                needs_llm=False,
                nlu=nlu,
                safety_message=EMERGENCY_SAFETY_MESSAGE,
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
