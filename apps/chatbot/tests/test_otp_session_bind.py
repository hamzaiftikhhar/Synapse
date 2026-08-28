"""OTP verify must authenticate the ChatSession even when the client
omits session_token on the verify request (send always mints one)."""

from __future__ import annotations

from datetime import date

from django.test import TestCase, override_settings

from apps.chatbot.models import ChatSession
from apps.chatbot.services.otp_service import OTPError, send_otp, verify_otp
from apps.clinics.models import Clinic
from apps.patients.models import Patient


@override_settings(DEBUG=True)
class OtpSessionBindTests(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="otp-bind-clinic",
            name="OTP Bind Clinic",
            email="otp-bind@clinic.com",
            phone="+12125550999",
            timezone="America/New_York",
        )
        self.patient = Patient.objects.create(
            clinic=self.clinic,
            phone="+15559876543",
            email="otp-bind@example.com",
            first_name="Pat",
            last_name="Ient",
        )

    def test_verify_without_session_token_still_authenticates_otp_session(self):
        sent = send_otp(
            clinic=self.clinic,
            email=self.patient.email,
            channel="email",
            session_token=None,
            require_existing_patient=True,
        )
        self.assertTrue(sent.session_token)
        self.assertIsNotNone(sent.debug_code)

        verified = verify_otp(
            clinic=self.clinic,
            email=self.patient.email,
            code=sent.debug_code,
            session_token=None,  # broken client path
        )

        self.assertIsNotNone(verified.session)
        assert verified.session is not None
        self.assertEqual(verified.session.session_token, sent.session_token)
        self.assertTrue(verified.session.is_authenticated)
        self.assertEqual(verified.session.patient_id, self.patient.id)

        row = ChatSession.objects.get(session_token=sent.session_token)
        self.assertTrue(row.is_authenticated)
        self.assertEqual(row.patient_id, self.patient.id)

    def test_verify_with_matching_session_token_authenticates(self):
        sent = send_otp(
            clinic=self.clinic,
            email=self.patient.email,
            channel="email",
            session_token=None,
            require_existing_patient=True,
        )
        verified = verify_otp(
            clinic=self.clinic,
            email=self.patient.email,
            code=sent.debug_code,
            session_token=sent.session_token,
        )
        self.assertEqual(verified.session.session_token, sent.session_token)
        self.assertTrue(verified.session.is_authenticated)


@override_settings(DEBUG=True)
class OtpDobVerificationTests(TestCase):
    """Phase 42A — DOB check runs inside verify_otp, only ever after the
    code itself is already confirmed correct."""

    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="otp-dob-clinic",
            name="OTP DOB Clinic",
            email="otp-dob@clinic.com",
            phone="+12125550998",
            timezone="America/New_York",
        )
        self.patient = Patient.objects.create(
            clinic=self.clinic,
            phone="+15559876500",
            email="otp-dob@example.com",
            first_name="Pat",
            last_name="Ient",
            date_of_birth=date(1990, 5, 1),
        )

    def _send(self):
        return send_otp(
            clinic=self.clinic,
            email=self.patient.email,
            channel="email",
            session_token=None,
            require_existing_patient=True,
        )

    def test_correct_code_and_matching_dob_verifies_both(self):
        sent = self._send()
        result = verify_otp(
            clinic=self.clinic,
            email=self.patient.email,
            code=sent.debug_code,
            session_token=None,
            date_of_birth=date(1990, 5, 1),
        )
        self.assertTrue(result.dob_verified)
        self.assertTrue(result.session.is_authenticated)

    def test_correct_code_but_wrong_dob_blocks_verification_entirely(self):
        sent = self._send()
        with self.assertRaises(OTPError) as ctx:
            verify_otp(
                clinic=self.clinic,
                email=self.patient.email,
                code=sent.debug_code,
                session_token=None,
                date_of_birth=date(1985, 1, 1),
            )
        self.assertEqual(ctx.exception.status_code, 401)
        # The session was never authenticated — a DOB mismatch blocks the
        # whole verification, same as a wrong code would.
        session = ChatSession.objects.get(session_token=sent.session_token)
        self.assertFalse(session.is_authenticated)

    def test_no_dob_passed_skips_the_check_entirely(self):
        """A clinic that never asks for DOB (or the "none" verification
        mode path, which never calls this at all) must not be silently
        blocked by a check it didn't opt into."""
        sent = self._send()
        result = verify_otp(
            clinic=self.clinic,
            email=self.patient.email,
            code=sent.debug_code,
            session_token=None,
        )
        self.assertFalse(result.dob_verified)
        self.assertTrue(result.session.is_authenticated)
