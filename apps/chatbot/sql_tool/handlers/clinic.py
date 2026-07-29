"""Clinic info SQL handlers."""

from __future__ import annotations

from apps.chatbot.sql_tool.base import SQLContext, SQLResult


_DAY_NAMES = [
    "Monday", "Tuesday", "Wednesday", "Thursday",
    "Friday", "Saturday", "Sunday",
]


def clinic_hours(ctx: SQLContext) -> SQLResult:
    from apps.clinics.models import ClinicBusinessHours

    hours_qs = ClinicBusinessHours.objects.filter(clinic=ctx.clinic).order_by("day_of_week")
    rows = [
        {
            "day": _DAY_NAMES[h.day_of_week],
            "day_of_week": h.day_of_week,
            "open_time": h.open_time.strftime("%I:%M %p") if h.open_time else None,
            "close_time": h.close_time.strftime("%I:%M %p") if h.close_time else None,
            "is_closed": h.is_closed,
        }
        for h in hours_qs
    ]
    summary = (
        f"Clinic hours loaded for {len(rows)} day(s)."
        if rows
        else "No clinic hours configured."
    )
    return SQLResult(handler="clinic_hours", found=bool(rows), rows=rows, summary=summary)


def clinic_location(ctx: SQLContext) -> SQLResult:
    clinic = ctx.clinic
    address = clinic.address or {}
    street = address.get("street", "")
    city = address.get("city", "")
    state = address.get("state", "")
    zip_code = address.get("zip", "")
    rows = [
        {
            "name": clinic.name,
            "street": street,
            "city": city,
            "state": state,
            "zip": zip_code,
            "country": address.get("country", ""),
            "phone": clinic.phone,
            "email": clinic.email,
        }
    ]
    parts = [p for p in (street, city, state, zip_code) if p]
    summary = f"Clinic location: {', '.join(parts)}." if parts else "Location info loaded."
    return SQLResult(handler="clinic_location", found=True, rows=rows, summary=summary)
