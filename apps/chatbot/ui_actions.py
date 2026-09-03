"""Deterministic UI-action handlers.

For interactions where the frontend already knows the user's intent (a
specialty/doctor/service card click — not typed free text), there is
nothing to classify. This module runs straight to the same SQL handler,
formatter, and ui_meta card-mapping the normal chat pipeline uses once NLU
has resolved an intent — the only thing skipped is NLU/LLM classification
itself, because the frontend already supplied the resolved id.

Keep this module narrow: one function per genuinely deterministic UI
action, each a thin wrapper around existing handlers. It is not a second
routing framework — planner.py/engine.py remain the only place that decides
between conversational and deterministic handling for typed messages.
"""

from __future__ import annotations

from typing import Any


def search_doctors_for_specialty(clinic: Any, specialty_id: str) -> dict[str, Any]:
    """Doctors for an explicitly-selected specialty card — no NLU, no LLM.

    Returns the same {response, meta} shape the chat pipeline's own
    search_doctors turn would produce (reusing the identical SQL handler,
    formatter, and ui_meta card-mapping), so a card click and an
    equivalent typed query render identically. On no match, returns an
    honest NO_DIRECT_MATCH state — never a substitute specialty picked
    just because it happened to be first in the clinic's list.
    """
    from apps.chatbot.nlu.schemas import ExtractedEntities, Intent, NLUResult, ResolvedIds
    from apps.chatbot.sql_tool.base import SQLContext
    from apps.chatbot.sql_tool.formatter import format_sql_results
    from apps.chatbot.sql_tool.handlers.doctors import search_doctors
    from apps.chatbot.ui_meta import build_ui_meta
    from apps.specialties.models import Specialty

    try:
        specialty = Specialty.objects.get(
            id=specialty_id, clinic=clinic, is_deleted=False, is_active=True
        )
    except (Specialty.DoesNotExist, ValueError, TypeError):
        return {
            "state": "NOT_SUPPORTED",
            "response": "That specialty isn't listed for this clinic.",
            "meta": {},
        }

    nlu = NLUResult(
        intent=Intent.DOCTOR_SEARCH,
        confidence=1.0,
        entities=ExtractedEntities(specialty=specialty.name),
        resolved_ids=ResolvedIds(specialty_id=str(specialty.id)),
    )
    result = search_doctors(SQLContext(clinic=clinic, nlu=nlu))

    if not result.found:
        return {
            "state": "NO_DIRECT_MATCH",
            "response": (
                f"We don't currently have a doctor listed specifically for "
                f"{specialty.name}. You can browse all our doctors, or ask "
                "about a different specialty."
            ),
            # Deliberately no fabricated alternatives here — only a
            # configured, factual relationship would justify suggesting a
            # different specialty, and none exists for this path.
            "meta": {"actions": []},
        }

    result_dict = result.to_dict()
    meta = build_ui_meta(
        clinic=clinic,
        intent=Intent.DOCTOR_SEARCH.value,
        route="ui_action",
        sql_results=[result_dict],
        nlu=nlu,
    )
    return {
        "state": "FOUND_MATCHES",
        "response": format_sql_results([result_dict]),
        "meta": meta,
    }


def browse_doctors(clinic: Any) -> dict[str, Any]:
    """The clinic's full doctor roster — no NLU, no LLM.

    Backs the "Find a Doctor" main-menu button: that button's label is
    frontend-authored, not user language, so there's nothing to classify —
    this runs the identical search_doctors handler a typed "what doctors
    do you have" would reach, unfiltered.
    """
    from apps.chatbot.nlu.schemas import Intent, NLUResult
    from apps.chatbot.sql_tool.base import SQLContext
    from apps.chatbot.sql_tool.formatter import format_sql_results
    from apps.chatbot.sql_tool.handlers.doctors import search_doctors
    from apps.chatbot.ui_meta import build_ui_meta

    nlu = NLUResult(intent=Intent.DOCTOR_SEARCH, confidence=1.0)
    result = search_doctors(SQLContext(clinic=clinic, nlu=nlu))
    result_dict = result.to_dict()
    meta = build_ui_meta(
        clinic=clinic,
        intent=Intent.DOCTOR_SEARCH.value,
        route="ui_action",
        sql_results=[result_dict],
        nlu=nlu,
    )
    return {
        "state": "FOUND_MATCHES" if result.found else "NO_DIRECT_MATCH",
        "response": format_sql_results([result_dict]),
        "meta": meta,
    }


def clinic_hours_info(clinic: Any) -> dict[str, Any]:
    """The clinic's business hours — no NLU, no LLM.

    Backs the "Clinic Hours" main-menu button. clinic_hours is prose-only
    (no card meta today — see ui_meta.py), so this just reuses the SQL
    handler + formatter for identical wording to the typed-question path.
    """
    from apps.chatbot.nlu.schemas import Intent, NLUResult
    from apps.chatbot.sql_tool.base import SQLContext
    from apps.chatbot.sql_tool.formatter import format_sql_results
    from apps.chatbot.sql_tool.handlers.clinic import clinic_hours

    nlu = NLUResult(intent=Intent.CLINIC_HOURS, confidence=1.0)
    result = clinic_hours(SQLContext(clinic=clinic, nlu=nlu))
    return {
        "state": "FOUND_MATCHES" if result.found else "NO_DIRECT_MATCH",
        "response": format_sql_results([result.to_dict()]),
        "meta": {},
    }
