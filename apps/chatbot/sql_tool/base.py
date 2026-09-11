"""SQL tool types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from apps.chatbot.nlu.schemas import NLUResult


@dataclass
class SQLContext:
    """Inputs for a SQL handler — always clinic-scoped."""

    clinic: Any
    nlu: NLUResult
    patient: Any | None = None
    message: str = ""
    # Service IDs the planner already authorized for this turn (see
    # planner.ExecutionPlan.resolved_service_ids). A handler that needs to
    # filter by service should read this first — it means "which IDs did
    # the planner authorize me to query," not "let me guess from scratch."
    resolved_service_ids: list[str] = field(default_factory=list)
    # Specialty IDs the planner already authorized for this turn (see
    # planner.ExecutionPlan.resolved_specialty_ids) -- same authority
    # rule as resolved_service_ids above, mirrored for specialty-level
    # resolution (Clinic Capability Resolver live vertical slice).
    resolved_specialty_ids: list[str] = field(default_factory=list)
    # True only when resolved_service_ids/resolved_specialty_ids above were
    # populated by the live, validated Clinic Capability Resolver (a real
    # LLM call against this clinic's actual catalog, every id re-checked
    # against the DB -- see planner.apply_capability_resolution and
    # planner.ExecutionPlan.capability_resolver_used), as opposed to the
    # older, cruder message-token matchers (routing/signals.py's
    # match_services_in_message, booking/discovery.py's symptom/category
    # chain) that can also populate those same two lists. A handler with
    # its own conservative "don't guess" branch for an ambiguous/browse-
    # shaped question (see services.py's mode == "none") should still
    # trust a resolved id set backed by this flag -- it is not a guess,
    # it is what the planner already decided for this exact message.
    capability_resolver_used: bool = False
    # Service IDs the Clinic Capability Resolver found relevant to a
    # "concern" but that must never narrow a query on their own (see
    # planner.ExecutionPlan.informational_service_candidates) -- a handler
    # may mention these, once resolved back to real names, alongside
    # whatever it already found; it must never filter or dispatch by them.
    informational_service_candidates: list[str] = field(default_factory=list)
    # Entity fields (e.g. "doctor_id") each SQL task name is told to ignore
    # this turn — computed once, centrally, by the planner (see
    # planner.ExecutionPlan.blocked_entity_fields) whenever a compound
    # message has an entity that plausibly belongs to a *different*
    # intent/task than this one. A handler consults its own task-name
    # key(s) here instead of independently deciding whether a "bonus"
    # entity filter is safe to apply — see sql_tool/handlers/{insurance,
    # services,doctors}.py for the exact guard shape.
    blocked_entity_fields: dict[str, frozenset[str]] = field(default_factory=dict)


@dataclass
class SQLResult:
    """Structured output from one SQL handler."""

    handler: str
    found: bool = False
    rows: list[dict[str, Any]] = field(default_factory=list)
    summary: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "handler": self.handler,
            "found": self.found,
            "rows": self.rows,
            "summary": self.summary,
            "meta": self.meta,
        }


class SQLHandler(Protocol):
    """Callable handler registered on an intent."""

    def __call__(self, ctx: SQLContext) -> SQLResult: ...
