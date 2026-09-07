"""Date-of-birth validation shared by API, model, and chatbot booking."""

from __future__ import annotations

from datetime import date

from django.core.exceptions import ValidationError
from django.utils import timezone

MAX_AGE_YEARS = 120


def validate_date_of_birth(value: date | None, *, required: bool = False) -> date | None:
    """Reject future DOBs and implausibly old dates.

    Returns the value unchanged when valid (including None when not required).
    Raises django.core.exceptions.ValidationError with a patient-facing message.
    """
    if value is None:
        if required:
            raise ValidationError("Date of birth is required", code="required")
        return None

    today = timezone.localdate()
    if value > today:
        raise ValidationError(
            "Date of birth cannot be in the future",
            code="dob_future",
        )
    # today.day is only unsafe for Feb 29 -- year - MAX_AGE_YEARS isn't
    # guaranteed to also be a leap year (the two can disagree exactly at
    # non-leap century boundaries), which would otherwise raise a raw
    # ValueError instead of the intended ValidationError. Falling back to
    # Feb 28 for that one case is a negligible one-day shift on a 120-year
    # boundary.
    try:
        earliest = date(today.year - MAX_AGE_YEARS, today.month, today.day)
    except ValueError:
        earliest = date(today.year - MAX_AGE_YEARS, today.month, today.day - 1)
    if value < earliest:
        raise ValidationError(
            f"Date of birth cannot be more than {MAX_AGE_YEARS} years ago",
            code="dob_too_old",
        )
    return value
