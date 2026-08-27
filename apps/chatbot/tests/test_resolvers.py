"""nlu/resolvers.py: consolidated doctor-name resolution + service->specialty resolution."""

from __future__ import annotations

from django.test import TestCase

from apps.chatbot.nlu.resolvers import (
    resolve_doctor_candidates,
    resolve_doctor_from_text,
    resolve_specialty_for_service,
)
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


class FuzzyMatchShortWordCollisionTests(TestCase):
    """Phase 40: a real, long eHealthForum patient narrative ("...i had
    explained to the dr...") fuzzy-matched the common word "had" against a
    real clinic doctor's surname "Haddad" at 0.725 — a "did you mean Dr.
    Omar Haddad?" prompt on a message that named no doctor at all. Root
    cause: _fuzzy_score's substring-match branch had no minimum length on
    the shorter string, so a 3-letter common word being a literal prefix of
    a much longer surname scored almost as high as a genuine partial name.
    """

    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="haddad-collision-clinic",
            name="Haddad Collision Clinic",
            email="haddad@clinic.com",
            phone="+12125550001",
            timezone="America/New_York",
        )
        self.doctor = Doctor.objects.create(
            clinic=self.clinic,
            full_name="Dr. Omar Haddad",
            title="MD",
            is_active=True,
        )

    def test_long_narrative_with_had_does_not_suggest_haddad(self):
        text = (
            "i have a large hard knot beneath the skin of my left cheek. "
            "the following day i went to an er due to more aggressive "
            "facial swelling. the dr there gave me a cat scan. at this "
            "point i had explained to the dr that none of my teeth were "
            "bothering me in any way. what could be causing this knot"
        )
        resolution = resolve_doctor_candidates(self.clinic, text)
        self.assertNotEqual(resolution.status, "clarify")
        self.assertIsNone(resolve_doctor_from_text(self.clinic, text))

    def test_short_partial_name_still_resolves(self):
        # "Sharma"-style short-but-genuine last names must still work —
        # the fix only excludes matches below the length floor.
        result = resolve_doctor_from_text(self.clinic, "book with dr haddad please")
        self.assertIsNotNone(result)
        self.assertEqual(result["id"], str(self.doctor.id))


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
