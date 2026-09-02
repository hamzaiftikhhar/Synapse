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
