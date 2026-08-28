"""patient_service dedup primitives — get_or_create_by_email mirrors
get_or_create_by_phone (ROADMAP.md's persistent-chat-history phase, Step 3:
added so booking/service.py's confirm() and the widget's /chat/contact
endpoint share one dedup path instead of each doing their own raw lookup)."""

from __future__ import annotations

from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone

from apps.clinics.models import Clinic
from apps.patients.models import Patient
from apps.patients.services import patient_service


class GetOrCreateByEmailTests(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="patient-service-clinic",
            name="Patient Service Clinic",
            email="patient-service@clinic.com",
            phone="+12125550400",
            timezone="America/Los_Angeles",
        )

    def test_creates_an_unverified_patient_for_a_new_email(self):
        patient, created = patient_service.get_or_create_by_email(
            clinic=self.clinic, email="new@example.com", first_name="Ali", last_name="Test",
        )
        self.assertTrue(created)
        self.assertFalse(patient.is_verified)
        self.assertEqual(patient.email, "new@example.com")
        self.assertEqual(
            patient.phone, patient_service.email_placeholder_phone("new@example.com")
        )

    def test_reuses_an_existing_patient_with_the_same_email_case_insensitively(self):
        existing = Patient.objects.create(
            clinic=self.clinic, phone="+15551230000", email="existing@example.com",
            first_name="Prior", last_name="Patient", is_verified=True,
        )
        patient, created = patient_service.get_or_create_by_email(
            clinic=self.clinic, email="Existing@Example.com",
        )
        self.assertFalse(created)
        self.assertEqual(patient.id, existing.id)
        self.assertEqual(Patient.objects.filter(clinic=self.clinic).count(), 1)

    def test_does_not_overwrite_verification_status_of_an_existing_patient(self):
        existing = Patient.objects.create(
            clinic=self.clinic, phone="+15551230001", email="verified@example.com",
            first_name="V", last_name="P", is_verified=True,
        )
        patient, _created = patient_service.get_or_create_by_email(
            clinic=self.clinic, email="verified@example.com",
        )
        self.assertEqual(patient.id, existing.id)
        self.assertTrue(patient.is_verified)


class VerifyDateOfBirthTests(TestCase):
    """Phase 42A — DOB identity check. Ordering is load-bearing (this runs
    only after OTP proves contact ownership — enforced by callers, not
    this function), so what's tested here is the comparison/lockout logic
    itself: legacy-null patients are never blocked, a mismatch never
    reveals which reason it failed for, and lockout is scoped to
    (clinic, patient) via fields on Patient, independent of any OTP row's
    own attempts counter (which resets on every resend — a gap this must
    not inherit)."""

    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="dob-verify-clinic",
            name="DOB Verify Clinic",
            email="dob@clinic.com",
            phone="+12125550401",
            timezone="America/Los_Angeles",
        )

    def _patient(self, **kwargs) -> Patient:
        defaults = dict(
            clinic=self.clinic, phone="+15559990001", first_name="A", last_name="B",
        )
        defaults.update(kwargs)
        return Patient.objects.create(**defaults)

    def test_legacy_patient_with_no_stored_dob_is_captured_not_compared(self):
        patient = self._patient(date_of_birth=None)
        result = patient_service.verify_date_of_birth(patient, date(1990, 5, 1))
        self.assertTrue(result)
        patient.refresh_from_db()
        self.assertEqual(patient.date_of_birth, date(1990, 5, 1))
        self.assertEqual(patient.dob_check_attempts, 0)

    def test_matching_dob_verifies(self):
        patient = self._patient(date_of_birth=date(1990, 5, 1))
        result = patient_service.verify_date_of_birth(patient, date(1990, 5, 1))
        self.assertTrue(result)

    def test_mismatched_dob_raises_generic_error_never_confirming_the_reason(self):
        patient = self._patient(date_of_birth=date(1990, 5, 1))
        with self.assertRaises(patient_service.IdentityVerificationError) as ctx:
            patient_service.verify_date_of_birth(patient, date(1985, 1, 1))
        message = str(ctx.exception)
        self.assertNotIn("match", message.lower())
        self.assertEqual(ctx.exception.status_code, 401)
        patient.refresh_from_db()
        self.assertEqual(patient.dob_check_attempts, 1)

    def test_lockout_after_max_attempts_scoped_to_this_patient(self):
        patient = self._patient(date_of_birth=date(1990, 5, 1))
        other_patient = self._patient(
            phone="+15559990002", date_of_birth=date(1990, 5, 1)
        )
        for _ in range(patient_service._DOB_MAX_ATTEMPTS):
            with self.assertRaises(patient_service.IdentityVerificationError):
                patient_service.verify_date_of_birth(patient, date(1985, 1, 1))
        patient.refresh_from_db()
        self.assertIsNotNone(patient.dob_check_locked_until)

        # Locked out now, even with the *correct* DOB.
        with self.assertRaises(patient_service.IdentityVerificationError) as ctx:
            patient_service.verify_date_of_birth(patient, date(1990, 5, 1))
        self.assertEqual(ctx.exception.status_code, 429)

        # A different patient's lockout is untouched — scoped correctly.
        self.assertTrue(
            patient_service.verify_date_of_birth(other_patient, date(1990, 5, 1))
        )

    def test_successful_match_resets_a_prior_attempt_count(self):
        patient = self._patient(date_of_birth=date(1990, 5, 1))
        with self.assertRaises(patient_service.IdentityVerificationError):
            patient_service.verify_date_of_birth(patient, date(1985, 1, 1))
        patient.refresh_from_db()
        self.assertEqual(patient.dob_check_attempts, 1)

        patient_service.verify_date_of_birth(patient, date(1990, 5, 1))
        patient.refresh_from_db()
        self.assertEqual(patient.dob_check_attempts, 0)

    def test_lockout_expires_after_the_cooldown_window(self):
        patient = self._patient(
            date_of_birth=date(1990, 5, 1),
            dob_check_attempts=patient_service._DOB_MAX_ATTEMPTS,
            dob_check_locked_until=timezone.now() - timedelta(minutes=1),
        )
        # Cooldown already elapsed — a correct DOB verifies normally.
        self.assertTrue(
            patient_service.verify_date_of_birth(patient, date(1990, 5, 1))
        )
