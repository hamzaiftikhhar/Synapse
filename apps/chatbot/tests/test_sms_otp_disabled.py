"""SMS/phone verification is disabled for now (a deliberate product
decision, not a bug) — kept fully working in the code for a later re-enable
per clinic, but off by default everywhere. `sms_otp` (apps.clinics.features
.DEFAULT_FEATURE_FLAGS) is the single enforcement point: resolve_otp_channel
consults it before ever returning "sms", regardless of a clinic's
verification_mode setting.
"""

from __future__ import annotations

from django.test import TestCase, override_settings

from apps.chatbot.services.otp_service import OTPError, resolve_otp_channel, send_otp
from apps.clinics.features import get_verification_mode
from apps.clinics.models import Clinic
from apps.widget.models import WidgetSettings


class DefaultVerificationModeTests(TestCase):
    def test_clinic_with_no_widget_settings_defaults_to_email(self):
        clinic = Clinic.objects.create(
            slug="no-settings-clinic", name="No Settings Clinic",
            email="no-settings@clinic.com", phone="+12125550960",
            timezone="America/New_York",
        )
        self.assertEqual(get_verification_mode(clinic), "email")

    def test_clinic_with_empty_booking_config_defaults_to_email(self):
        clinic = Clinic.objects.create(
            slug="empty-booking-clinic", name="Empty Booking Clinic",
            email="empty-booking@clinic.com", phone="+12125550961",
            timezone="America/New_York",
        )
        WidgetSettings.objects.create(clinic=clinic, configuration={"booking": {}})
        self.assertEqual(get_verification_mode(clinic), "email")


class ResolveOtpChannelTests(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="sms-disabled-clinic", name="SMS Disabled Clinic",
            email="sms-disabled@clinic.com", phone="+12125550962",
            timezone="America/New_York",
        )

    def test_sms_request_falls_back_to_email_under_the_default_email_mode(self):
        # Graceful, not an error: mode=="email" (the new default) treats an
        # sms request the same as no request at all when sms_otp is off.
        self.assertEqual(resolve_otp_channel(self.clinic, "sms"), "email")

    def test_no_explicit_request_resolves_to_email(self):
        self.assertEqual(resolve_otp_channel(self.clinic, None), "email")

    def test_email_request_still_works(self):
        self.assertEqual(resolve_otp_channel(self.clinic, "email"), "email")

    def test_sms_request_is_rejected_when_a_clinic_is_explicitly_in_sms_mode(self):
        """A clinic that still has verification_mode="sms" explicitly
        stored (pre-existing data, nothing in the UI writes this anymore)
        must not silently start sending real SMS again — sms_otp=False
        blocks it outright rather than falling back."""
        WidgetSettings.objects.create(
            clinic=self.clinic,
            configuration={"booking": {"verification_mode": "sms"}},
        )
        with self.assertRaises(OTPError) as ctx:
            resolve_otp_channel(self.clinic, "sms")
        self.assertIn("SMS verification is disabled", str(ctx.exception))

    def test_a_clinic_that_explicitly_re_enables_sms_otp_can_still_use_it(self):
        """Proves this is a flip-able default, not code that's actually
        been removed — the whole point of disabling rather than deleting."""
        WidgetSettings.objects.create(
            clinic=self.clinic,
            configuration={
                "booking": {"verification_mode": "sms"},
                "feature_flags": {"sms_otp": True},
            },
        )
        self.assertEqual(resolve_otp_channel(self.clinic, "sms"), "sms")

    def test_stale_stored_sms_verification_mode_still_resolves_email_when_only_email_is_sent(self):
        """A clinic whose WidgetSettings row still has verification_mode=
        "sms" from before this change (no frontend surface offers phone
        anymore, so nothing will ever request "sms" again) must still
        work — resolve_otp_channel honors the actual request over the
        stored mode."""
        WidgetSettings.objects.create(
            clinic=self.clinic,
            configuration={"booking": {"verification_mode": "sms"}},
        )
        self.assertEqual(resolve_otp_channel(self.clinic, "email"), "email")


@override_settings(DEBUG=True)
class SendOtpEmailOnlyTests(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="send-otp-email-only-clinic", name="Send OTP Email Only Clinic",
            email="send-otp-email-only@clinic.com", phone="+12125550963",
            timezone="America/New_York",
        )

    def test_phone_only_request_with_no_clinic_override_is_rejected(self):
        """Nothing in the current UI can produce this (DetailsStep and
        VerifyIdentity only ever collect email now), but the backend must
        still fail closed rather than silently texting someone."""
        with self.assertRaises(OTPError) as ctx:
            send_otp(
                clinic=self.clinic, phone="+15559990000",
                session_token=None,
            )
        self.assertIn("Email is required", str(ctx.exception))

    def test_email_only_request_succeeds(self):
        result = send_otp(
            clinic=self.clinic, email="patient@example.com", session_token=None,
        )
        self.assertEqual(result.channel, "email")
        self.assertIsNotNone(result.debug_code)
