"""Doctor and availability SQL handlers."""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from apps.chatbot.sql_tool.base import SQLContext, SQLResult
from apps.chatbot.sql_tool.utils import (
    build_name_filter,
    clinic_timezone,
    doctor_to_dict,
    entity_ids,
    entity_list,
    parse_natural_date,
)


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


def search_doctors(ctx: SQLContext) -> SQLResult:
    from apps.doctors.models import Doctor

    clinic = ctx.clinic
    nlu = ctx.nlu
    qs = (
        Doctor.objects.filter(clinic=clinic, is_deleted=False, is_active=True)
        .prefetch_related("specialties", "services")
    )

    doctor_ids = entity_ids(nlu.resolved_ids.doctor_id)
    if doctor_ids:
        qs = qs.filter(id__in=doctor_ids)
    else:
        names = entity_list(nlu.entities.doctor_name)
        # Ignore politeness / filler tokens mistaken for names
        names = [
            n
            for n in names
            if n.lower()
            not in {
                "please", "doctor", "doctors", "dentist", "help", "find",
                "me", "a", "the", "good", "best",
            }
        ]
        if names:
            qs = qs.filter(build_name_filter("full_name", names))

    specialty_ids = entity_ids(nlu.resolved_ids.specialty_id)
    if specialty_ids:
        qs = qs.filter(doctor_specialties__specialty_id__in=specialty_ids).distinct()
    else:
        specs = entity_list(nlu.entities.specialty)
        if specs:
            q = build_name_filter("specialties__name", specs)
            qs = qs.filter(q).distinct()

    service_id = nlu.resolved_ids.service_id
    if service_id:
        qs = qs.filter(services__id=service_id).distinct()
    elif nlu.entities.service:
        qs = qs.filter(services__name__icontains=nlu.entities.service, services__is_deleted=False).distinct()

    doctors = list(qs[:3])
    rows = [doctor_to_dict(d) for d in doctors]
    if rows:
        names = ", ".join(r["full_name"] for r in rows[:3])
        summary = f"Found {len(rows)} doctor(s): {names}."
    else:
        summary = "No matching doctors found."
    return SQLResult(handler="search_doctors", found=bool(rows), rows=rows, summary=summary)


def list_specialties(ctx: SQLContext) -> SQLResult:
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

    specialties = list(qs.order_by("name")[:20])
    rows = [
        {
            "id": str(s.id),
            "name": s.name,
            "slug": s.slug,
            "description": (s.description or "")[:300],
            "doctor_count": s.doctors.filter(is_deleted=False, is_active=True).count(),
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
    from apps.chatbot.booking.slots import active_holds_for_date, compute_slots_for_day
    from apps.doctors.models import Doctor
    from apps.chatbot.sql_tool.utils import parse_time_floor

    clinic = ctx.clinic
    nlu = ctx.nlu
    tz = clinic_timezone(clinic)

    dates = entity_list(nlu.entities.date)
    target_date = parse_natural_date(dates[0] if dates else None, tz=tz)
    if target_date is None:
        target_date = timezone.now().astimezone(tz).date() + timedelta(days=1)

    time_floor = parse_time_floor(entity_list(nlu.entities.time))

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
        if names:
            doctor_qs = doctor_qs.filter(build_name_filter("full_name", names))

    specialty_ids = entity_ids(nlu.resolved_ids.specialty_id)
    if specialty_ids:
        doctor_qs = doctor_qs.filter(doctor_specialties__specialty_id__in=specialty_ids).distinct()
    else:
        specs = entity_list(nlu.entities.specialty)
        if specs:
            doctor_qs = doctor_qs.filter(build_name_filter("specialties__name", specs)).distinct()

    doctors = list(doctor_qs[:5])
    if not doctors:
        return SQLResult(
            handler="doctor_availability",
            found=False,
            summary="No matching doctors found to check availability.",
            meta={"target_date": target_date.isoformat()},
        )

    slots = compute_slots_for_day(
        clinic,
        target_date=target_date,
        doctors=doctors,
        max_slots=20,
        excluded_keys=active_holds_for_date(clinic, target_date),
    )

    if time_floor is not None:
        slots = [
            s
            for s in slots
            if _slot_at_or_after(s, time_floor)
        ]

    found = bool(slots)
    summary = (
        f"Found {len(slots)} available slot(s) on {target_date.strftime('%A, %B %d')}."
        if found
        else (
            f"No available slots found on {target_date.strftime('%A, %B %d')}. "
            "Try another day, or tap Start Booking to pick a time."
        )
    )
    return SQLResult(
        handler="doctor_availability",
        found=found,
        rows=slots[:20],
        summary=summary,
        meta={"target_date": target_date.isoformat()},
    )
