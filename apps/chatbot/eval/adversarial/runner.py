"""Phase 51 adversarial eval runner — executes corpus.py against the real
ChatEngine (live LLM, real DB), not the synthetic offline battery in
apps/chatbot/eval/runner.py.

Deliberately does NOT auto-score hallucination/injection-compliance/safety
via keyword matching — those require reading the actual response text
against ground truth, which this module captures completely (response,
intent, secondary_intents, entities, sql_tasks, blocked_entity_fields,
meta.actions, is_emergency) so a reviewer (human or Claude) can judge each
case precisely, the same methodology used throughout this project's prior
phases. What IS automated: retrying past live provider timeouts (never
past a genuine classification) and formatting output for fast review.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from apps.chatbot.eval.adversarial.corpus import Case, all_cases


@dataclass
class CaseResult:
    case: Case
    turns_run: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.case.id,
            "category": self.case.category,
            "subcategory": self.case.subcategory,
            "severity_if_failed": self.case.severity_if_failed,
            "poison_ground_truth": self.case.poison_ground_truth,
            "turns": self.turns_run,
        }


def _run_one_turn(clinic: Any, message: str, session: Any, *, max_attempts: int = 4) -> dict[str, Any]:
    from apps.chatbot.providers import circuit_breaker

    from apps.chatbot.engine import ChatEngine

    last = None
    for _ in range(max_attempts):
        circuit_breaker.reset()
        result = ChatEngine().process(clinic=clinic, message=message, session=session)
        last = result
        if not result.meta.get("degraded"):
            break
    r = last
    planner = (r.meta or {}).get("planner") or {}
    return {
        "message": message,
        "intent": r.intent,
        "confidence": r.confidence,
        "route": r.route,
        "secondary_intents": planner.get("facts", {}).get("secondary_intents", []),
        "sql_tasks": planner.get("sql_tasks", []),
        "vector_tasks": planner.get("vector_tasks", []),
        "blocked_entity_fields": planner.get("blocked_entity_fields", {}),
        "booking": planner.get("booking", False),
        "is_emergency": bool(planner.get("emergency")),
        "direct_mode": planner.get("direct_mode"),
        "response": r.response,
        "actions": [a.get("id") for a in (r.meta or {}).get("actions", [])],
        "primary_component": (r.meta or {}).get("primary_component"),
        "degraded": bool((r.meta or {}).get("degraded")),
        "sql_found": [
            {"handler": row.get("handler"), "found": row.get("found")}
            for row in (r.sql_results or [])
        ],
    }


def run_case(clinic: Any, case: Case) -> CaseResult:
    import uuid

    from apps.chatbot.models import ChatSession, ChatSessionStatus

    result = CaseResult(case=case)
    if case.turns:
        session = ChatSession.objects.create(
            clinic=clinic,
            session_token=f"adversarial-{case.id}-{uuid.uuid4().hex[:8]}",
            status=ChatSessionStatus.ACTIVE,
        )
        for turn_message in case.turns:
            result.turns_run.append(_run_one_turn(clinic, turn_message, session))
    else:
        result.turns_run.append(_run_one_turn(clinic, case.message, None))
    return result


def run_all(clinic: Any, *, categories: list[str] | None = None) -> list[CaseResult]:
    cases = all_cases()
    if categories:
        cases = [c for c in cases if c.category in categories]
    return [run_case(clinic, c) for c in cases]


def print_compact(results: list[CaseResult]) -> None:
    for r in results:
        print(f"\n=== [{r.case.category}/{r.case.subcategory}] {r.case.id} "
              f"(sev-if-failed={r.case.severity_if_failed}) ===")
        if r.case.poison_ground_truth:
            print(f"  ground truth: {r.case.poison_ground_truth}")
        for i, t in enumerate(r.turns_run):
            prefix = f"  turn{i+1}" if len(r.turns_run) > 1 else " "
            print(f"{prefix} msg: {t['message']!r}")
            print(f"{prefix} intent={t['intent']} conf={t['confidence']:.2f} "
                  f"secondary={t['secondary_intents']} degraded={t['degraded']}")
            print(f"{prefix} sql_tasks={t['sql_tasks']} blocked={t['blocked_entity_fields']} "
                  f"booking={t['booking']} emergency={t['is_emergency']} "
                  f"direct_mode={t['direct_mode']}")
            print(f"{prefix} sql_found={t['sql_found']}")
            print(f"{prefix} actions={t['actions']} primary_component={t['primary_component']}")
            print(f"{prefix} RESPONSE: {t['response']!r}")


def dump_json(results: list[CaseResult], path: str) -> None:
    with open(path, "w") as f:
        json.dump([r.to_dict() for r in results], f, indent=2, default=str)
