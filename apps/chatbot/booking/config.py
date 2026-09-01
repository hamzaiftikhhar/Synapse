"""Booking configuration helpers from WidgetSettings."""

from __future__ import annotations

from typing import Any

from apps.clinics.features import VERIFICATION_MODES, get_verification_mode

DEFAULT_BOOKING_CONFIG: dict[str, Any] = {
    # Fallback only — patients pick a path on the PATH step unless doctor/service is prefilled.
    "mode": "service_first",
    "ai_discovery": True,
    "require_auth": True,
    "verification_mode": "email",  # sms | email | sms_or_email | none
    "max_slots_preview": 5,
    "date_horizon_days": 30,
    "slot_hold_minutes": 10,
    "show_reason": True,
    "slot_duration_min": 30,
    # Calendar density thresholds — ratio of remaining/capacity below which a
    # day is "few" (yellow) or "almost_full" (red); above "few" is "plenty" (green).
    "density_thresholds": {"few": 0.5, "almost_full": 0.15},
    # How many days ahead to scan for the PATH step's "Earliest Available" hero
    # slot — intentionally short, not the full booking horizon.
    "hero_horizon_days": 3,
    # Phase 42A — shown on the Review & Confirm step. Deliberately generic
    # and accurate rather than a specific medical/legal claim this system
    # has no way to verify a given clinic actually meets — a clinic can
    # override with its own wording via WidgetSettings.configuration.booking.
    "review_disclaimer": (
        "By confirming, you agree this appointment is subject to the "
        "clinic's cancellation and scheduling policies."
    ),
}

# Upper bound on how far ahead a clinic can be configured to take bookings —
# guards against a mis-entered value turning into a year-long day scan.
MAX_HORIZON_DAYS = 365

VALID_MODES = frozenset(
    {
        "service_first",
        "specialty_first",  # alias of service_first
        "choose_doctor",
        "first_available",
        "general",
    }
)
MODE_ALIASES = {"specialty_first": "service_first"}


def get_booking_config(clinic: Any) -> dict[str, Any]:
    """Merge clinic WidgetSettings.booking with defaults."""
    cfg = dict(DEFAULT_BOOKING_CONFIG)
    try:
        from apps.widget.models import WidgetSettings

        settings = WidgetSettings.objects.filter(clinic=clinic).first()
        if settings and isinstance(settings.configuration, dict):
            booking = settings.configuration.get("booking") or {}
            if isinstance(booking, dict):
                cfg.update(booking)
    except Exception:
        pass

    mode = str(cfg.get("mode", "service_first")).lower().strip()
    if mode not in VALID_MODES:
        mode = "service_first"
    cfg["mode"] = MODE_ALIASES.get(mode, mode)
    cfg["ai_discovery"] = bool(cfg.get("ai_discovery", True))

    vmode = str(cfg.get("verification_mode") or "").lower().strip()
    if vmode not in VERIFICATION_MODES:
        vmode = get_verification_mode(clinic)
    cfg["verification_mode"] = vmode
    # Keep require_auth in sync for older callers
    cfg["require_auth"] = vmode != "none"

    # Coerce against the declared defaults. Spelling the fallbacks a second
    # time is how date_horizon_days ended up advertising 30 days and applying
    # 14 to any clinic that stored a blank value.
    for key in (
        "max_slots_preview",
        "date_horizon_days",
        "slot_hold_minutes",
        "slot_duration_min",
        "hero_horizon_days",
    ):
        try:
            value = int(cfg.get(key) or 0)
        except (TypeError, ValueError):
            value = 0
        cfg[key] = value if value > 0 else int(DEFAULT_BOOKING_CONFIG[key])

    cfg["date_horizon_days"] = min(cfg["date_horizon_days"], MAX_HORIZON_DAYS)
    return cfg


def booking_horizon_days(clinic: Any) -> int:
    """Last day the clinic accepts bookings, as a day offset from today.

    The availability layer enforces this so a question about a month the
    clinic isn't open for yet gets an honest answer instead of whatever the
    date parser happened to fall back to.
    """
    return int(get_booking_config(clinic)["date_horizon_days"])
