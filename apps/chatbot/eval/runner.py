"""Evaluate routing decisions (rules → heuristics → confidence → lane)."""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any

from apps.chatbot.eval.cases import EvalCase
from apps.chatbot.nlu.decision import DecisionEngine
from apps.chatbot.nlu.rules import try_rule_classify
from apps.chatbot.nlu.schemas import Intent, parse_nlu_payload
from apps.chatbot.routing.confidence import apply_confidence_policy
from apps.chatbot.routing.heuristics import apply_routing_heuristics
from apps.chatbot.routing.lanes import Lane, resolve_lane
from apps.chatbot.routing.signals import (
    is_transactional_booking,
    looks_like_knowledge_question,
    match_services_in_message,
)


@dataclass
class CaseResult:
    case_id: str
    message: str
    expected_lane: str
    predicted_lane: str
    expected_family: str
    predicted_intent: str
    confidence: float
    confidence_band: str
    passed: bool
    ms: float
    source: str
    needs_sql: bool
    needs_vector: bool
    tags: tuple[str, ...] = ()
    reason: str = ""


@dataclass
class EvalReport:
    total: int
    passed: int
    failed: int
    pass_rate: float
    by_family: dict[str, dict[str, int]] = field(default_factory=dict)
    by_lane_confusion: dict[str, int] = field(default_factory=dict)
    failures: list[CaseResult] = field(default_factory=list)
    results: list[CaseResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "pass_rate": self.pass_rate,
            "by_family": self.by_family,
            "by_lane_confusion": self.by_lane_confusion,
            "failures": [asdict(f) for f in self.failures[:50]],
        }


def evaluate_routing_case(case: EvalCase) -> CaseResult:
    started = time.perf_counter()
    services = list(case.services)
    documents = list(case.documents)

    source = "rules"
    raw = None if case.force_unknown else try_rule_classify(case.message, tier="strong")
    if raw is None:
        raw = try_rule_classify(case.message, tier="fallback")
    if raw is None or case.force_unknown:
        source = "unknown_seed"
        conf = case.confidence_override if case.confidence_override is not None else 0.5
        raw = {
            "intent": "unknown",
            "confidence": conf,
            "needs_sql": False,
            "needs_vector": False,
            "needs_llm": False,
            "clarification_needed": True,
            "clarification_question": "Could you clarify?",
            "entities": {},
        }
    elif case.confidence_override is not None:
        raw["confidence"] = case.confidence_override

    nlu = parse_nlu_payload(raw)
    nlu = apply_routing_heuristics(
        message=case.message,
        nlu=nlu,
        document_catalog=documents,
        service_catalog=services,
    )
    service_hit = bool(match_services_in_message(case.message, services))
    knowledge_q = looks_like_knowledge_question(case.message)
    policy = apply_confidence_policy(
        nlu,
        has_catalog=bool(documents),
        service_hit=service_hit,
        knowledge_q=knowledge_q,
    )
    nlu = policy.nlu
    decision = DecisionEngine.decide(nlu)

    booking_commit = case.message.lower().strip() in {
        "start booking",
        "book appointment",
        "book an appointment",
        "i would like to book an appointment",
    }
    is_booking = (
        nlu.intent in {Intent.BOOK_APPOINTMENT, Intent.RESCHEDULE_APPOINTMENT}
        and (is_transactional_booking(case.message) or booking_commit)
        and not knowledge_q
    )
    soft_medical = (
        (
            nlu.intent == Intent.MEDICAL_QUESTION
            or bool(getattr(nlu.entities, "symptom", None))
        )
        and not is_booking
        and not knowledge_q
    )
    matched_docs = [
        d["id"]
        for d in documents
        if any(
            isinstance(kw, str) and kw.lower() in case.message.lower()
            for kw in (d.get("routing_keywords") or [])
        )
    ]
    has_catalog = bool(documents)
    needs_vector = bool(nlu.needs_vector) or (
        (soft_medical or knowledge_q) and (bool(matched_docs) or has_catalog)
    )
    doc_match = bool(matched_docs) or (
        has_catalog
        and (
            needs_vector
            or knowledge_q
            or nlu.intent in {Intent.FAQ, Intent.MEDICAL_QUESTION, Intent.UNKNOWN}
        )
    )
    lane = resolve_lane(
        nlu=nlu,
        route=decision.route,
        is_booking_intent=is_booking,
        soft_medical=soft_medical,
        needs_vector=needs_vector,
        doc_match=doc_match,
        has_catalog=has_catalog,
        prefer_vector=policy.prefer_vector,
        prefer_clarify=policy.prefer_clarify,
    )

    acceptable = case.acceptable_lanes or frozenset({case.expected_lane})
    # Map family soft checks: duration must never be confused only — lane set is enough
    passed = lane.value in acceptable
    # Extra guard: duration family must not claim clinic_hours intent
    if case.expected_family == "duration" and nlu.intent == Intent.CLINIC_HOURS:
        passed = False

    ms = (time.perf_counter() - started) * 1000
    return CaseResult(
        case_id=case.case_id,
        message=case.message,
        expected_lane=case.expected_lane,
        predicted_lane=lane.value,
        expected_family=case.expected_family,
        predicted_intent=nlu.intent.value,
        confidence=float(nlu.confidence or 0),
        confidence_band=policy.band.value,
        passed=passed,
        ms=ms,
        source=source,
        needs_sql=bool(nlu.needs_sql),
        needs_vector=lane == Lane.VECTOR_RAG,
        tags=case.tags,
        reason=policy.reasoning,
    )


def evaluate_cases(cases: list[EvalCase]) -> EvalReport:
    results = [evaluate_routing_case(c) for c in cases]
    passed = sum(1 for r in results if r.passed)
    failed_list = [r for r in results if not r.passed]
    by_family: dict[str, dict[str, int]] = {}
    confusion: Counter[str] = Counter()
    for r in results:
        bucket = by_family.setdefault(r.expected_family, {"pass": 0, "fail": 0})
        bucket["pass" if r.passed else "fail"] += 1
        if not r.passed:
            confusion[f"{r.expected_lane}->{r.predicted_lane}"] += 1
    total = len(results)
    return EvalReport(
        total=total,
        passed=passed,
        failed=total - passed,
        pass_rate=(passed / total) if total else 0.0,
        by_family=by_family,
        by_lane_confusion=dict(confusion.most_common(20)),
        failures=failed_list,
        results=results,
    )
