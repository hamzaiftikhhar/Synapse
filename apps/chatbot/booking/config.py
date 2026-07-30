"""Booking configuration helpers from WidgetSettings."""

from __future__ import annotations

from typing import Any

DEFAULT_BOOKING_CONFIG: dict[str, Any] = {
    "mode": "specialty_first",
    "ai_discovery": True,
    "require_auth": True,
    "max_slots_preview": 5,
    "date_horizon_days": 14,
    "slot_hold_minutes": 10,
    "show_reason": True,
    "slot_duration_min": 30,
}

VALID_MODES = frozenset(
    {"specialty_first", "choose_doctor", "first_available", "general"}
)


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

    mode = str(cfg.get("mode", "specialty_first")).lower().strip()
    if mode not in VALID_MODES:
        mode = "specialty_first"
    cfg["mode"] = mode
    cfg["ai_discovery"] = bool(cfg.get("ai_discovery", True))
    cfg["require_auth"] = bool(cfg.get("require_auth", True))
    cfg["max_slots_preview"] = int(cfg.get("max_slots_preview") or 5)
    cfg["date_horizon_days"] = int(cfg.get("date_horizon_days") or 14)
    cfg["slot_hold_minutes"] = int(cfg.get("slot_hold_minutes") or 10)
    cfg["slot_duration_min"] = int(cfg.get("slot_duration_min") or 30)
    return cfg
