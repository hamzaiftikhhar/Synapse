"""Serialize booking session + clinic data into step UI payloads."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from django.utils import timezone

from apps.chatbot.booking.config import get_booking_config
from apps.chatbot.booking.modes import PATH_OPTIONS, step_index
from apps.chatbot.booking.state import BookingSession, BookingStep
from apps.chatbot.sql_tool.utils import clinic_timezone, doctor_to_dict, slot_to_dict


def serialize_step(clinic: Any, session: BookingSession) -> dict[str, Any]:
    """Full wizard response for the current step."""
    cfg = get_booking_config(clinic)
    current, total = step_index(session.mode, session.step)
    payload: dict[str, Any] = {
        "booking_id": session.booking_id,
        "mode": session.mode,
        "step": session.step,
        "progress": {"current": current, "total": total},
        "reason": session.reason,
        "specialty_chip": None,
        "options": {},
        "hold": None,
        "confirmation": None,
    }

    if session.specialty_id and session.specialty_name:
        payload["specialty_chip"] = {
            "id": session.specialty_id,
            "name": session.specialty_name,
        }

    step = session.step
    if step == BookingStep.PATH.value:
        payload["options"] = _path_options(clinic, session)
    elif step == BookingStep.SPECIALTY.value:
        payload["options"] = _specialty_options(clinic, session)
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


def _path_options(clinic: Any, session: BookingSession) -> dict[str, Any]:
    """First screen: who would you like to see?"""
    from apps.specialties.models import Specialty

    suggested: list[dict[str, Any]] = []
    for sid in session.suggested_specialty_ids or []:
        try:
            spec = Specialty.objects.get(clinic=clinic, id=sid, is_deleted=False)
            suggested.append(
                {
                    "id": str(spec.id),
                    "name": spec.name,
                    "description": getattr(spec, "description", "") or "",
                    "plain_label": getattr(spec, "plain_label", "") or "",
                }
            )
        except Specialty.DoesNotExist:
            continue

    return {
        "title": "Who would you like to see?",
        "subtitle": "Choose how you'd like to book — you can always go back.",
        "paths": list(PATH_OPTIONS),
        "suggested": suggested[:3],
    }


def _specialty_options(clinic: Any, session: BookingSession) -> dict[str, Any]:
    from apps.specialties.models import Specialty

    qs = Specialty.objects.filter(
        clinic=clinic, is_deleted=False, is_active=True
    ).order_by("name")
    all_specs = [
        {
            "id": str(s.id),
            "name": s.name,
            "slug": s.slug,
            "description": (s.description or "")[:200],
            "doctor_count": s.doctors.filter(is_deleted=False, is_active=True).count(),
        }
        for s in qs
    ]
    suggested_ids = set(session.suggested_specialty_ids or [])
    suggested = [s for s in all_specs if s["id"] in suggested_ids]
    return {
        "search_placeholder": "Condition, procedure or specialty",
        "suggested": suggested,
        "all": all_specs,
        "title": "Choose a specialty",
        "subtitle": (
            "Based on what you described, you may want to start with one of these."
            if suggested
            else "Select a specialty offered by this clinic."
        ),
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
        .prefetch_related("specialties")
        .order_by("full_name")
    )
    if session.specialty_id:
        qs = qs.filter(doctor_specialties__specialty_id=session.specialty_id).distinct()

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
                "languages": row.get("languages") or [],
                "specialties": row.get("specialties") or [],
                "next_available": next_slot,
            }
        )
    return {
        "title": "Choose a doctor",
        "doctors": doctors,
        "empty_message": (
            "No doctors found for this specialty. Clear the filter to see all doctors."
            if session.specialty_id
            else "No doctors are currently accepting patients."
        ),
    }


def _date_options(clinic: Any, session: BookingSession, cfg: dict[str, Any]) -> dict[str, Any]:
    tz = clinic_timezone(clinic)
    today = timezone.now().astimezone(tz).date()
    horizon = int(cfg.get("date_horizon_days") or 14)
    dates: list[dict[str, Any]] = []
    for i in range(horizon):
        d = today + timedelta(days=i)
        # Skip Sundays lightly if clinic closed — still show; availability checked on time step
        dates.append(
            {
                "date": d.isoformat(),
                "label": d.strftime("%a %b %d"),
                "is_today": i == 0,
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
        specialty_id=session.specialty_id,
        mode=session.mode,
    )
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
    }


def _slot_summary(session: BookingSession) -> str:
    parts = []
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
            specialty_id=None,
            mode="choose_doctor",
        )
        if slots:
            return slots[0]
    return None


def _slots_for_day(
    clinic: Any,
    *,
    target_date: date,
    doctor_id: str | None,
    specialty_id: str | None,
    mode: str,
) -> list[dict[str, Any]]:
    from apps.appointments.models import Appointment, AppointmentStatus
    from apps.doctors.models import Doctor, DoctorLeave, DoctorSchedule

    tz = clinic_timezone(clinic)
    day_of_week = target_date.weekday()
    day_start = timezone.make_aware(datetime.combine(target_date, time.min), tz)
    day_end = timezone.make_aware(datetime.combine(target_date, time.max), tz)

    doctor_qs = Doctor.objects.filter(
        clinic=clinic,
        is_deleted=False,
        is_active=True,
        is_accepting_patients=True,
    )
    if doctor_id:
        doctor_qs = doctor_qs.filter(id=doctor_id)
    elif specialty_id:
        doctor_qs = doctor_qs.filter(
            doctor_specialties__specialty_id=specialty_id
        ).distinct()

    # For general / first-available without a pinned doctor: scan more providers
    limit = 12 if mode in {"general", "first_available"} and not doctor_id else 5
    doctors = list(doctor_qs[:limit])
    if not doctors:
        return []

    # Collect holds from other active sessions (lightweight)
    held = _active_holds(clinic, target_date)

    slots: list[dict[str, Any]] = []
    for doctor in doctors:
        on_leave = DoctorLeave.objects.filter(
            clinic=clinic,
            doctor=doctor,
            is_active=True,
            start_at__lt=day_end,
            end_at__gt=day_start,
        ).exists()
        if on_leave:
            continue

        booked = {
            appt.astimezone(tz).replace(second=0, microsecond=0)
            for appt in Appointment.objects.filter(
                clinic=clinic,
                doctor=doctor,
                start_time__gte=day_start,
                start_time__lte=day_end,
                status__in=[AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED],
            ).values_list("start_time", flat=True)
        }

        for sched in DoctorSchedule.objects.filter(
            clinic=clinic,
            doctor=doctor,
            day_of_week=day_of_week,
            is_active=True,
        ):
            slot_start = timezone.make_aware(
                datetime.combine(target_date, sched.start_time), tz
            )
            slot_end = timezone.make_aware(
                datetime.combine(target_date, sched.end_time), tz
            )
            duration = timedelta(minutes=sched.slot_duration_min)
            current = slot_start
            # Skip past times for today
            now = timezone.now().astimezone(tz)
            while current + duration <= slot_end:
                normalized = current.replace(second=0, microsecond=0)
                if normalized < now:
                    current += duration
                    continue
                key = f"{doctor.id}|{normalized.isoformat()}"
                if normalized in booked or key in held:
                    current += duration
                    continue
                end = current + duration
                slots.append(
                    {
                        **slot_to_dict(
                            current,
                            end,
                            doctor_name=doctor.full_name,
                            doctor_id=str(doctor.id),
                        ),
                        "id": f"{doctor.id}_{normalized.isoformat()}",
                        "label": current.strftime("%I:%M %p"),
                    }
                )
                current += duration
                if len(slots) >= 40:
                    break

    # Prefer earliest across doctors
    slots.sort(key=lambda s: s.get("start") or "")
    return slots


def _active_holds(clinic: Any, target_date: date) -> set[str]:
    """Collect non-expired holds from chat sessions for this clinic/day."""
    from apps.chatbot.models import ChatSession, ChatSessionStatus

    held: set[str] = set()
    now = timezone.now()
    sessions = ChatSession.objects.filter(
        clinic=clinic, status=ChatSessionStatus.ACTIVE
    ).only("conversation_context")[:200]
    for s in sessions:
        ctx = s.conversation_context or {}
        booking = ctx.get("booking") if isinstance(ctx, dict) else None
        if not isinstance(booking, dict):
            continue
        expires = booking.get("hold_expires_at")
        start = booking.get("slot_start")
        doctor_id = booking.get("doctor_id")
        if not (expires and start and doctor_id):
            continue
        try:
            exp = datetime.fromisoformat(expires.replace("Z", "+00:00"))
            if timezone.is_naive(exp):
                exp = timezone.make_aware(exp, ZoneInfo("UTC"))
            if exp < now:
                continue
            slot_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
            if slot_dt.date() != target_date:
                continue
            held.add(f"{doctor_id}|{slot_dt.replace(second=0, microsecond=0).isoformat()}")
        except Exception:
            continue
    return held
