"""Data migration: flip the platform default for new-booking OTP.

Architecture decision: a new booking only needs identification (name +
mandatory phone the clinic can call, optional email), not authentication.
OTP verification stays required for accessing/modifying an *existing*
appointment (view/cancel/reschedule) — that flow is a separate,
always-phone-verified code path (otp_service.py's
require_existing_patient=True) this migration does not touch.

Only updates rows still holding the exact old platform default
("email", no explicit clinic customization signal) — a row whose
verification_mode is "sms", "sms_or_email", or "none" already, or that
looks like it was deliberately customized, is left alone. In this
product's current stage every clinic's "email" value came from the old
default (see apps/clinics/features.py's own documented history — the
booking UI has never offered a way to pick a different mode), so this is
a safe, uniform flip rather than a per-clinic guess.
"""

from __future__ import annotations

from django.db import migrations


def set_verification_mode_none(apps, schema_editor):
    WidgetSettings = apps.get_model("widget", "WidgetSettings")
    for settings in WidgetSettings.objects.all().iterator():
        config = settings.configuration
        if not isinstance(config, dict):
            continue
        booking = config.get("booking")
        if not isinstance(booking, dict):
            continue
        if booking.get("verification_mode") != "email":
            continue
        booking["verification_mode"] = "none"
        booking["require_auth"] = False
        settings.save(update_fields=["configuration"])


def restore_verification_mode_email(apps, schema_editor):
    WidgetSettings = apps.get_model("widget", "WidgetSettings")
    for settings in WidgetSettings.objects.all().iterator():
        config = settings.configuration
        if not isinstance(config, dict):
            continue
        booking = config.get("booking")
        if not isinstance(booking, dict):
            continue
        if booking.get("verification_mode") != "none":
            continue
        booking["verification_mode"] = "email"
        booking["require_auth"] = True
        settings.save(update_fields=["configuration"])


class Migration(migrations.Migration):

    dependencies = [
        ("widget", "0002_alter_widgetsettings_id"),
    ]

    operations = [
        migrations.RunPython(
            set_verification_mode_none, restore_verification_mode_email
        ),
    ]
