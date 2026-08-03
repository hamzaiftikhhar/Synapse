"""Default clinic feature flags + patient verification helpers."""

from __future__ import annotations

from typing import Any

DEFAULT_FEATURE_FLAGS: dict[str, bool] = {
    "ai_chat": True,
    "booking": True,
    "knowledge_base": True,
    "analytics": True,
    "email_otp": True,
    "sms_otp": True,
    "doctor_portal": False,
}

# Patient booking verification
VERIFICATION_MODES = frozenset({"sms", "email", "sms_or_email", "none"})


def default_widget_configuration() -> dict[str, Any]:
    return {
        "widget": {
            "primary_color": "#5b21b6",
            "position": "bottom-right",
            "greeting": "Hi! How can I help you today?",
        },
        "ai": {"model": "default", "temperature": 0.2},
        "booking": {
            "mode": "specialty_first",
            "ai_discovery": True,
            "require_auth": True,
            "verification_mode": "sms",
            "max_slots_preview": 5,
            "date_horizon_days": 14,
            "slot_hold_minutes": 10,
            "slot_duration_min": 30,
        },
        "feature_flags": dict(DEFAULT_FEATURE_FLAGS),
    }


def get_verification_mode(clinic: Any) -> str:
    """Resolve patient verification mode from widget booking config."""
    try:
        from apps.widget.models import WidgetSettings

        settings = WidgetSettings.objects.filter(clinic=clinic).first()
        booking = {}
        if settings and isinstance(settings.configuration, dict):
            booking = settings.configuration.get("booking") or {}
        mode = str(booking.get("verification_mode") or "").lower().strip()
        if mode in VERIFICATION_MODES:
            return mode
        # Legacy boolean
        if "require_auth" in booking:
            return "sms" if booking.get("require_auth") else "none"
    except Exception:
        pass
    return "sms"


def get_feature_flags(clinic: Any) -> dict[str, bool]:
    flags = dict(DEFAULT_FEATURE_FLAGS)
    try:
        from apps.widget.models import WidgetSettings

        settings = WidgetSettings.objects.filter(clinic=clinic).first()
        if settings and isinstance(settings.configuration, dict):
            raw = settings.configuration.get("feature_flags") or {}
            if isinstance(raw, dict):
                for k, v in raw.items():
                    if k in flags:
                        flags[k] = bool(v)
    except Exception:
        pass
    return flags
