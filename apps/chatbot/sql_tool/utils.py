"""Shared helpers for SQL handlers."""

from __future__ import annotations

import re
import re
from datetime import date, datetime, time, timedelta
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
    if raw in ("next week", "this week"):
        # Start of next ISO week (Monday) or today for this week
        if raw == "this week":
            return today
        days_until_monday = (7 - today.weekday()) % 7 or 7
        return today + timedelta(days=days_until_monday)

    m = re.match(r"^in\s+(\d+)\s+weeks?$", raw)
    if m:
        return today + timedelta(weeks=int(m.group(1)))
    m = re.match(r"^in\s+(\d+)\s+days?$", raw)
    if m:
        return today + timedelta(days=int(m.group(1)))

    day_map = {
        "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
        "friday": 4, "saturday": 5, "sunday": 6,
        "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
    }
    for name, weekday in day_map.items():
        if re.search(rf"\bnext\s+{name}\b", raw):
            days_ahead = (weekday - today.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7
            return today + timedelta(days=days_ahead)
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


_TIME_FLOOR_AFTER_RE = re.compile(r"\bafter\s+(\d{1,2})\s*(am|pm)?\b", re.I)
_AFTER_WORK_RE = re.compile(r"\bafter\s+work\b", re.I)
_ASAP_RE = re.compile(r"\basap\b|\bas\s+soon\s+as\s+possible\b|\bnext\s+available\b", re.I)
_SAME_DAY_RE = re.compile(r"\bsame\s+day\b", re.I)

_TIME_OF_DAY_FLOORS: dict[str, time] = {
    "morning": time(8, 0),
    "afternoon": time(12, 0),
    "evening": time(17, 0),
    "noon": time(12, 0),
    "night": time(19, 0),
}


def parse_time_floor(time_entities: list[str] | None) -> time | None:
    """Interpret already-extracted time-entity strings into a floor time
    (earliest acceptable slot start). Deliberately simple, not a general NLP
    time parser: "after work" -> 17:00; "after N[am/pm]" -> N, with colloquial
    "after 5" (no am/pm) assumed evening (hours 1-7 and 12 -> PM, hours 8-11
    -> AM); morning/afternoon/evening/noon/night -> a sane floor for that
    period.
    """
    for raw in time_entities or []:
        text = (raw or "").strip().lower()
        if not text:
            continue
        if _AFTER_WORK_RE.search(text):
            return time(17, 0)
        match = _TIME_FLOOR_AFTER_RE.search(text)
        if match:
            hour = int(match.group(1))
            meridiem = match.group(2)
            if meridiem == "am":
                hour = hour % 12
            elif meridiem == "pm":
                hour = (hour % 12) + 12
            elif 8 <= hour <= 11:
                pass  # assumed AM
            else:
                hour = (hour % 12) + 12  # assumed PM (covers 1-7 and 12)
            return time(hour % 24, 0)
        if text in _TIME_OF_DAY_FLOORS:
            return _TIME_OF_DAY_FLOORS[text]
    return None


def is_asap_request(text: str) -> bool:
    return bool(_ASAP_RE.search(text or ""))


def is_same_day_request(text: str) -> bool:
    return bool(_SAME_DAY_RE.search(text or ""))


def doctor_to_dict(doc: Any) -> dict[str, Any]:
    return {
        "id": str(doc.id),
        "full_name": doc.full_name,
        "title": doc.title,
        "bio": (doc.bio or "")[:300],
        "photo_url": doc.photo_url or "",
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
