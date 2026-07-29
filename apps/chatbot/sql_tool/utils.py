"""Shared helpers for SQL handlers."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from django.db.models import Q
from django.utils import timezone


def entity_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    text = str(value).strip()
    return [text] if text else []


def entity_ids(value: Any) -> list[str]:
    return entity_list(value)


def clinic_timezone(clinic: Any) -> ZoneInfo:
    tz_name = getattr(clinic, "timezone", None) or "UTC"
    try:
        return ZoneInfo(str(tz_name))
    except Exception:
        return ZoneInfo("UTC")


def parse_natural_date(raw: str | None, *, tz: ZoneInfo | None = None) -> date | None:
    """Lightweight natural-language date parser."""
    if not raw:
        return None
    raw = raw.strip().lower()
    now = timezone.now()
    if tz:
        today = now.astimezone(tz).date()
    else:
        today = timezone.localdate()

    if raw in ("today", "now"):
        return today
    if raw == "tomorrow":
        return today + timedelta(days=1)

    day_map = {
        "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
        "friday": 4, "saturday": 5, "sunday": 6,
        "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
    }
    for name, weekday in day_map.items():
        if name in raw:
            days_ahead = (weekday - today.weekday()) % 7 or 7
            return today + timedelta(days=days_ahead)

    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%B %d", "%b %d"):
        try:
            parsed = datetime.strptime(raw, fmt)
            if parsed.year == 1900:
                parsed = parsed.replace(year=today.year)
            return parsed.date()
        except ValueError:
            continue
    return None


def doctor_to_dict(doc: Any) -> dict[str, Any]:
    return {
        "id": str(doc.id),
        "full_name": doc.full_name,
        "title": doc.title,
        "bio": (doc.bio or "")[:300],
        "languages": list(doc.languages or []),
        "is_accepting_patients": doc.is_accepting_patients,
        "specialties": [s.name for s in doc.specialties.all()],
        "services": [s.name for s in doc.services.filter(is_deleted=False)],
    }


def build_name_filter(field: str, names: list[str]) -> Q:
    q = Q()
    for name in names:
        q |= Q(**{f"{field}__icontains": name})
    return q


def slot_to_dict(
    start: datetime,
    end: datetime,
    *,
    doctor_name: str,
    doctor_id: str,
) -> dict[str, Any]:
    return {
        "doctor_id": doctor_id,
        "doctor": doctor_name,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "date": start.date().isoformat(),
        "time": start.strftime("%I:%M %p"),
    }
