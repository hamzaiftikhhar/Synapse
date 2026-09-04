"""Doctor and availability SQL handlers."""

from __future__ import annotations

from datetime import date, time, timedelta
from typing import Any

from django.utils import timezone

from apps.chatbot.nlu.languages import resolve_language_codes
from apps.chatbot.sql_tool.base import SQLContext, SQLResult
from apps.chatbot.sql_tool.utils import (
    DOCTOR_LIST_CEILING,
    build_name_filter,
    clinic_timezone,
    doctor_to_dict,
    entity_ids,
    entity_list,
    parse_natural_date,
)
from apps.chatbot.temporal import TemporalQuery

# Words that appear in booking/availability talk but are never a doctor's
# name — shared by search_doctors and doctor_availability so a fix to one
# can't drift from the other (Phase 41: "should" from "which doctor
# should I see" was extracted as doctor_name and reproduced live — zero
# doctors ever matched a name filter for "should"; previously only one of
# the two copies would have needed the fix, exactly the drift this shared
# constant prevents).
_NAME_NOISE = {
    "please", "doctor", "doctors", "dentist", "help", "find",
    "me", "a", "the", "good", "best", "free", "available", "open",
    "any", "some", "all", "on", "in", "at", "morning", "afternoon",
    "evening", "slot", "slots",
    "should", "would", "could", "can", "will", "shall", "do", "does", "did",
    "i", "my", "see", "seeing",
}


def _slot_at_or_after(slot: dict, floor_time) -> bool:
    start = slot.get("start") or ""
    if not start or floor_time is None:
        return True
    try:
        from datetime import datetime

        dt = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
        return dt.time() >= floor_time
    except Exception:
        return True


def _slot_before(slot: dict, ceiling_time) -> bool:
    start = slot.get("start") or ""
    if not start or ceiling_time is None:
        return True
    try:
        from datetime import datetime

        dt = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
        return dt.time() < ceiling_time
    except Exception:
        return True


def search_doctors(ctx: SQLContext) -> SQLResult:
    from apps.doctors.models import Doctor

    clinic = ctx.clinic
    nlu = ctx.nlu
    qs = (
        Doctor.objects.filter(clinic=clinic, is_deleted=False, is_active=True)
        .prefetch_related("specialties", "services")
    )

    # A doctor named only to anchor a *different*, competing intent in the
    # same message (e.g. "who are your doctors and can I book with Dr.
    # Vance" — the booking clause, not this browse) must not silently
    # narrow this task — see planner._compute_blocked_entity_fields. A
    # genuine single-clause "tell me about Dr. Vance" still filters
    # normally: this only fires when a doctor-owning intent (booking,
    # availability, reschedule) is also present in the same message.
    doctor_blocked = "doctor_id" in ctx.blocked_entity_fields.get("doctors", frozenset())
    doctor_ids = [] if doctor_blocked else entity_ids(nlu.resolved_ids.doctor_id)
    if doctor_ids:
        qs = qs.filter(id__in=doctor_ids)
    elif not doctor_blocked:
        names = entity_list(nlu.entities.doctor_name)
        # Ignore politeness / filler / availability tokens mistaken for names
        # e.g. "is any dr free on tuesday" → "free" must not filter doctors
        names = [
            n
            for n in names
            if n.lower() not in _NAME_NOISE
            and not all(tok in _NAME_NOISE for tok in n.lower().split())
        ]
        if names:
            qs = qs.filter(build_name_filter("full_name", names))

    # A doctor was explicitly named ("does Dr Lee treat cardiac issues") —
    # keep filtering by that doctor regardless of whether their symptom
    # also maps to a specialty; only a bare, doctor-less symptom mention
    # should trigger the honest "we don't have that" path below.
    doctor_named = bool(doctor_ids) or bool(entity_list(nlu.entities.doctor_name))

    specialty_ids = entity_ids(nlu.resolved_ids.specialty_id)
    if specialty_ids:
        qs = qs.filter(doctor_specialties__specialty_id__in=specialty_ids).distinct()
    else:
        specs = entity_list(nlu.entities.specialty)
        if specs:
            q = build_name_filter("specialties__name", specs)
            qs = qs.filter(q).distinct()
        elif not doctor_named:
            from apps.chatbot.booking.discovery import (
                resolve_symptom_specialty_ids,
                symptom_no_match_result,
            )

            resolution = resolve_symptom_specialty_ids(clinic, nlu, ctx.message)
            if resolution is not None:
                if resolution.matched_ids:
                    qs = qs.filter(
                        doctor_specialties__specialty_id__in=resolution.matched_ids
                    ).distinct()
                else:
                    return symptom_no_match_result("search_doctors", resolution, kind="doctor")

    # Same principle for a service named only to anchor a pricing/services
    # clause elsewhere in the message — live-confirmed without this guard:
    # "who are your doctors and how much is a strep test" silently dropped
    # 3 of 6 real doctors from the browse-all-doctors answer.
    service_blocked = "service_id" in ctx.blocked_entity_fields.get("doctors", frozenset())
    service_id = None if service_blocked else nlu.resolved_ids.service_id
    if service_id:
        qs = qs.filter(services__id=service_id).distinct()
    elif not service_blocked and nlu.entities.service:
        qs = qs.filter(services__name__icontains=nlu.entities.service, services__is_deleted=False).distinct()

    language_values = entity_list(getattr(nlu.entities, "language", None))
    if language_values:
        lang_codes = resolve_language_codes(language_values)
        # A language was named but didn't resolve to any known code — filter
        # to no rows rather than silently ignoring the request and returning
        # every doctor as if the question had never been asked.
        qs = qs.filter(languages__overlap=lang_codes) if lang_codes else qs.none()

    doctors = list(qs[:DOCTOR_LIST_CEILING])
    rows = [doctor_to_dict(d) for d in doctors]
    if rows:
        names = ", ".join(r["full_name"] for r in rows[:3])
        more = f" (+{len(rows) - 3} more)" if len(rows) > 3 else ""
        summary = f"Found {len(rows)} doctor(s): {names}{more}."
    else:
        summary = "No matching doctors found."
    return SQLResult(handler="search_doctors", found=bool(rows), rows=rows, summary=summary)


def list_specialties(ctx: SQLContext) -> SQLResult:
    from django.db.models import Count, Q

    from apps.specialties.models import Specialty

    clinic = ctx.clinic
    nlu = ctx.nlu
    qs = Specialty.objects.filter(clinic=clinic, is_deleted=False, is_active=True)

    specialty_ids = entity_ids(nlu.resolved_ids.specialty_id)
    if specialty_ids:
        qs = qs.filter(id__in=specialty_ids)
    else:
        specs = entity_list(nlu.entities.specialty)
        if specs:
            qs = qs.filter(build_name_filter("name", specs))

    # One annotated query instead of a per-specialty .count() (was up to 20
    # extra COUNT queries per "what specialties do you offer" chat message).
    qs = qs.annotate(
        doctor_count=Count(
            "doctors",
            filter=Q(doctors__is_deleted=False, doctors__is_active=True),
        )
    )
    specialties = list(qs.order_by("name")[:20])
    rows = [
        {
            "id": str(s.id),
            "name": s.name,
            "slug": s.slug,
            "description": (s.description or "")[:300],
            "doctor_count": s.doctor_count,
        }
        for s in specialties
    ]
    if rows:
        names = ", ".join(r["name"] for r in rows[:5])
        summary = f"Specialties: {names}."
    else:
        summary = "No specialties found."
    return SQLResult(handler="list_specialties", found=bool(rows), rows=rows, summary=summary)


def doctor_availability(ctx: SQLContext) -> SQLResult:
    from apps.doctors.models import Doctor
    from apps.chatbot.sql_tool.utils import parse_time_ceiling, parse_time_floor
    from apps.chatbot.booking.config import booking_horizon_days
    from apps.chatbot.temporal import day_label, resolve_temporal_query

    clinic = ctx.clinic
    nlu = ctx.nlu
    tz = clinic_timezone(clinic)
    today = timezone.now().astimezone(tz).date()

    scope = resolve_temporal_query(
        date_entities=entity_list(nlu.entities.date),
        today=today,
        horizon_days=booking_horizon_days(clinic),
        message=ctx.message,
        tz=tz,
    )
    if not scope.searchable:
        return SQLResult(
            handler="doctor_availability",
            found=False,
            summary=_unsearchable_summary(scope),
            meta={**scope.as_meta(), "authoritative_summary": True},
        )

    time_entities = _clean_time_entities(entity_list(nlu.entities.time))
    time_floor = parse_time_floor(time_entities)
    time_ceiling = parse_time_ceiling(time_entities)

    doctor_qs = Doctor.objects.filter(
        clinic=clinic,
        is_deleted=False,
        is_active=True,
        is_accepting_patients=True,
    )
    doctor_ids = entity_ids(nlu.resolved_ids.doctor_id)
    if doctor_ids:
        doctor_qs = doctor_qs.filter(id__in=doctor_ids)
    else:
        names = entity_list(nlu.entities.doctor_name)
        names = [
            n
            for n in names
            if n.lower() not in _NAME_NOISE
            and not all(tok in _NAME_NOISE for tok in n.lower().split())
        ]
        if names:
            doctor_qs = doctor_qs.filter(build_name_filter("full_name", names))

    doctor_named = bool(doctor_ids) or bool(entity_list(nlu.entities.doctor_name))

    specialty_ids = entity_ids(nlu.resolved_ids.specialty_id)
    symptom_resolution = None
    if specialty_ids:
        doctor_qs = doctor_qs.filter(doctor_specialties__specialty_id__in=specialty_ids).distinct()
    else:
        specs = entity_list(nlu.entities.specialty)
        if specs:
            doctor_qs = doctor_qs.filter(build_name_filter("specialties__name", specs)).distinct()
        elif not doctor_named:
            # Same fix as search_doctors: a bare symptom ("cardiac doctor
            # available tomorrow") must not silently check availability
            # for every doctor at the clinic regardless of specialty.
            from apps.chatbot.booking.discovery import (
                resolve_symptom_specialty_ids,
                symptom_no_match_result,
            )

            resolution = resolve_symptom_specialty_ids(clinic, nlu, ctx.message)
            if resolution is not None:
                if resolution.matched_ids:
                    doctor_qs = doctor_qs.filter(
                        doctor_specialties__specialty_id__in=resolution.matched_ids
                    ).distinct()
                else:
                    symptom_resolution = resolution

    doctors = [] if symptom_resolution else list(doctor_qs[:5])
    if not doctors:
        if symptom_resolution is not None:
            no_match = symptom_no_match_result(
                "doctor_availability", symptom_resolution, kind="doctor"
            )
            return SQLResult(
                handler="doctor_availability",
                found=False,
                summary=no_match.summary,
                meta={**scope.as_meta(), "target_date": scope.start.isoformat(), **no_match.meta},
            )
        return SQLResult(
            handler="doctor_availability",
            found=False,
            summary="No matching doctors found to check availability.",
            meta={**scope.as_meta(), "target_date": scope.start.isoformat()},
        )

    slots, target_date = _first_day_with_slots(
        clinic,
        scope=scope,
        doctors=doctors,
        time_floor=time_floor,
        time_ceiling=time_ceiling,
    )
    target_date = target_date or scope.start

    found = bool(slots)
    where = day_label(target_date, today=today)
    if found:
        summary = f"Found {len(slots)} available slot(s) on {where}."
        if scope.conflict and scope.conflict_weekday:
            # The date the patient gave and the weekday they gave disagree.
            # The date wins, but we say so rather than quietly picking one.
            summary += (
                f" Note: you mentioned {scope.conflict_weekday}, but "
                f"{where} is a {target_date.strftime('%A')}."
            )
    else:
        # A month with nothing open must say so about the month, not about
        # whichever single day the scan happened to end on.
        if scope.is_range and scope.scope_label:
            where = scope.scope_label
        if time_entities:
            wanted = ", ".join(time_entities)
            summary = (
                f"No available slots on {where} for {wanted}. "
                "Try another day or time."
            )
        else:
            summary = (
                f"No available slots found on {where}. "
                "Try another day, or tap Book Appointment to pick a time."
            )
    return SQLResult(
        handler="doctor_availability",
        found=found,
        rows=slots[:20],
        summary=summary,
        meta={
            **scope.as_meta(),
            "target_date": target_date.isoformat(),
            "authoritative_summary": True,
        },
    )


# A day scan is bounded so a wide horizon can never turn one question into an
# unbounded walk. Days the roster never works are skipped before any query.
_MAX_DAYS_SCANNED = 62


def _first_day_with_slots(
    clinic: Any,
    *,
    scope: TemporalQuery,
    doctors: list[Any],
    time_floor: time | None,
    time_ceiling: time | None,
) -> tuple[list[dict[str, Any]], date | None]:
    """Earliest day inside `scope` that has bookable slots left.

    A single-day scope visits exactly one day, so this is the previous
    behaviour for "Monday morning"; a month scope walks the month instead of
    collapsing to an arbitrary date.
    """
    from apps.chatbot.booking.slots import active_holds_for_date, compute_slots_for_day
    from apps.doctors.models import DoctorSchedule

    working_days = set(
        DoctorSchedule.objects.filter(
            clinic=clinic, doctor__in=doctors, is_active=True
        ).values_list("day_of_week", flat=True)
    )

    for scanned, day in enumerate(scope.iter_days()):
        if scanned >= _MAX_DAYS_SCANNED:
            break
        if working_days and day.weekday() not in working_days:
            continue
        slots = compute_slots_for_day(
            clinic,
            target_date=day,
            doctors=doctors,
            max_slots=20,
            excluded_keys=active_holds_for_date(clinic, day),
        )
        if time_floor is not None:
            slots = [s for s in slots if _slot_at_or_after(s, time_floor)]
        if time_ceiling is not None:
            slots = [s for s in slots if _slot_before(s, time_ceiling)]
        if slots:
            return slots, day
    return [], None


_WEEKDAY_WORDS = frozenset(
    w.lower()
    for w in (
        "monday", "tuesday", "wednesday", "thursday", "friday", "saturday",
        "sunday", "mon", "tue", "tues", "wed", "weds", "thu", "thur", "thurs",
        "fri", "sat", "sun",
    )
)


def _clean_time_entities(values: list[str]) -> list[str]:
    """Drop values that name a day or a bare number rather than a time.

    The NLU has been observed filing "Friday" and "2" under `time` — which
    produced the reply "No available slots on Friday, August 21 for Friday"
    and risks a nonsense floor/ceiling filter suppressing real slots.
    """
    cleaned = []
    for value in values:
        text = str(value).strip().lower()
        if not text or text in _WEEKDAY_WORDS or text.isdigit():
            continue
        cleaned.append(value)
    return cleaned


def _unsearchable_summary(scope: TemporalQuery) -> str:
    """What we say when there is nothing safe to search.

    Every branch names the constraint back to the patient and offers no
    slots. Substituting the earliest opening here is what let someone book
    19 August after asking about 12 January.
    """
    from apps.chatbot.temporal import TemporalStatus, day_label

    asked = scope.scope_label or scope.requested_text or "that date"
    if scope.status is TemporalStatus.PAST:
        return (
            f"{asked} has already passed. Which upcoming date would you like "
            "me to check?"
        )
    if scope.status is TemporalStatus.BEYOND_HORIZON:
        through = (
            day_label(scope.horizon_end) if scope.horizon_end else "the current window"
        )
        return (
            f"This clinic is scheduling appointments through {through}, so "
            f"{asked} isn't open for booking yet."
        )
    if scope.status is TemporalStatus.AMBIGUOUS:
        return (
            f"I couldn't pin down the date you meant by \"{asked}\". Could you "
            "give me the full date — for example \"September 1\"?"
        )
    return (
        f"I couldn't confidently work out which date \"{asked}\" refers to. "
        "Could you give me the full date — for example \"January 12, 2027\"?"
    )
