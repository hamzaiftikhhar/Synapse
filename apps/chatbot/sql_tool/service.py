"""Dispatch NLU intents to SQL handlers."""

from __future__ import annotations

import logging
from collections.abc import Callable

from apps.chatbot.nlu.schemas import Intent, NLUResult
from apps.chatbot.sql_tool.base import SQLContext, SQLHandler, SQLResult
from apps.chatbot.routing.signals import is_specialty_list_query
from apps.chatbot.sql_tool.handlers import (
    clinic_hours,
    clinic_location,
    doctor_availability,
    insurance_accepted,
    list_specialties,
    patient_appointments,
    search_doctors,
    services_offered,
)

logger = logging.getLogger(__name__)

# Primary handler per intent
_INTENT_HANDLERS: dict[Intent, SQLHandler] = {
    Intent.DOCTOR_SEARCH: search_doctors,
    Intent.DOCTOR_AVAILABILITY: doctor_availability,
    # BOOK_APPOINTMENT is handled by the booking wizard — no SQL dump
    Intent.CANCEL_APPOINTMENT: patient_appointments,
    Intent.RESCHEDULE_APPOINTMENT: patient_appointments,
    Intent.INSURANCE_ACCEPTED: insurance_accepted,
    Intent.INSURANCE_VERIFICATION: insurance_accepted,
    Intent.CLINIC_HOURS: clinic_hours,
    Intent.CLINIC_LOCATION: clinic_location,
    Intent.SERVICES_OFFERED: services_offered,
    Intent.PRICING: services_offered,
}

# sql_tool string from Small LLM → handler override
_SQL_TOOL_HANDLERS: dict[str, SQLHandler] = {
    "hours": clinic_hours,
    "location": clinic_location,
    "insurance": insurance_accepted,
    "doctors": search_doctors,
    "availability": doctor_availability,
    "specialties": list_specialties,
    "services": services_offered,
    "pricing": services_offered,
    "appointments": patient_appointments,
}

# Extra handlers for multi-intent / enrichment — avoid dumping specialties on every doctor search
_INTENT_SUPPLEMENTS: dict[Intent, list[SQLHandler]] = {
    Intent.INSURANCE_VERIFICATION: [],
}


class SQLTool:
    """
    Run read-only clinic DB queries from an NLUResult.

    Usage:
        results = SQLTool.run(clinic, nlu, patient=patient)
    """

    @classmethod
    def run(
        cls,
        clinic: object,
        nlu: NLUResult,
        *,
        patient: object | None = None,
        message: str = "",
    ) -> list[SQLResult]:
        """Compatibility entry: derive handlers from NLU (legacy). Prefer run_tasks."""
        ctx = SQLContext(clinic=clinic, nlu=nlu, patient=patient, message=message or "")
        handlers = cls._handlers_for(nlu, message=message or "")
        return cls._execute_handlers(handlers, ctx, nlu=nlu)

    @classmethod
    def run_tasks(
        cls,
        clinic: object,
        nlu: NLUResult,
        tasks: list[str],
        *,
        patient: object | None = None,
        message: str = "",
    ) -> list[SQLResult]:
        """Execute SQL tools named by the ExecutionPlan (planner source of truth)."""
        from apps.chatbot.sql_tool.cache import get_cached_result, set_cached_result

        ctx = SQLContext(clinic=clinic, nlu=nlu, patient=patient, message=message or "")
        clinic_id = getattr(clinic, "id", None)
        results: list[SQLResult] = []
        pending_handlers: list[tuple[str, SQLHandler]] = []
        seen: set[str] = set()

        for task in tasks or []:
            key = str(task or "").strip().lower()
            handler = _SQL_TOOL_HANDLERS.get(key)
            if handler is None:
                continue
            name = handler.__name__
            if name in seen:
                continue
            seen.add(name)
            cached = get_cached_result(clinic_id, key) if clinic_id is not None else None
            if cached is not None:
                # Reconstruct SQLResult-like dicts already stored as to_dict()
                for row in cached:
                    results.append(
                        SQLResult(
                            handler=row.get("handler", name),
                            found=bool(row.get("found")),
                            rows=list(row.get("rows") or []),
                            summary=str(row.get("summary") or ""),
                            meta=dict(row.get("meta") or {}),
                        )
                    )
                continue
            pending_handlers.append((key, handler))

        if pending_handlers:
            fresh = cls._execute_handlers(
                [h for _, h in pending_handlers], ctx, nlu=nlu
            )
            # Cache each task's result block
            by_handler = {r.handler: r for r in fresh}
            for key, handler in pending_handlers:
                name = handler.__name__
                block = by_handler.get(name)
                if block is not None and clinic_id is not None:
                    set_cached_result(clinic_id, key, [block.to_dict()])
            results.extend(fresh)

        if not results:
            return cls._execute_handlers([], ctx, nlu=nlu)
        return results

    @classmethod
    def _execute_handlers(
        cls,
        handlers: list[SQLHandler],
        ctx: SQLContext,
        *,
        nlu: NLUResult,
    ) -> list[SQLResult]:
        if not handlers:
            return [
                SQLResult(
                    handler="none",
                    found=False,
                    summary="No SQL handler for this intent.",
                    meta={"intent": nlu.intent.value},
                )
            ]

        results: list[SQLResult] = []
        seen: set[str] = set()
        for handler in handlers:
            name = getattr(handler, "__name__", str(handler))
            if name in seen:
                continue
            seen.add(name)
            try:
                results.append(handler(ctx))
            except Exception:
                logger.exception("SQL handler %s failed", name)
                results.append(
                    SQLResult(handler=name, found=False, summary="DB query failed.")
                )
        return results

    @classmethod
    def run_handler(cls, handler_name: str, ctx: SQLContext) -> SQLResult:
        """Run a single handler by name — useful for debug endpoints."""
        handler = _HANDLER_BY_NAME.get(handler_name)
        if handler is None:
            return SQLResult(
                handler=handler_name,
                found=False,
                summary=f"Unknown SQL handler: {handler_name}",
            )
        return handler(ctx)

    @classmethod
    def _handlers_for(cls, nlu: NLUResult, message: str = "") -> list[SQLHandler]:
        intents = [nlu.intent, *nlu.secondary_intents]
        handlers: list[SQLHandler] = []
        seen: set[str] = set()

        def add(handler: SQLHandler) -> None:
            name = handler.__name__
            if name not in seen:
                seen.add(name)
                handlers.append(handler)

        raw = getattr(nlu, "raw", None) or {}
        tool = getattr(nlu, "sql_tool", None) or raw.get("sql_tool") or raw.get(
            "sql_tool_hint"
        )
        if isinstance(tool, str):
            key = tool.strip().lower()
            if key in _SQL_TOOL_HANDLERS:
                add(_SQL_TOOL_HANDLERS[key])
                return handlers

        if is_specialty_list_query(message):
            add(list_specialties)
            return handlers

        for intent in intents:
            primary = _INTENT_HANDLERS.get(intent)
            if primary:
                add(primary)
            for supplement in _INTENT_SUPPLEMENTS.get(intent, []):
                add(supplement)

        return handlers


_HANDLER_BY_NAME: dict[str, Callable[..., SQLResult]] = {
    "search_doctors": search_doctors,
    "list_specialties": list_specialties,
    "doctor_availability": doctor_availability,
    "patient_appointments": patient_appointments,
    "insurance_accepted": insurance_accepted,
    "clinic_hours": clinic_hours,
    "clinic_location": clinic_location,
    "services_offered": services_offered,
}
