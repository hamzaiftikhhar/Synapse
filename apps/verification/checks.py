"""Startup-time configuration validation.

Without this, `OTP_PROVIDER=twilio` with an incomplete credential set would
boot cleanly and only reveal itself the first time a real request tried to
send or check a verification (as a per-request FAILED outcome — a safety
net, not a substitute for surfacing the misconfiguration at deploy time).
Runs automatically on `runserver`, `migrate`, `test`, etc. via Django's
system check framework; has no effect when OTP_PROVIDER is left at its
"mock" default, so it never fires in ordinary local dev.
"""

from __future__ import annotations

from django.core.checks import Error, register

_REQUIRED_TWILIO_SETTINGS = (
    "TWILIO_ACCOUNT_SID",
    "TWILIO_API_KEY",
    "TWILIO_API_SECRET",
    "TWILIO_VERIFY_SERVICE_SID",
)


@register()
def check_twilio_verify_configured(app_configs, **kwargs):
    from django.conf import settings

    if getattr(settings, "OTP_PROVIDER", "mock") != "twilio":
        return []

    missing = [
        name for name in _REQUIRED_TWILIO_SETTINGS if not getattr(settings, name, "")
    ]
    if not missing:
        return []

    return [
        Error(
            "OTP_PROVIDER is set to 'twilio' but required settings are missing: "
            + ", ".join(missing),
            hint=(
                "Set all of TWILIO_ACCOUNT_SID, TWILIO_API_KEY, TWILIO_API_SECRET, "
                "TWILIO_VERIFY_SERVICE_SID, or set OTP_PROVIDER=mock for local "
                "development."
            ),
            id="verification.E001",
        )
    ]
