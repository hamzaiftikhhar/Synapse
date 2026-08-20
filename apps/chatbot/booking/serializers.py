"""Serialize booking session + clinic data into step UI payloads."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from django.utils import timezone

from apps.chatbot.booking.config import get_booking_config
from apps.chatbot.booking.modes import PATH_OPTIONS, step_index
from apps.chatbot.booking.state import BookingSession, BookingStep
from apps.chatbot.sql_tool.utils import clinic_timezone, doctor_to_dict


def serialize_step(clinic: Any, session: BookingSession) -> dict[str, Any]:
    """Full wizard response for the current step."""
    cfg = get_booking_config(clinic)
    current, total = step_index(
        session.mode,
        session.step,
        details_skipped=session.details_skipped,
        otp_skipped=session.otp_skipped,
    )
    payload: dict[str, Any] = {
        "booking_id": session.booking_id,
        "mode": session.mode,
        "step": session.step,
        "progress": {"current": current, "total": total},
        "reason": session.reason,
        "specialty_chip": None,
        "service_chip": None,
        "options": {},
        "hold": None,
        "review": None,
        "confirmation": None,
    }

    if session.service_id and session.service_name:
        chip = {"id": session.service_id, "name": session.service_name}
        payload["service_chip"] = chip
        payload["specialty_chip"] = chip  # legacy key; chip is the booked service
    elif session.specialty_id and session.specialty_name:
        payload["specialty_chip"] = {
            "id": session.specialty_id,
            "name": session.specialty_name,
        }

    step = session.step
    if step == BookingStep.PATH.value:
        payload["options"] = _path_options(clinic, session, cfg)
    elif step in {BookingStep.SERVICE.value, BookingStep.SPECIALTY.value}:
        payload["options"] = _service_options(clinic, session)
    elif step == BookingStep.DOCTOR.value:
        payload["options"] = _doctor_options(clinic, session)
    elif step == BookingStep.DATE.value:
        payload["options"] = _date_options(clinic, session, cfg)
    elif step == BookingStep.TIME.value:
        payload["options"] = _time_options(clinic, session, cfg)
    elif step == BookingStep.DETAILS.value:
        payload["options"] = {
            "slot_summary": _slot_summary(session),
            "first_name": session.patient_first_name,
            "last_name": session.patient_last_name,
            "phone": session.patient_phone,
            "email": session.patient_email,
            "verification_mode": cfg.get("verification_mode") or "sms",
        }
    elif step == BookingStep.OTP.value:
        payload["options"] = {
            "phone": session.patient_phone,
            "email": session.patient_email,
            "verification_mode": cfg.get("verification_mode") or "sms",
            "slot_summary": _slot_summary(session),
        }
        if session.hold_expires_at:
            payload["hold"] = {"expires_at": session.hold_expires_at}
    elif step == BookingStep.REVIEW.value:
        # Same shape as CONFIRMED below, minus the fields that don't exist
        # until confirm() actually runs — the frontend renders this as the
        # same card, with a Confirm button in place of the code line.
        payload["review"] = {
            "slot_summary": _slot_summary(session),
            "doctor_name": session.doctor_name,
            "service_name": session.service_name,
            "date": session.date,
            "start": session.slot_start,
            "end": session.slot_end,
            "first_name": session.patient_first_name,
            "last_name": session.patient_last_name,
        }
        if session.hold_expires_at:
            payload["hold"] = {"expires_at": session.hold_expires_at}
    elif step == BookingStep.CONFIRMED.value:
        payload["confirmation"] = {
            "confirmation_code": session.confirmation_code,
            "appointment_id": session.appointment_id,
            "slot_summary": _slot_summary(session),
            "doctor_name": session.doctor_name,
            "date": session.date,
            "start": session.slot_start,
            "first_name": session.patient_first_name,
            "last_name": session.patient_last_name,
        }

    return payload


def _path_options(clinic: Any, session: BookingSession, cfg: dict[str, Any]) -> dict[str, Any]:
    """First screen: three simple booking paths — no hero, no AI specialty pitch."""
    return {
        "title": "How would you like to book?",
        "paths": list(PATH_OPTIONS),
    }


def _hero_slot(clinic: Any, cfg: dict[str, Any]) -> dict[str, Any] | None:
    """Earliest bookable slot clinic-wide within a short horizon (deliberately
    much shorter than the full booking date_horizon_days — this runs on every
    fresh PATH-step landing, not just when a date is actually being browsed)."""
    from apps.chatbot.booking.slots import active_holds_for_date, compute_slots_for_day

    tz = clinic_timezone(clinic)
    today = timezone.now().astimezone(tz).date()
    horizon = int(cfg.get("hero_horizon_days") or 3)
    doctors = _doctors_for_session(clinic, doctor_id=None, service_id=None, mode="general")
    if not doctors:
        return None

    for i in range(horizon):
        d = today + timedelta(days=i)
        slots = compute_slots_for_day(
            clinic,
            target_date=d,
            doctors=doctors,
            max_slots=40,
            excluded_keys=active_holds_for_date(clinic, d),
        )
        if slots:
            day_label = "Today" if i == 0 else "Tomorrow" if i == 1 else d.strftime("%A")
            return {**slots[0], "day_label": day_label}
    return None


def _service_options(clinic: Any, session: BookingSession) -> dict[str, Any]:
    from apps.services.models import Service

    qs = Service.objects.filter(
        clinic=clinic, is_deleted=False, is_active=True
    ).order_by("name")
    if session.specialty_id:
        # Discovery bridge: Dermatology → Botox, Acne Consultation.
        # Specialty never determines booking eligibility — only which
        # services are listed when chat already pinned an area of care.
        qs = qs.filter(doctors__specialties__id=session.specialty_id).distinct()
    all_services = [
        {
            "id": str(s.id),
            "name": s.name,
            "slug": getattr(s, "slug", "") or "",
            "description": (s.description or "")[:200],
            "doctor_count": s.doctors.filter(
                is_deleted=False, is_active=True, is_accepting_patients=True
            ).count(),
        }
        for s in qs
    ]
    return {
        "search_placeholder": "Search services",
        "suggested": [],
        "all": all_services,
        "title": "Choose a service",
        "subtitle": "",
    }


def _doctor_options(clinic: Any, session: BookingSession) -> dict[str, Any]:
    from apps.doctors.models import Doctor

    qs = (
        Doctor.objects.filter(
            clinic=clinic,
            is_deleted=False,
            is_active=True,
            is_accepting_patients=True,
        )
        .prefetch_related("specialties", "services")
        .order_by("full_name")
    )
    if session.service_id:
        qs = qs.filter(doctor_services__service_id=session.service_id).distinct()

    doctors = []
    for d in qs[:20]:
        row = doctor_to_dict(d)
        next_slot = _next_available_slot(clinic, d)
        doctors.append(
            {
                "id": row["id"],
                "name": row["full_name"],
                "title": row["title"],
                "bio": (row.get("bio") or "")[:160],
                "photo_url": row.get("photo_url") or "",
                "languages": row.get("languages") or [],
                "specialties": row.get("specialties") or [],
                "services": row.get("services") or [],
                "next_available": next_slot,
            }
        )
    return {
        "title": "Choose a doctor",
        "doctors": doctors,
        "empty_message": (
            "No doctors currently offer this service."
            if session.service_id
            else "No doctors are currently accepting patients."
        ),
    }


def _date_options(clinic: Any, session: BookingSession, cfg: dict[str, Any]) -> dict[str, Any]:
    from apps.chatbot.booking.slots import compute_density_for_range

    tz = clinic_timezone(clinic)
    today = timezone.now().astimezone(tz).date()
    horizon = int(cfg.get("date_horizon_days") or 30)
    end = today + timedelta(days=horizon - 1)

    doctors = _doctors_for_session(
        clinic, doctor_id=session.doctor_id, service_id=session.service_id, mode=session.mode
    )
    density_by_date = (
        compute_density_for_range(
            clinic,
            doctors=doctors,
            start_date=today,
            end_date=end,
            thresholds=cfg.get("density_thresholds"),
        )
        if doctors
        else {}
    )

    dates: list[dict[str, Any]] = []
    for i in range(horizon):
        d = today + timedelta(days=i)
        info = density_by_date.get(d) or {"density": "closed", "reason": "no_schedule"}
        dates.append(
            {
                "date": d.isoformat(),
                "label": d.strftime("%a %b %d"),
                "is_today": i == 0,
                "density": info["density"],
                "reason": info["reason"],
            }
        )
    return {
        "title": (
            "Choose a date"
            if session.doctor_id
            else "When would you like to come in?"
        ),
        "dates": dates,
        "doctor_name": session.doctor_name,
        "hint": (
            None
            if session.doctor_id
            else "We'll match you with an available doctor for your chosen time."
        ),
        "selected_date": session.date,
    }


def _time_options(clinic: Any, session: BookingSession, cfg: dict[str, Any]) -> dict[str, Any]:
    if not session.date:
        return {"title": "Choose a time", "slots": [], "has_more": False}

    target = date.fromisoformat(session.date)
    preview = int(cfg.get("max_slots_preview") or 5)
    show_all = bool(session.show_all_times)

    slots = _slots_for_day(
        clinic,
        target_date=target,
        doctor_id=session.doctor_id,
        service_id=session.service_id,
        mode=session.mode,
    )

    time_hint_unmet = False
    if session.time_hint:
        try:
            floor = time.fromisoformat(session.time_hint)
        except ValueError:
            floor = None
        if floor is not None:
            filtered = [s for s in slots if _slot_time_of_day(s) >= floor]
            if filtered:
                slots = filtered
            else:
                time_hint_unmet = True

    has_more = len(slots) > preview and not show_all
    visible = slots if show_all else slots[:preview]
    title = "Choose a time"
    if session.mode in {"general", "first_available"} and not session.doctor_id:
        title = "First available times"
    return {
        "title": title,
        "date": session.date,
        "doctor_name": session.doctor_name,
        "slots": visible,
        "has_more": has_more,
        "total_slots": len(slots),
        "clinic_assigned": session.mode in {"general", "first_available"}
        and not session.doctor_id,
        "time_hint_unmet": time_hint_unmet,
        "time_hint": session.time_hint,
    }


def _slot_time_of_day(slot: dict[str, Any]) -> time:
    try:
        return datetime.fromisoformat(str(slot.get("start") or "").replace("Z", "+00:00")).time()
    except ValueError:
        return time.min


def _slot_summary(session: BookingSession) -> str:
    parts = []
    if session.service_name:
        parts.append(session.service_name)
    if session.doctor_name:
        parts.append(session.doctor_name)
    if session.date:
        parts.append(session.date)
    if session.slot_start:
        try:
            dt = datetime.fromisoformat(session.slot_start.replace("Z", "+00:00"))
            parts.append(dt.strftime("%I:%M %p"))
        except ValueError:
            parts.append(session.slot_start)
    return " · ".join(parts) if parts else ""


def _next_available_slot(clinic: Any, doctor: Any) -> dict[str, Any] | None:
    tz = clinic_timezone(clinic)
    today = timezone.now().astimezone(tz).date()
    for i in range(14):
        d = today + timedelta(days=i)
        slots = _slots_for_day(
            clinic,
            target_date=d,
            doctor_id=str(doctor.id),
            service_id=None,
            mode="choose_doctor",
        )
        if slots:
            return slots[0]
    return None


def _doctors_for_session(
    clinic: Any,
    *,
    doctor_id: str | None,
    service_id: str | None,
    mode: str,
) -> list[Any]:
    """The doctor-set-selection filter shared by _slots_for_day,
    _next_available_slot, _hero_slot, and the calendar density preview — the
    one place this filter logic lives (does not cover _doctor_options, which
    needs the full Doctor objects + prefetch_related for card rendering with
    its own limit=20).

    Booking eligibility is doctors ↔ services. Specialty is never used here.
    """
    from apps.doctors.models import Doctor

    doctor_qs = Doctor.objects.filter(
        clinic=clinic,
        is_deleted=False,
        is_active=True,
        is_accepting_patients=True,
    )
    if doctor_id:
        doctor_qs = doctor_qs.filter(id=doctor_id)
    elif service_id:
        doctor_qs = doctor_qs.filter(
            doctor_services__service_id=service_id
        ).distinct()

    # For general / first-available without a pinned doctor: scan more providers
    limit = 12 if mode in {"general", "first_available"} and not doctor_id else 5
    return list(doctor_qs[:limit])


def _slots_for_day(
    clinic: Any,
    *,
    target_date: date,
    doctor_id: str | None,
    service_id: str | None,
    mode: str,
) -> list[dict[str, Any]]:
    from apps.chatbot.booking.slots import active_holds_for_date, compute_slots_for_day

    doctors = _doctors_for_session(
        clinic, doctor_id=doctor_id, service_id=service_id, mode=mode
    )
    if not doctors:
        return []

    return compute_slots_for_day(
        clinic,
        target_date=target_date,
        doctors=doctors,
        max_slots=40,
        excluded_keys=active_holds_for_date(clinic, target_date),
    )
