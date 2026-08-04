"""Deterministic planner layer: scores execution paths from structured NLU output.

The planner does not understand English. It only converts validated NLU output
plus runtime facts into an execution decision.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from apps.chatbot.nlu.schemas import Intent, NLUResult
from apps.chatbot.routing.lanes import Lane


@dataclass(frozen=True)
class PlannerScores:
    emergency: float = 0.0
    direct: float = 0.0
    booking: float = 0.0
    sql: float = 0.0
    vector: float = 0.0
    clarify: float = 0.0

    def to_dict(self) -> dict[str, float]:
        return {
            "emergency": self.emergency,
            "direct": self.direct,
            "booking": self.booking,
            "sql": self.sql,
            "vector": self.vector,
            "clarify": self.clarify,
        }


@dataclass(frozen=True)
class PlannerDecision:
    lane: Lane
    scores: PlannerScores
    sql_tool: str | None = None
    reason: str = ""
    direct_mode: str | None = None
    degraded: bool = False
    facts: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "lane": self.lane.value,
            "scores": self.scores.to_dict(),
            "sql_tool": self.sql_tool,
            "reason": self.reason,
            "direct_mode": self.direct_mode,
            "degraded": self.degraded,
            "facts": self.facts,
        }


def choose_plan(
    *,
    nlu: NLUResult,
    is_booking_intent: bool,
    soft_medical: bool,
    needs_vector: bool,
    doc_match: bool,
    has_catalog: bool,
    prefer_vector: bool,
    prefer_clarify: bool,
    degraded: bool,
    doctor_ranking_request: bool,
    instruction_injection: bool,
    unknown_doctor_requested: bool,
) -> PlannerDecision:
    """Score lanes from structured facts and select the highest-confidence path."""
    direct_mode: str | None = None

    emergency = 1.0 if (nlu.is_emergency or nlu.intent == Intent.EMERGENCY) else 0.0
    if emergency:
        return PlannerDecision(
            lane=Lane.DIRECT,
            scores=PlannerScores(emergency=1.0),
            reason="planner_emergency_override",
            direct_mode="emergency",
            degraded=degraded,
            facts=_facts(
                nlu=nlu,
                is_booking_intent=is_booking_intent,
                soft_medical=soft_medical,
                needs_vector=needs_vector,
                doc_match=doc_match,
                degraded=degraded,
                doctor_ranking_request=doctor_ranking_request,
                instruction_injection=instruction_injection,
                unknown_doctor_requested=unknown_doctor_requested,
            ),
        )

    direct = 0.0
    if nlu.can_respond_directly or nlu.intent in {
        Intent.GREETING,
        Intent.FAREWELL,
        Intent.OFF_TOPIC,
    }:
        direct = 0.92 + min(0.08, max(0.0, float(nlu.confidence or 0.0) * 0.08))
    if doctor_ranking_request:
        direct = max(direct, 0.98)
        direct_mode = "doctor_ranking_refusal"
    if instruction_injection:
        direct = max(direct, 0.99)
        direct_mode = "prompt_injection_refusal"
    if unknown_doctor_requested:
        direct = max(direct, 0.97)
        direct_mode = "unknown_doctor_refusal"

    booking = 0.0
    if is_booking_intent and not unknown_doctor_requested:
        booking = 0.90 + min(0.08, float(nlu.confidence or 0.0) * 0.08)

    sql = 0.0
    if nlu.needs_sql:
        sql = 0.65 + min(0.25, float(nlu.confidence or 0.0) * 0.25)
        if nlu.sql_tool:
            sql += 0.05
        if degraded and nlu.intent == Intent.UNKNOWN:
            sql = 0.0
        if nlu.intent in {Intent.CLINIC_HOURS, Intent.CLINIC_LOCATION}:
            sql += 0.05

    vector = 0.0
    if needs_vector or nlu.needs_vector or nlu.intent == Intent.FAQ:
        vector = 0.70 + min(0.25, float(nlu.confidence or 0.0) * 0.20)
        if doc_match:
            vector += 0.08
        if nlu.document_needed:
            vector += 0.05
        if prefer_vector:
            vector += 0.04
    elif soft_medical and doc_match:
        vector = 0.72

    clarify = 0.0
    if nlu.clarification_needed or nlu.intent == Intent.UNKNOWN:
        clarify = 0.60 + (0.12 if degraded else 0.0)
        if prefer_clarify:
            clarify += 0.08
    if degraded and not (sql or vector or booking or direct):
        clarify = max(clarify, 0.78)

    scores = PlannerScores(
        emergency=emergency,
        direct=direct,
        booking=booking,
        sql=sql,
        vector=vector,
        clarify=clarify,
    )
    lane = _best_lane(scores)
    reason = f"planner_best:{lane.value}"

    if lane == Lane.SQL_FAST and not nlu.sql_tool and soft_medical and not nlu.needs_sql:
        lane = Lane.DIRECT
        reason = "planner_soft_medical_direct"

    return PlannerDecision(
        lane=lane,
        scores=scores,
        sql_tool=nlu.sql_tool,
        reason=reason,
        direct_mode=direct_mode,
        degraded=degraded,
        facts=_facts(
            nlu=nlu,
            is_booking_intent=is_booking_intent,
            soft_medical=soft_medical,
            needs_vector=needs_vector,
            doc_match=doc_match,
            degraded=degraded,
            doctor_ranking_request=doctor_ranking_request,
            instruction_injection=instruction_injection,
            unknown_doctor_requested=unknown_doctor_requested,
        ),
    )


def _best_lane(scores: PlannerScores) -> Lane:
    ordered = [
        (Lane.DIRECT, scores.direct),
        (Lane.BOOKING, scores.booking),
        (Lane.VECTOR_RAG, scores.vector),
        (Lane.SQL_FAST, scores.sql),
        (Lane.CLARIFY, scores.clarify),
    ]
    best_lane, best_score = Lane.CLARIFY, -1.0
    for lane, score in ordered:
        if score > best_score:
            best_lane, best_score = lane, score
    return best_lane


def _facts(**kwargs: Any) -> dict[str, Any]:
    nlu = kwargs.pop("nlu")
    return {
        "intent": nlu.intent.value,
        "confidence": float(nlu.confidence or 0.0),
        "sql_tool": nlu.sql_tool,
        "service_filter_mode": nlu.service_filter_mode,
        "needs_sql": bool(nlu.needs_sql),
        "needs_vector": bool(nlu.needs_vector),
        "document_needed": bool(nlu.document_needed),
        **kwargs,
    }
