"""patient_service dedup primitives — get_or_create_by_email mirrors
get_or_create_by_phone (ROADMAP.md's persistent-chat-history phase, Step 3:
added so booking/service.py's confirm() and the widget's /chat/contact
endpoint share one dedup path instead of each doing their own raw lookup)."""

from __future__ import annotations

from django.test import TestCase

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
