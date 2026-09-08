"""Two independent, deliberate product decisions layered on top of each
other here — neither is a bug:

1. New-booking OTP is off by default (`verification_mode` defaults to
   "none" — see `apps.chatbot.booking.config.DEFAULT_BOOKING_CONFIG` and
   `apps.clinics.features.default_widget_configuration`'s matching
   comments). A new booking only needs identification (name + mandatory
   phone, optional email); OTP is reserved for accessing/modifying an
   *existing* appointment, a separate, always-phone-verified code path
   (`otp_service.send_otp`'s `require_existing_patient=True`) this
   setting never governs. A clinic can still opt back into requiring OTP
   for new bookings too, via `email`/`sms`/`sms_or_email`.
2. Even when a clinic *does* opt in, SMS/phone verification specifically
   is disabled for now — kept fully working in the code for a later
   re-enable per clinic, but off by default. `sms_otp`
   (apps.clinics.features.DEFAULT_FEATURE_FLAGS) is the single
   enforcement point: `resolve_otp_channel` consults it before ever
   returning "sms", regardless of a clinic's `verification_mode` setting.
"""

from __future__ import annotations

from django.test import TestCase, override_settings

from apps.chatbot.services.otp_service import OTPError, resolve_otp_channel, send_otp
from apps.clinics.features import get_verification_mode
from apps.clinics.models import Clinic
from apps.widget.models import WidgetSettings


class DefaultVerificationModeTests(TestCase):
    def test_clinic_with_no_widget_settings_defaults_to_none(self):
        clinic = Clinic.objects.create(
            slug="no-settings-clinic", name="No Settings Clinic",
            email="no-settings@clinic.com", phone="+12125550960",
            timezone="America/New_York",
        )
        self.assertEqual(get_verification_mode(clinic), "none")

    def test_clinic_with_empty_booking_config_defaults_to_none(self):
        clinic = Clinic.objects.create(
            slug="empty-booking-clinic", name="Empty Booking Clinic",
            email="empty-booking@clinic.com", phone="+12125550961",
            timezone="America/New_York",
        )
        WidgetSettings.objects.create(clinic=clinic, configuration={"booking": {}})
        self.assertEqual(get_verification_mode(clinic), "none")

    def test_a_clinic_can_still_opt_into_requiring_email_otp_for_booking(self):
        """Proves this is a flip-able default, not code that's actually
        been removed — a clinic that wants stronger identification at
        booking time can still ask for it."""
        clinic = Clinic.objects.create(
            slug="opts-into-email-clinic", name="Opts Into Email Clinic",
            email="opts-into-email@clinic.com", phone="+12125550964",
            timezone="America/New_York",
        )
        WidgetSettings.objects.create(
            clinic=clinic, configuration={"booking": {"verification_mode": "email"}}
        )
        self.assertEqual(get_verification_mode(clinic), "email")


class ResolveOtpChannelTests(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="sms-disabled-clinic", name="SMS Disabled Clinic",
            email="sms-disabled@clinic.com", phone="+12125550962",
            timezone="America/New_York",
        )

    def test_no_config_at_all_raises_verification_disabled(self):
        """The new platform default -- no config means no OTP channel at
        all, matching BookingService's own "none" branch (skip straight
        to review, no send_otp call reaches this function in practice)."""
        with self.assertRaises(OTPError) as ctx:
            resolve_otp_channel(self.clinic, "sms")
        self.assertIn("disabled", str(ctx.exception).lower())

    def test_sms_request_falls_back_to_email_when_clinic_opts_into_email_mode(self):
        # Graceful, not an error: a clinic explicitly in "email" mode
        # treats an sms request the same as no request at all when
        # sms_otp is off.
        WidgetSettings.objects.create(
            clinic=self.clinic,
            configuration={"booking": {"verification_mode": "email"}},
        )
        self.assertEqual(resolve_otp_channel(self.clinic, "sms"), "email")

    def test_no_explicit_request_resolves_to_email_when_clinic_opts_in(self):
        WidgetSettings.objects.create(
            clinic=self.clinic,
            configuration={"booking": {"verification_mode": "email"}},
        )
        self.assertEqual(resolve_otp_channel(self.clinic, None), "email")

    def test_email_request_still_works_when_clinic_opts_in(self):
        WidgetSettings.objects.create(
            clinic=self.clinic,
            configuration={"booking": {"verification_mode": "email"}},
        )
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
class SendOtpNoConfigTests(TestCase):
    """The new platform default: a clinic with no explicit booking config
    doesn't offer new-booking OTP at all. In practice BookingService's own
    "none" branch (submit_details) never calls send_otp for such a clinic
    at all — it routes straight to REVIEW — but send_otp is a shared
    primitive other callers could still reach directly, so it must fail
    honestly rather than silently pick a channel nobody configured."""

    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="send-otp-no-config-clinic", name="Send OTP No Config Clinic",
            email="send-otp-no-config@clinic.com", phone="+12125550963",
            timezone="America/New_York",
        )

    def test_phone_only_request_raises_verification_disabled(self):
        with self.assertRaises(OTPError) as ctx:
            send_otp(clinic=self.clinic, phone="+15559990000", session_token=None)
        self.assertIn("disabled", str(ctx.exception).lower())


@override_settings(DEBUG=True)
class SendOtpEmailOptInTests(TestCase):
    """A clinic that has explicitly opted into requiring OTP for new
    bookings (verification_mode="email") — the machinery a clinic can
    still turn on, even though it's off by default now."""

    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="send-otp-email-only-clinic", name="Send OTP Email Only Clinic",
            email="send-otp-email-only@clinic.com", phone="+12125550963",
            timezone="America/New_York",
        )
        WidgetSettings.objects.create(
            clinic=self.clinic,
            configuration={"booking": {"verification_mode": "email"}},
        )

    def test_phone_only_request_falls_back_to_sms_when_email_is_unavailable(self):
        """A patient who only gave a phone number must still succeed, not
        dead-end on "email required" purely because the clinic's own
        configured channel preference (email) was never available for
        this patient. Still honors that preference whenever a real choice
        exists (see the next test): this only overrides it when email is
        genuinely absent."""
        result = send_otp(
            clinic=self.clinic, phone="+15559990000", session_token=None,
        )
        self.assertEqual(result.channel, "sms")
        self.assertIsNotNone(result.debug_code)

    def test_both_contacts_given_still_honors_clinic_preference(self):
        """The override above is scoped to "email is genuinely absent" --
        when a patient gives both, the clinic's configured
        verification_mode (email) still wins, unchanged."""
        result = send_otp(
            clinic=self.clinic, phone="+15559990000", email="patient@example.com",
            session_token=None,
        )
        self.assertEqual(result.channel, "email")

    def test_email_only_request_succeeds(self):
        result = send_otp(
            clinic=self.clinic, email="patient@example.com", session_token=None,
        )
        self.assertEqual(result.channel, "email")
        self.assertIsNotNone(result.debug_code)
