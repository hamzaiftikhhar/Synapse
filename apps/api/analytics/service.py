"""Clinic-local aggregations for dashboard overview and the analytics page.

Every query is scoped to `clinic` from staff JWT / X-Tenant-ID. Daily
buckets use TruncDate(..., tzinfo=clinic.timezone) so a UTC midnight does
not shift an appointment onto the wrong clinic calendar day.
"""

from __future__ import annotations

from datetime import datetime, time as dtime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F
from django.db.models.functions import Coalesce, TruncDate

from django.utils import timezone as dj_timezone

from apps.api.analytics.ranges import change_pct, fill_daily, parse_year_month, window_for
from apps.appointments.models import Appointment, AppointmentSource, AppointmentStatus
from apps.chatbot.models import ChatMessage, ChatSession, ChatSessionStatus
from apps.clinics.models import Clinic
from apps.knowledge.models import Document, KnowledgeChunk
from apps.patients.models import Patient


def _day(qs, field: str, tz: ZoneInfo):
    return qs.annotate(day=TruncDate(field, tzinfo=tz))


def _daily_counts(qs, field: str, tz: ZoneInfo, start: datetime, end: datetime) -> list[dict]:
    rows = [
        {"date": row["day"].isoformat() if row["day"] else "", "count": int(row["n"] or 0)}
        for row in _day(qs, field, tz).values("day").annotate(n=Count("id")).order_by("day")
        if row["day"] is not None
    ]
    return fill_daily(rows, start=start, end=end, value_keys=("count",))


def _status_counts(qs) -> list[dict]:
    order = [
        AppointmentStatus.CONFIRMED,
        AppointmentStatus.PENDING,
        AppointmentStatus.COMPLETED,
        AppointmentStatus.CANCELLED,
        AppointmentStatus.NO_SHOW,
        AppointmentStatus.RESCHEDULED,
    ]
    raw = {row["status"]: int(row["n"]) for row in qs.values("status").annotate(n=Count("id"))}
    return [{"status": status, "count": raw.get(status, 0)} for status in order]


def _top_named(rows: list[dict], *, limit: int = 5) -> tuple[list[dict], int]:
    ranked = [r for r in rows if r.get("label")]
    extra = max(len(ranked) - limit, 0)
    return ranked[:limit], extra


_RADAR_SOURCES = (
    AppointmentSource.PHONE,
    AppointmentSource.WALK_IN,
    AppointmentSource.CHATBOT,
)
_RADAR_AXES = (
    ("volume", "Volume"),
    (AppointmentStatus.CONFIRMED, "Confirmed"),
    (AppointmentStatus.COMPLETED, "Completed"),
    (AppointmentStatus.PENDING, "Pending"),
    (AppointmentStatus.CANCELLED, "Cancelled"),
)


def _source_radar(qs) -> list[dict]:
    """Compare phone / walk-in / chatbot bookings across status axes.

    Recharts radar wants one row per axis: {axis, phone, walk_in, chatbot}.
    """
    raw = list(
        qs.filter(source__in=_RADAR_SOURCES)
        .values("source", "status")
        .annotate(n=Count("id"))
    )
    by = {(row["source"], row["status"]): int(row["n"]) for row in raw}
    totals = {src: 0 for src in _RADAR_SOURCES}
    for (src, _status), n in by.items():
        totals[src] += n
    points: list[dict] = []
    for key, label in _RADAR_AXES:
        item = {"axis": label}
        for src in _RADAR_SOURCES:
            item[src] = totals[src] if key == "volume" else by.get((src, key), 0)
        points.append(item)
    return points


def overview(clinic: Clinic, *, days: int) -> dict:
    start, now, prev_start, tz = window_for(clinic, days)
    cid = clinic.id

    conv_qs = ChatSession.objects.filter(clinic_id=cid)
    appt_qs = Appointment.objects.filter(clinic_id=cid)
    patient_qs = Patient.objects.filter(clinic_id=cid)

    conversations = conv_qs.filter(created_at__gte=start, created_at__lte=now).count()
    conversations_prev = conv_qs.filter(created_at__gte=prev_start, created_at__lt=start).count()
    appointments = appt_qs.filter(created_at__gte=start, created_at__lte=now).count()
    appointments_prev = appt_qs.filter(created_at__gte=prev_start, created_at__lt=start).count()
    patients_total = patient_qs.count()
    patients_new = patient_qs.filter(created_at__gte=start, created_at__lte=now).count()
    patients_returning = (
        appt_qs.filter(created_at__gte=start, created_at__lte=now, patient__created_at__lt=start)
        .values("patient_id")
        .distinct()
        .count()
    )
    completed = appt_qs.filter(
        created_at__gte=start,
        created_at__lte=now,
        status=AppointmentStatus.COMPLETED,
    ).count()
    completed_prev = appt_qs.filter(
        created_at__gte=prev_start,
        created_at__lt=start,
        status=AppointmentStatus.COMPLETED,
    ).count()

    conv_daily = _daily_counts(
        conv_qs.filter(created_at__gte=start, created_at__lte=now),
        "created_at",
        tz,
        start,
        now,
    )
    appt_daily = _daily_counts(
        appt_qs.filter(created_at__gte=start, created_at__lte=now),
        "created_at",
        tz,
        start,
        now,
    )
    patients_daily = _daily_counts(
        patient_qs.filter(created_at__gte=start, created_at__lte=now),
        "created_at",
        tz,
        start,
        now,
    )
    completed_daily = _daily_counts(
        appt_qs.filter(
            created_at__gte=start, created_at__lte=now, status=AppointmentStatus.COMPLETED
        ),
        "created_at",
        tz,
        start,
        now,
    )
    trend = [
        {
            "date": c["date"],
            "conversations": c["count"],
            "appointments": a["count"],
        }
        for c, a in zip(conv_daily, appt_daily)
    ]

    in_window = appt_qs.filter(start_time__gte=start, start_time__lte=now)
    booked = appt_qs.filter(created_at__gte=start, created_at__lte=now)
    status = _status_counts(booked)

    specialty_rows = list(
        in_window.filter(doctor__doctor_specialties__specialty__is_deleted=False)
        .values("doctor__doctor_specialties__specialty__name")
        .annotate(count=Count("id", distinct=True))
        .order_by("-count")
    )
    specialties, specialties_more = _top_named(
        [
            {"label": row["doctor__doctor_specialties__specialty__name"], "count": int(row["count"])}
            for row in specialty_rows
        ]
    )

    inbox_raw = {
        row["status"]: int(row["n"])
        for row in conv_qs.values("status").annotate(n=Count("id"))
    }
    live_statuses = (
        AppointmentStatus.PENDING,
        AppointmentStatus.CONFIRMED,
        AppointmentStatus.RESCHEDULED,
    )
    today_start = datetime.combine(now.date(), dtime.min, tzinfo=tz)
    today_end = today_start + timedelta(days=1)
    upcoming_qs = appt_qs.filter(start_time__gte=now, status__in=live_statuses)

    return {
        "range_days": days,
        "timezone": clinic.timezone,
        "summary": {
            "conversations": conversations,
            "conversations_change_pct": change_pct(conversations, conversations_prev),
            "appointments": appointments,
            "appointments_change_pct": change_pct(appointments, appointments_prev),
            "patients_total": patients_total,
            "patients_new": patients_new,
            "patients_returning": patients_returning,
            "completed_appointments": completed,
            "completed_change_pct": change_pct(completed, completed_prev),
        },
        "ops": {
            "appointments_today": appt_qs.filter(
                start_time__gte=today_start, start_time__lt=today_end
            ).count(),
            "appointments_upcoming": upcoming_qs.count(),
            "appointments_completed": appt_qs.filter(status=AppointmentStatus.COMPLETED).count(),
            "appointments_cancelled": appt_qs.filter(status=AppointmentStatus.CANCELLED).count(),
            "patients_upcoming": upcoming_qs.values("patient_id").distinct().count(),
            "doctors_with_upcoming": upcoming_qs.values("doctor_id").distinct().count(),
            "inbox": {
                "total": sum(inbox_raw.values()),
                "active": inbox_raw.get(ChatSessionStatus.ACTIVE, 0),
                "closed": inbox_raw.get(ChatSessionStatus.CLOSED, 0),
                "escalated": inbox_raw.get(ChatSessionStatus.ESCALATED, 0),
            },
        },
        "conversation_appointment_trend": trend,
        "conversations_daily": [row["count"] for row in conv_daily],
        "appointments_daily": [row["count"] for row in appt_daily],
        "patients_daily": [row["count"] for row in patients_daily],
        "completed_daily": [row["count"] for row in completed_daily],
        "appointment_status": status,
        "appointments_by_specialty": specialties,
        "appointments_by_specialty_more": specialties_more,
        "appointment_source_radar": _source_radar(in_window),
    }


def insights(clinic: Clinic, *, days: int) -> dict:
    start, now, _prev, tz = window_for(clinic, days)
    cid = clinic.id
    conv_qs = ChatSession.objects.filter(clinic_id=cid)
    appt_qs = Appointment.objects.filter(clinic_id=cid)
    in_created = appt_qs.filter(created_at__gte=start, created_at__lte=now)
    in_start = appt_qs.filter(start_time__gte=start, start_time__lte=now)
    window_sessions = conv_qs.filter(created_at__gte=start, created_at__lte=now)

    by_status = {
        row["status"]: int(row["n"])
        for row in window_sessions.values("status").annotate(n=Count("id"))
    }
    session_count = window_sessions.count()
    message_count = ChatMessage.objects.filter(
        clinic_id=cid,
        session__created_at__gte=start,
        session__created_at__lte=now,
    ).count()
    avg_messages = round(message_count / session_count, 2) if session_count else 0.0

    duration = window_sessions.annotate(
        ended=Coalesce("closed_at", "last_active_at"),
        span=ExpressionWrapper(F("ended") - F("created_at"), output_field=DurationField()),
    ).aggregate(avg=Avg("span"))
    avg_seconds = int(duration["avg"].total_seconds()) if duration["avg"] else 0

    conv_daily = _daily_counts(window_sessions, "created_at", tz, start, now)
    outcome_rows = list(
        _day(window_sessions, "created_at", tz)
        .values("day", "status")
        .annotate(n=Count("id"))
        .order_by("day")
    )
    outcome_by_day: dict[str, dict[str, int]] = {}
    for row in outcome_rows:
        if not row["day"]:
            continue
        key = row["day"].isoformat()
        bucket = outcome_by_day.setdefault(key, {"closed": 0, "escalated": 0, "active": 0})
        status = row["status"]
        if status == ChatSessionStatus.CLOSED:
            bucket["closed"] += int(row["n"])
        elif status == ChatSessionStatus.ESCALATED:
            bucket["escalated"] += int(row["n"])
        else:
            bucket["active"] += int(row["n"])
    outcome_trend = fill_daily(
        [{"date": k, **v} for k, v in outcome_by_day.items()],
        start=start,
        end=now,
        value_keys=("closed", "escalated", "active"),
    )

    appt_trend = _daily_counts(in_created, "created_at", tz, start, now)

    provider_rows = list(
        in_start.values("doctor_id", "doctor__full_name")
        .annotate(count=Count("id"))
        .order_by("-count")
    )
    providers, providers_more = _top_named(
        [{"label": row["doctor__full_name"], "count": int(row["count"])} for row in provider_rows]
    )

    stacked_ids = [row["doctor_id"] for row in provider_rows[:7]]
    stacked: list[dict] = []
    if stacked_ids:
        by_doc: dict[UUID, dict] = {
            row["doctor_id"]: {
                "label": row["doctor__full_name"],
                "completed": 0,
                "cancelled": 0,
                "no_show": 0,
            }
            for row in provider_rows[:7]
        }
        raw = (
            in_start.filter(doctor_id__in=stacked_ids)
            .values("doctor_id", "status")
            .annotate(n=Count("id"))
        )
        for row in raw:
            item = by_doc.get(row["doctor_id"])
            if item is None:
                continue
            if row["status"] == AppointmentStatus.COMPLETED:
                item["completed"] = int(row["n"])
            elif row["status"] == AppointmentStatus.CANCELLED:
                item["cancelled"] = int(row["n"])
            elif row["status"] == AppointmentStatus.NO_SHOW:
                item["no_show"] = int(row["n"])
        stacked = [by_doc[did] for did in stacked_ids if did in by_doc]

    new_daily = _daily_counts(
        Patient.objects.filter(clinic_id=cid, created_at__gte=start, created_at__lte=now),
        "created_at",
        tz,
        start,
        now,
    )
    returning_rows = list(
        _day(
            Appointment.objects.filter(
                clinic_id=cid,
                created_at__gte=start,
                created_at__lte=now,
                patient__created_at__lt=start,
            ),
            "created_at",
            tz,
        )
        .values("day")
        .annotate(count=Count("patient_id", distinct=True))
        .order_by("day")
    )
    returning_daily = fill_daily(
        [
            {"date": row["day"].isoformat(), "count": int(row["count"])}
            for row in returning_rows
            if row["day"]
        ],
        start=start,
        end=now,
        value_keys=("count",),
    )
    patient_trend = [
        {"date": n["date"], "new": n["count"], "returning": r["count"]}
        for n, r in zip(new_daily, returning_daily)
    ]

    buckets = {"1": 0, "2": 0, "3": 0, "4+": 0}
    for row in Appointment.objects.filter(clinic_id=cid).values("patient_id").annotate(n=Count("id")):
        n = int(row["n"])
        if n <= 0:
            continue
        if n >= 4:
            buckets["4+"] += 1
        else:
            buckets[str(n)] += 1
    patient_frequency = [
        {"label": "1 appointment", "count": buckets["1"]},
        {"label": "2 appointments", "count": buckets["2"]},
        {"label": "3 appointments", "count": buckets["3"]},
        {"label": "4+", "count": buckets["4+"]},
    ]

    docs = Document.objects.filter(clinic_id=cid, is_deleted=False)
    chunks = KnowledgeChunk.objects.filter(clinic_id=cid)
    last_updated = docs.order_by("-updated_at").values_list("updated_at", flat=True).first()
    knowledge_growth = _daily_counts(
        docs.filter(created_at__gte=start, created_at__lte=now),
        "created_at",
        tz,
        start,
        now,
    )

    from apps.ai.services.analytics import summarize_usage

    ai = summarize_usage(clinic_id=cid, days=days)

    base = overview(clinic, days=days)
    returning_patients = (
        Appointment.objects.filter(clinic_id=cid, created_at__gte=start, created_at__lte=now)
        .filter(patient__created_at__lt=start)
        .values("patient_id")
        .distinct()
        .count()
    )

    return {
        **base,
        "conversations_detail": {
            "active": by_status.get(ChatSessionStatus.ACTIVE, 0),
            "closed": by_status.get(ChatSessionStatus.CLOSED, 0),
            "escalated": by_status.get(ChatSessionStatus.ESCALATED, 0),
            "avg_messages": avg_messages,
            "avg_duration_seconds": avg_seconds,
            "volume": conv_daily,
            "outcomes": outcome_trend,
        },
        "appointment_trend": appt_trend,
        "appointments_by_provider": providers,
        "appointments_by_provider_more": providers_more,
        "provider_status": stacked,
        "patients_detail": {
            "returning": returning_patients,
            "trend": patient_trend,
            "frequency": patient_frequency,
        },
        "knowledge": {
            "documents": docs.count(),
            "chunks": chunks.count(),
            "last_updated": last_updated.isoformat() if last_updated else None,
            "growth": knowledge_growth,
        },
        "ai": ai,
    }


def breakdown(clinic: Clinic, *, days: int, dimension: str) -> dict:
    start, now, _prev, tz = window_for(clinic, days)
    cid = clinic.id
    in_start = Appointment.objects.filter(
        clinic_id=cid, start_time__gte=start, start_time__lte=now
    )

    if dimension == "doctor":
        rows = list(
            in_start.values("doctor__full_name").annotate(count=Count("id")).order_by("-count")
        )
        items, more = _top_named(
            [{"label": r["doctor__full_name"], "count": int(r["count"])} for r in rows]
        )
        return {"dimension": dimension, "items": items, "more": more}

    if dimension == "service":
        rows = list(
            in_start.exclude(service_id=None)
            .values("service__name")
            .annotate(count=Count("id"))
            .order_by("-count")
        )
        items, more = _top_named(
            [{"label": r["service__name"], "count": int(r["count"])} for r in rows]
        )
        return {"dimension": dimension, "items": items, "more": more}

    if dimension == "specialty":
        rows = list(
            in_start.filter(doctor__doctor_specialties__specialty__is_deleted=False)
            .values("doctor__doctor_specialties__specialty__name")
            .annotate(count=Count("id", distinct=True))
            .order_by("-count")
        )
        items, more = _top_named(
            [
                {
                    "label": r["doctor__doctor_specialties__specialty__name"],
                    "count": int(r["count"]),
                }
                for r in rows
            ]
        )
        return {"dimension": dimension, "items": items, "more": more}

    if dimension == "insurance":
        rows = list(
            in_start.exclude(insurance_plan_id=None)
            .values("insurance_plan__provider_name")
            .annotate(count=Count("id"))
            .order_by("-count")
        )
        items, more = _top_named(
            [{"label": r["insurance_plan__provider_name"], "count": int(r["count"])} for r in rows]
        )
        return {"dimension": dimension, "items": items, "more": more}

    if dimension == "new_patients":
        series = _daily_counts(
            Patient.objects.filter(clinic_id=cid, created_at__gte=start, created_at__lte=now),
            "created_at",
            tz,
            start,
            now,
        )
        return {"dimension": dimension, "items": [{"label": r["date"], "count": r["count"]} for r in series], "more": 0}

    from ninja.errors import HttpError

    raise HttpError(400, "Invalid dimension")


_BOOKED_STATUSES = (
    AppointmentStatus.PENDING,
    AppointmentStatus.CONFIRMED,
    AppointmentStatus.COMPLETED,
    AppointmentStatus.RESCHEDULED,
)
_UPCOMING_STATUSES = (
    AppointmentStatus.PENDING,
    AppointmentStatus.CONFIRMED,
    AppointmentStatus.RESCHEDULED,
)


def _person_name(obj) -> str:
    if obj is None:
        return ""
    return str(getattr(obj, "full_name", "") or "").strip()


def calendar_month(clinic: Clinic, *, year: int | None, month: int | None) -> dict:
    """Month grid counts (clinic-local days) plus the next upcoming visits."""
    y, m, start, end, now_local, tz = parse_year_month(clinic, year, month)
    cid = clinic.id
    month_qs = Appointment.objects.filter(
        clinic_id=cid,
        start_time__gte=start,
        start_time__lt=end,
        status__in=_BOOKED_STATUSES,
    )
    days = []
    for row in (
        _day(month_qs, "start_time", tz)
        .values("day")
        .annotate(n=Count("id"))
        .order_by("day")
    ):
        day = row.get("day")
        if day is None:
            continue
        iso = day.isoformat() if hasattr(day, "isoformat") else str(day)[:10]
        if not iso:
            continue
        days.append({"date": iso, "count": int(row.get("n") or 0)})

    upcoming = []
    for appt in (
        Appointment.objects.filter(
            clinic_id=cid,
            start_time__gte=dj_timezone.now(),
            status__in=_UPCOMING_STATUSES,
        )
        .select_related("patient", "doctor", "service")
        .order_by("start_time")[:3]
    ):
        start_iso = appt.start_time.isoformat() if appt.start_time else ""
        end_iso = appt.end_time.isoformat() if appt.end_time else ""
        if not start_iso:
            continue
        service = getattr(appt, "service", None)
        upcoming.append(
            {
                "id": str(appt.id),
                "start_time": start_iso,
                "end_time": end_iso,
                "patient_name": _person_name(getattr(appt, "patient", None)),
                "doctor_name": _person_name(getattr(appt, "doctor", None)),
                "service_name": str(getattr(service, "name", "") or "").strip(),
                "status": appt.status or "",
            }
        )

    return {
        "year": y,
        "month": m,
        "timezone": getattr(tz, "key", None) or str(tz),
        "today": now_local.date().isoformat(),
        "days": days,
        "upcoming": upcoming,
    }
