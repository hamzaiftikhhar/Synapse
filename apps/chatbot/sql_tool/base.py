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
