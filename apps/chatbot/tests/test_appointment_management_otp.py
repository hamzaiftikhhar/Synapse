"""Appointment-management identity verification (view/reschedule/cancel an
existing appointment) — send_otp(require_existing_patient=True).

Two live-flagged gaps, both product-level, not hypothetical:

1. The widget's VerifyIdentity component collected email, not phone — but
   phone is the one field every patient record actually has (required at
   booking; Patient.phone's own field comment: "required for OTP"), while
   email is optional and frequently blank. An email-only management flow
   is unusable for any patient who booked with phone only. Phone is now
   forced for this flow specifically, regardless of the clinic's general
   verification_mode/sms_otp configuration (which still governs the
   separate new-patient booking OTP flow — see test_sms_otp_disabled.py,
   unaffected by this).

2. send_otp(require_existing_patient=True) used to raise a distinct,
   revealing 404 ("we couldn't find a patient with that phone/email") when
   no patient matched — a phone/email enumeration oracle: a caller could
   learn whether a given phone number belongs to a registered patient at
   this clinic purely from the response differing from a real send. Now
   returns the exact same response shape/message regardless of a match,
   and creates no OTPVerification row for a non-match, so a subsequent
   /otp/verify attempt gets the same generic "invalid or expired code"
   either way.
"""

from __future__ import annotations

from django.test import TestCase, override_settings

from apps.chatbot.models import OTPVerification
from apps.chatbot.services.otp_service import OTPError, OTPInvalidError, send_otp, verify_otp
from apps.clinics.models import Clinic
from apps.patients.models import Patient


@override_settings(DEBUG=True)
class ManagementFlowForcesPhoneTests(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="mgmt-otp-clinic", name="Mgmt OTP Clinic",
            email="mgmt-otp@clinic.com", phone="+12125550970",
            timezone="America/New_York",
        )
        self.patient = Patient.objects.create(
            clinic=self.clinic, phone="+15559871111", email="mgmt-otp@example.com",
            first_name="Mo", last_name="Bile",
        )

    def test_phone_works_regardless_of_clinic_verification_mode(self):
        """Clinic's stored config still says "email" (the default) — the
        management flow must force phone anyway."""
        result = send_otp(
            clinic=self.clinic, phone=self.patient.phone,
            session_token=None, require_existing_patient=True,
        )
        self.assertEqual(result.channel, "sms")
        self.assertIsNotNone(result.debug_code)

    def test_email_alone_is_rejected_even_though_the_patient_has_one(self):
        """The whole point: this flow no longer accepts email at all, even
        for a patient who has one on file — phone only."""
        with self.assertRaises(OTPError) as ctx:
            send_otp(
                clinic=self.clinic, email=self.patient.email,
                session_token=None, require_existing_patient=True,
            )
        self.assertIn("Phone is required", str(ctx.exception))

    def test_full_send_and_verify_round_trip_by_phone(self):
        sent = send_otp(
            clinic=self.clinic, phone=self.patient.phone,
            session_token=None, require_existing_patient=True,
        )
        result = verify_otp(
            clinic=self.clinic, phone=self.patient.phone,
            code=sent.debug_code, session_token=sent.session_token,
        )
        self.assertEqual(result.patient.id, self.patient.id)


@override_settings(DEBUG=True)
class NoEnumerationOracleTests(TestCase):
    """A phone number that belongs to no patient at this clinic must be
    indistinguishable, from the response alone, from one that does."""

    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="no-enum-clinic", name="No Enum Clinic",
            email="no-enum@clinic.com", phone="+12125550971",
            timezone="America/New_York",
        )
        self.patient = Patient.objects.create(
            clinic=self.clinic, phone="+15559872222", email="no-enum@example.com",
            first_name="Real", last_name="Patient",
        )

    def test_unknown_phone_gets_the_same_response_shape_as_a_real_one(self):
        real = send_otp(
            clinic=self.clinic, phone=self.patient.phone,
            session_token=None, require_existing_patient=True,
        )
        fake = send_otp(
            clinic=self.clinic, phone="+15559999999",  # no patient has this
            session_token=None, require_existing_patient=True,
        )
        # Same shape, same channel, no exception either way.
        self.assertEqual(real.channel, fake.channel)
        self.assertIsInstance(real.session_token, str)
        self.assertIsInstance(fake.session_token, str)
        # The unmatched case must not carry a usable code.
        self.assertIsNone(fake.debug_code)
        self.assertIsNone(fake.patient)
        self.assertIsNotNone(real.patient)

    def test_unknown_phone_creates_no_otp_verification_row(self):
        before = OTPVerification.objects.count()
        send_otp(
            clinic=self.clinic, phone="+15559999999",
            session_token=None, require_existing_patient=True,
        )
        self.assertEqual(OTPVerification.objects.count(), before)

    def test_verifying_after_an_unmatched_send_fails_generically(self):
        """No enumeration via the verify step either: an unmatched phone's
        "code" (there isn't one) fails exactly like a real wrong code."""
        sent = send_otp(
            clinic=self.clinic, phone="+15559999999",
            session_token=None, require_existing_patient=True,
        )
        with self.assertRaises(OTPInvalidError):
            verify_otp(
                clinic=self.clinic, phone="+15559999999",
                code="000000", session_token=sent.session_token,
            )

