"""Appointment SQL handlers."""

from __future__ import annotations

from django.utils import timezone

from apps.chatbot.sql_tool.base import SQLContext, SQLResult
from apps.chatbot.sql_tool.utils import clinic_timezone, format_clinic_when


def patient_appointments(ctx: SQLContext) -> SQLResult:
    from apps.appointments.models import Appointment, AppointmentStatus

    if ctx.patient is None:
        return SQLResult(
            handler="patient_appointments",
            found=False,
            summary=(
                "To cancel or reschedule, please verify your phone number first "
                "so I can pull up your appointments. You can also start booking "
                "a new visit if you prefer."
            ),
            meta={"requires_auth": True, "auth_prompt": True},
        )

    qs = (
        Appointment.objects.filter(clinic=ctx.clinic, patient=ctx.patient)
        .select_related("doctor", "service", "insurance_plan")
        .order_by("start_time")
    )
    upcoming = qs.filter(
        start_time__gte=timezone.now(),
        status__in=[AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED],
    )[:10]

    tz = clinic_timezone(ctx.clinic)
    rows = [
        {
            "id": str(a.id),
            "doctor": a.doctor.full_name,
            "doctor_id": str(a.doctor_id),
            "service": a.service.name if a.service else "",
            "insurance": a.insurance_plan.provider_name if a.insurance_plan else "",
            "start_time": a.start_time.isoformat(),
            "end_time": a.end_time.isoformat(),
            "when": format_clinic_when(a.start_time, tz),
            "status": a.status,
            "confirmation_code": a.confirmation_code,
        }
        for a in upcoming
    ]
    summary = (
        f"Patient has {len(rows)} upcoming appointment(s)."
        if rows
        else "No upcoming appointments found."
    )
    return SQLResult(
        handler="patient_appointments",
        found=bool(rows),
        rows=rows,
        summary=summary,
    )
