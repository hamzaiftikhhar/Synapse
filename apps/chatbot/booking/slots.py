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


def _expand_day_slots(
    target_date: date,
    tz: Any,
    *,
    schedule_rows: Iterable[tuple[time, time, int]],
    doctor_id: str,
    doctor_name: str,
    booked: set[datetime],
    held: set[str],
    now: datetime,
    max_slots: int,
) -> list[dict[str, Any]]:
    """Pure, in-memory: turn one doctor's one day of already-fetched
    schedule rows (start_time, end_time, slot_duration_min) into bookable
    slot dicts. No queries here — callers fetch schedule/booked/held once
    (per-day for compute_slots_for_day, or batched across doctors/days for
    compute_next_available_slots) and pass the results in."""
    slots: list[dict[str, Any]] = []
    for start_time, end_time, slot_duration_min in schedule_rows:
        open_at, close_at = effective_schedule_window(start_time, end_time)
        slot_start = timezone.make_aware(datetime.combine(target_date, open_at), tz)
        slot_end = timezone.make_aware(datetime.combine(target_date, close_at), tz)
        duration = timedelta(minutes=slot_duration_min)
        current = slot_start
        while current + duration <= slot_end:
            normalized = current.replace(second=0, microsecond=0)
            if normalized < now:
                current += duration
                continue
            key = f"{doctor_id}|{normalized.isoformat()}"
            if normalized in booked or key in held:
                current += duration
                continue
            end = current + duration
            slots.append(
                {
                    **slot_to_dict(
                        current, end, doctor_name=doctor_name, doctor_id=doctor_id
                    ),
                    "id": f"{doctor_id}_{normalized.isoformat()}",
                    "label": current.strftime("%I:%M %p"),
                }
            )
            current += duration
            if len(slots) >= max_slots:
                break
    return slots


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
                status__in=[
                    AppointmentStatus.PENDING,
                    AppointmentStatus.CONFIRMED,
                    AppointmentStatus.COMPLETED,
                    AppointmentStatus.NO_SHOW,
                ],
            ).values_list("start_time", flat=True)
        }

        schedule_rows = [
            (sched.start_time, sched.end_time, sched.slot_duration_min)
            for sched in DoctorSchedule.objects.filter(
                clinic=clinic,
                doctor=doctor,
                day_of_week=day_of_week,
                is_active=True,
            )
        ]
        slots.extend(
            _expand_day_slots(
                target_date,
                tz,
                schedule_rows=schedule_rows,
                doctor_id=str(doctor.id),
                doctor_name=doctor.full_name,
                booked=booked,
                held=excluded,
                now=now,
                max_slots=max_slots,
            )
        )

    slots.sort(key=lambda s: s.get("start") or "")
    return slots


def compute_next_available_slots(
    clinic: Any,
    *,
    doctors: Iterable[Any],
    horizon_days: int = 14,
) -> dict[str, dict[str, Any] | None]:
    """Next bookable slot per doctor within the horizon, batched into a
    small constant number of queries across ALL doctors and days.

    Previously this was one _next_available_slot() call per doctor, each
    looping up to `horizon_days` days and, per day, re-querying schedule /
    leave / appointments / holds for that one doctor — for a 20-doctor
    "Choose a doctor" card render, up to ~1,400 DB round trips to answer
    "what's the next open slot" for each card. Confirmed live before this
    fix. This does the same 4 lookups once, for every doctor and the whole
    horizon at once, then walks the horizon in pure Python per doctor."""
    from apps.appointments.models import Appointment, AppointmentStatus
    from apps.doctors.models import DoctorLeave, DoctorSchedule

    doctor_list = list(doctors)
    if not doctor_list:
        return {}
    doctor_ids = [d.id for d in doctor_list]
    tz = clinic_timezone(clinic)
    today = timezone.now().astimezone(tz).date()
    end_date = today + timedelta(days=horizon_days - 1)
    range_start = timezone.make_aware(datetime.combine(today, time.min), tz)
    range_end = timezone.make_aware(datetime.combine(end_date, time.max), tz)
    now = timezone.now().astimezone(tz)

    schedule_by_doctor_weekday: dict[tuple[Any, int], list[tuple[time, time, int]]] = {}
    for row in DoctorSchedule.objects.filter(
        clinic=clinic, doctor_id__in=doctor_ids, is_active=True
    ).values("doctor_id", "day_of_week", "start_time", "end_time", "slot_duration_min"):
        key = (row["doctor_id"], row["day_of_week"])
        schedule_by_doctor_weekday.setdefault(key, []).append(
            (row["start_time"], row["end_time"], row["slot_duration_min"])
        )

    leave_by_doctor: dict[Any, list[tuple[Any, Any]]] = {}
    for doctor_id, start_at, end_at in DoctorLeave.objects.filter(
        clinic=clinic,
        doctor_id__in=doctor_ids,
        is_active=True,
        start_at__lt=range_end,
        end_at__gt=range_start,
    ).values_list("doctor_id", "start_at", "end_at"):
        leave_by_doctor.setdefault(doctor_id, []).append((start_at, end_at))

    booked_by_doctor: dict[Any, set[datetime]] = {}
    for doctor_id, start_time_val in Appointment.objects.filter(
        clinic=clinic,
        doctor_id__in=doctor_ids,
        start_time__gte=range_start,
        start_time__lte=range_end,
        status__in=[
            AppointmentStatus.PENDING,
            AppointmentStatus.CONFIRMED,
            AppointmentStatus.COMPLETED,
            AppointmentStatus.NO_SHOW,
        ],
    ).values_list("doctor_id", "start_time"):
        booked_by_doctor.setdefault(doctor_id, set()).add(
            start_time_val.astimezone(tz).replace(second=0, microsecond=0)
        )

    held_by_date = active_holds_for_range(clinic, today, end_date)

    results: dict[str, dict[str, Any] | None] = {}
    for doctor in doctor_list:
        doctor_id = doctor.id
        doctor_id_str = str(doctor_id)
        doctor_leaves = leave_by_doctor.get(doctor_id, [])
        found: dict[str, Any] | None = None
        for i in range(horizon_days):
            d = today + timedelta(days=i)
            schedule_rows = schedule_by_doctor_weekday.get((doctor_id, d.weekday()))
            if not schedule_rows:
                continue
            d_start = timezone.make_aware(datetime.combine(d, time.min), tz)
            d_end = timezone.make_aware(datetime.combine(d, time.max), tz)
            if any(s < d_end and e > d_start for s, e in doctor_leaves):
                continue
            day_slots = _expand_day_slots(
                d,
                tz,
                schedule_rows=schedule_rows,
                doctor_id=doctor_id_str,
                doctor_name=doctor.full_name,
                booked=booked_by_doctor.get(doctor_id, set()),
                held=held_by_date.get(d, set()),
                now=now,
                max_slots=1,
            )
            if day_slots:
                found = day_slots[0]
                break
        results[doctor_id_str] = found
    return results


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
            status__in=[
                AppointmentStatus.PENDING,
                AppointmentStatus.CONFIRMED,
                AppointmentStatus.COMPLETED,
                AppointmentStatus.NO_SHOW,
            ],
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
    return active_holds_for_range(clinic, target_date, target_date).get(
        target_date, set()
    )


def active_holds_for_range(
    clinic: Any, start_date: date, end_date: date
) -> dict[date, set[str]]:
    """Same data as active_holds_for_date, for every date in
    [start_date, end_date], from a single scan of this clinic's active
    sessions instead of one query per date — used by
    compute_next_available_slots so a 14-day horizon doesn't turn into 14
    separate hold queries per doctor."""
    from zoneinfo import ZoneInfo

    from apps.chatbot.models import ChatSession, ChatSessionStatus

    held_by_date: dict[date, set[str]] = {}
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
            d = slot_dt.date()
            if not (start_date <= d <= end_date):
                continue
            held_by_date.setdefault(d, set()).add(
                f"{doctor_id}|{slot_dt.replace(second=0, microsecond=0).isoformat()}"
            )
        except Exception:
            continue
    return held_by_date
