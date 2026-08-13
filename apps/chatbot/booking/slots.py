"""Consolidated slot-generation core.

Previously duplicated between booking/serializers.py._slots_for_day and
sql_tool/handlers/doctors.py.doctor_availability. This is the one place that
walks DoctorSchedule/DoctorLeave/Appointment for a given day into bookable
slot boundaries. Callers pre-filter/limit `doctors` themselves (the wizard and
the conversational availability handler filter doctors differently) — this
function only knows how to expand one day's schedule into slots.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any, Iterable

from django.utils import timezone

from apps.chatbot.sql_tool.utils import clinic_timezone, slot_to_dict

# HTML <input type="time"> empty values save as 00:00. A midnight open with a
# daytime close is treated as the 9:00 default, not a 24-hour clinic.
_MIDNIGHT = time(0, 0)
_DAYTIME_FLOOR = time(6, 0)
_DEFAULT_OPEN = time(9, 0)


def effective_schedule_window(start: time, end: time) -> tuple[time, time]:
    if start == _MIDNIGHT and end > _DAYTIME_FLOOR:
        return _DEFAULT_OPEN, end
    return start, end


def compute_slots_for_day(
    clinic: Any,
    *,
    target_date: date,
    doctors: Iterable[Any],
    max_slots: int = 40,
    excluded_keys: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Expand one day's DoctorSchedule into bookable slots, excluding leave,
    already-booked appointments, and any `excluded_keys` (e.g. active holds).

    `excluded_keys` entries are `f"{doctor_id}|{slot_start_isoformat}"`.
    """
    from apps.appointments.models import Appointment, AppointmentStatus
    from apps.doctors.models import DoctorLeave, DoctorSchedule

    tz = clinic_timezone(clinic)
    day_of_week = target_date.weekday()
    day_start = timezone.make_aware(datetime.combine(target_date, time.min), tz)
    day_end = timezone.make_aware(datetime.combine(target_date, time.max), tz)
    excluded = excluded_keys or set()
    now = timezone.now().astimezone(tz)

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
            open_at, close_at = effective_schedule_window(
                sched.start_time, sched.end_time
            )
            slot_start = timezone.make_aware(
                datetime.combine(target_date, open_at), tz
            )
            slot_end = timezone.make_aware(
                datetime.combine(target_date, close_at), tz
            )
            duration = timedelta(minutes=sched.slot_duration_min)
            current = slot_start
            while current + duration <= slot_end:
                normalized = current.replace(second=0, microsecond=0)
                if normalized < now:
                    current += duration
                    continue
                key = f"{doctor.id}|{normalized.isoformat()}"
                if normalized in booked or key in excluded:
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
                if len(slots) >= max_slots:
                    break

    slots.sort(key=lambda s: s.get("start") or "")
    return slots


_DEFAULT_DENSITY_THRESHOLDS = {"few": 0.5, "almost_full": 0.15}


def weekday_capacity(clinic: Any, doctors: Iterable[Any]) -> dict[int, int]:
    """Sum of bookable slot-units per weekday (0=Monday..6=Sunday) across
    `doctors`, from DoctorSchedule alone — independent of calendar dates.
    One query; reused for every date in a horizon that falls on that weekday.
    Deliberately NOT a per-day slot walk — see compute_slots_for_day for that."""
    from apps.doctors.models import DoctorSchedule

    capacity: dict[int, int] = {i: 0 for i in range(7)}
    doctor_ids = [d.id for d in doctors]
    if not doctor_ids:
        return capacity

    rows = DoctorSchedule.objects.filter(
        clinic=clinic, doctor_id__in=doctor_ids, is_active=True
    ).values("day_of_week", "start_time", "end_time", "slot_duration_min")
    for row in rows:
        duration = row["slot_duration_min"] or 30
        open_at, close_at = effective_schedule_window(
            row["start_time"], row["end_time"]
        )
        minutes = (
            close_at.hour * 60 + close_at.minute
        ) - (open_at.hour * 60 + open_at.minute)
        if minutes > 0 and duration > 0:
            capacity[row["day_of_week"]] += minutes // duration
    return capacity


def compute_density_for_range(
    clinic: Any,
    *,
    doctors: Iterable[Any],
    start_date: date,
    end_date: date,
    thresholds: dict[str, float] | None = None,
) -> dict[date, dict[str, Any]]:
    """Cheap, aggregate-only availability preview per date in [start_date,
    end_date] for a calendar/date-picker view — NOT a per-slot walk (use
    compute_slots_for_day for the real TIME step). Two aggregate queries plus
    the cached weekday capacity, regardless of horizon length.

    Returns {date: {"density": "closed"|"plenty"|"few"|"almost_full", "reason": str}}.
    An estimate: ignores active per-session holds (those are only authoritative
    at the real slot walk) and discounts leave at the whole-day granularity.
    """
    from apps.appointments.models import Appointment, AppointmentStatus
    from apps.clinics.models import ClinicBusinessHours
    from apps.doctors.models import DoctorLeave

    thresholds = thresholds or _DEFAULT_DENSITY_THRESHOLDS
    doctor_list = list(doctors)
    doctor_ids = [d.id for d in doctor_list]
    capacity_by_weekday = weekday_capacity(clinic, doctor_list)
    closed_weekdays = set(
        ClinicBusinessHours.objects.filter(clinic=clinic, is_closed=True).values_list(
            "day_of_week", flat=True
        )
    )

    tz = clinic_timezone(clinic)
    range_start = timezone.make_aware(datetime.combine(start_date, time.min), tz)
    range_end = timezone.make_aware(datetime.combine(end_date, time.max), tz)

    booked_by_date: dict[date, int] = {}
    if doctor_ids:
        starts = Appointment.objects.filter(
            clinic=clinic,
            doctor_id__in=doctor_ids,
            start_time__gte=range_start,
            start_time__lte=range_end,
            status__in=[AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED],
        ).values_list("start_time", flat=True)
        for start in starts:
            d = start.astimezone(tz).date()
            booked_by_date[d] = booked_by_date.get(d, 0) + 1

    leave_ranges: list[tuple[Any, Any, Any]] = []
    if doctor_ids:
        leave_ranges = list(
            DoctorLeave.objects.filter(
                clinic=clinic,
                doctor_id__in=doctor_ids,
                is_active=True,
                start_at__lt=range_end,
                end_at__gt=range_start,
            ).values_list("doctor_id", "start_at", "end_at")
        )

    num_doctors = len(doctor_list) or 1
    result: dict[date, dict[str, Any]] = {}
    d = start_date
    while d <= end_date:
        weekday = d.weekday()
        if weekday in closed_weekdays:
            result[d] = {"density": "closed", "reason": "closed"}
            d += timedelta(days=1)
            continue

        capacity = capacity_by_weekday.get(weekday, 0)
        if capacity > 0 and leave_ranges:
            d_start = timezone.make_aware(datetime.combine(d, time.min), tz)
            d_end = timezone.make_aware(datetime.combine(d, time.max), tz)
            on_leave = {
                doc_id for doc_id, s, e in leave_ranges if s < d_end and e > d_start
            }
            if on_leave:
                capacity = int(capacity * max(0, num_doctors - len(on_leave)) / num_doctors)

        if capacity <= 0:
            result[d] = {"density": "closed", "reason": "no_schedule"}
            d += timedelta(days=1)
            continue

        booked = booked_by_date.get(d, 0)
        remaining = max(capacity - booked, 0)
        ratio = remaining / capacity
        if ratio < thresholds["almost_full"]:
            density = "almost_full"
        elif ratio < thresholds["few"]:
            density = "few"
        else:
            density = "plenty"
        result[d] = {"density": density, "reason": ""}
        d += timedelta(days=1)

    return result


def active_holds_for_date(clinic: Any, target_date: date) -> set[str]:
    """Non-expired booking-wizard slot holds for this clinic/day, keyed
    `f"{doctor_id}|{slot_start_isoformat}"` — moved verbatim from
    booking/serializers.py._active_holds so both slot-generation call sites
    can be hold-aware."""
    from zoneinfo import ZoneInfo

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
