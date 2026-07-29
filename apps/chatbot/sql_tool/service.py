"""Dispatch NLU intents to SQL handlers."""

from __future__ import annotations

import logging
from collections.abc import Callable

from apps.chatbot.nlu.schemas import Intent, NLUResult
from apps.chatbot.sql_tool.base import SQLContext, SQLHandler, SQLResult
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
    Intent.BOOK_APPOINTMENT: doctor_availability,
    Intent.CANCEL_APPOINTMENT: patient_appointments,
    Intent.RESCHEDULE_APPOINTMENT: patient_appointments,
    Intent.INSURANCE_ACCEPTED: insurance_accepted,
    Intent.INSURANCE_VERIFICATION: insurance_accepted,
    Intent.CLINIC_HOURS: clinic_hours,
    Intent.CLINIC_LOCATION: clinic_location,
    Intent.SERVICES_OFFERED: services_offered,
    Intent.PRICING: services_offered,
}

# Extra handlers for multi-intent / enrichment
_INTENT_SUPPLEMENTS: dict[Intent, list[SQLHandler]] = {
    Intent.DOCTOR_SEARCH: [list_specialties],
    Intent.BOOK_APPOINTMENT: [search_doctors],
    Intent.INSURANCE_VERIFICATION: [search_doctors],
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
    ) -> list[SQLResult]:
        ctx = SQLContext(clinic=clinic, nlu=nlu, patient=patient)
        handlers = cls._handlers_for(nlu)
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
    def _handlers_for(cls, nlu: NLUResult) -> list[SQLHandler]:
        intents = [nlu.intent, *nlu.secondary_intents]
        handlers: list[SQLHandler] = []
        seen: set[str] = set()

        def add(handler: SQLHandler) -> None:
            name = handler.__name__
            if name not in seen:
                seen.add(name)
                handlers.append(handler)

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
