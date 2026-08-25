"""Date-range and clinic-local day helpers for clinic analytics."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.utils import timezone
from ninja.errors import HttpError

from apps.clinics.models import Clinic

RANGE_DAYS: dict[str, int] = {
    "7d": 7,
    "30d": 30,
    "90d": 90,
    "6m": 182,
    "12m": 365,
}

VALID_RANGES = tuple(RANGE_DAYS.keys())


def parse_range(raw: str | None) -> tuple[str, int]:
    key = (raw or "30d").strip().lower()
    days = RANGE_DAYS.get(key)
    if days is None:
        raise HttpError(400, "Invalid range. Use 7d, 30d, 90d, 6m, or 12m.")
    return key, days


def parse_year_month(
    clinic: Clinic, year: int | None, month: int | None
) -> tuple[int, int, datetime, datetime, datetime, ZoneInfo]:
    """Clinic-local month window: [month_start, next_month_start)."""
    tz = clinic_zone(clinic)
    now = timezone.now().astimezone(tz)
    try:
        y = int(year) if year is not None else now.year
        m = int(month) if month is not None else now.month
    except (TypeError, ValueError):
        raise HttpError(400, "Invalid year or month.")
    if y < 2000 or y > 2100 or m < 1 or m > 12:
        raise HttpError(400, "Invalid year or month.")
    start = datetime(y, m, 1, tzinfo=tz)
    end = datetime(y + 1, 1, 1, tzinfo=tz) if m == 12 else datetime(y, m + 1, 1, tzinfo=tz)
    return y, m, start, end, now, tz


def clinic_zone(clinic: Clinic) -> ZoneInfo:
    try:
        return ZoneInfo(clinic.timezone or "UTC")
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def window_for(clinic: Clinic, days: int) -> tuple[datetime, datetime, datetime, ZoneInfo]:
    """Return (current_start, now, previous_start, tz). Previous is the same
    length immediately before the current window."""
    tz = clinic_zone(clinic)
    now = timezone.now().astimezone(tz)
    current_start = now - timedelta(days=days)
    previous_start = current_start - timedelta(days=days)
    return current_start, now, previous_start, tz


def change_pct(current: int, previous: int) -> float | None:
    if previous == 0:
        return None if current == 0 else 100.0
    return round((current - previous) / previous * 100.0, 1)


def fill_daily(
    rows: list[dict],
    *,
    start: datetime,
    end: datetime,
    value_keys: tuple[str, ...],
) -> list[dict]:
    by_date = {str(r.get("date") or "")[:10]: r for r in rows}
    out: list[dict] = []
    day = start.date()
    last = end.date()
    while day <= last:
        iso = day.isoformat()
        src = by_date.get(iso, {})
        item = {"date": iso}
        for key in value_keys:
            item[key] = int(src.get(key) or 0)
        out.append(item)
        day += timedelta(days=1)
    return out
