"""nlu/resolvers.py: consolidated doctor-name resolution + service->specialty resolution."""

from __future__ import annotations

from django.test import TestCase

from apps.chatbot.nlu.resolvers import resolve_doctor_from_text, resolve_specialty_for_service
from apps.clinics.models import Clinic
from apps.doctors.models import Doctor, DoctorService, DoctorSpecialty
from apps.services.models import Service
from apps.specialties.models import Specialty


class ResolveDoctorFromTextTests(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="resolver-clinic",
            name="Resolver Clinic",
            email="resolver@clinic.com",
            phone="+12125550000",
            timezone="America/New_York",
        )
        self.doctor = Doctor.objects.create(
            clinic=self.clinic,
            full_name="Dr. Rajat Sharma",
            title="MD",
            is_active=True,
        )

    def test_exact_full_name_match(self):
        result = resolve_doctor_from_text(self.clinic, "Book with Dr. Rajat Sharma please")
        self.assertIsNotNone(result)
        self.assertEqual(result["id"], str(self.doctor.id))

    def test_last_name_match(self):
        result = resolve_doctor_from_text(self.clinic, "Can I see Sharma on Friday?")
        self.assertIsNotNone(result)
        self.assertEqual(result["id"], str(self.doctor.id))

    def test_typo_tolerance_fuzzy_fallback(self):
        result = resolve_doctor_from_text(self.clinic, "book with dr rajet sharme")
        self.assertIsNotNone(result)
        self.assertEqual(result["id"], str(self.doctor.id))

    def test_unrelated_text_does_not_match(self):
        result = resolve_doctor_from_text(self.clinic, "what insurance do you accept")
        self.assertIsNone(result)

    def test_empty_text_returns_none(self):
        self.assertIsNone(resolve_doctor_from_text(self.clinic, ""))
        self.assertIsNone(resolve_doctor_from_text(self.clinic, None))


class ResolveSpecialtyForServiceTests(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="specialty-resolver-clinic",
            name="Specialty Resolver Clinic",
            email="spec@clinic.com",
            phone="+12125550001",
            timezone="America/New_York",
        )
        self.aesthetics = Specialty.objects.create(
            clinic=self.clinic, name="Aesthetics", slug="aesthetics"
        )
        self.dermatology = Specialty.objects.create(
            clinic=self.clinic, name="Dermatology", slug="dermatology"
        )
        self.botox = Service.objects.create(
            clinic=self.clinic, name="Botox", duration_min=30, price_cents=50000
        )

    def test_resolves_via_doctor_specialty_relation(self):
        doctor = Doctor.objects.create(clinic=self.clinic, full_name="Dr. Aesthetic One")
        DoctorSpecialty.objects.create(
            clinic=self.clinic, doctor=doctor, specialty=self.aesthetics
        )
        DoctorService.objects.create(clinic=self.clinic, doctor=doctor, service=self.botox)

        specialty_id = resolve_specialty_for_service(self.clinic, str(self.botox.id))
        self.assertEqual(specialty_id, str(self.aesthetics.id))

    def test_picks_specialty_with_most_doctors_performing_service(self):
        one_aesthetic = Doctor.objects.create(clinic=self.clinic, full_name="Dr. A")
        two_derm = Doctor.objects.create(clinic=self.clinic, full_name="Dr. B")
        three_derm = Doctor.objects.create(clinic=self.clinic, full_name="Dr. C")
        for doc in (one_aesthetic, two_derm, three_derm):
            DoctorService.objects.create(clinic=self.clinic, doctor=doc, service=self.botox)
        DoctorSpecialty.objects.create(
            clinic=self.clinic, doctor=one_aesthetic, specialty=self.aesthetics
        )
        DoctorSpecialty.objects.create(
            clinic=self.clinic, doctor=two_derm, specialty=self.dermatology
        )
        DoctorSpecialty.objects.create(
            clinic=self.clinic, doctor=three_derm, specialty=self.dermatology
        )

        specialty_id = resolve_specialty_for_service(self.clinic, str(self.botox.id))
        self.assertEqual(specialty_id, str(self.dermatology.id))

    def test_no_doctors_performing_service_returns_none(self):
        self.assertIsNone(resolve_specialty_for_service(self.clinic, str(self.botox.id)))

    def test_none_service_id_returns_none(self):
        self.assertIsNone(resolve_specialty_for_service(self.clinic, None))
