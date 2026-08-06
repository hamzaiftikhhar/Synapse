"""Doctor resolution confidence bands and candidate ranking."""

from __future__ import annotations

from django.test import TestCase

from apps.chatbot.nlu.resolvers import (
    confidence_band,
    did_you_mean_doctor_reply,
    resolve_doctor_candidates,
    resolve_doctor_from_text,
)
from apps.clinics.models import Clinic
from apps.doctors.models import Doctor


class DoctorResolutionBandsTests(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="bands-clinic",
            name="Bands Clinic",
            email="bands@clinic.com",
            phone="+12125550000",
            timezone="America/New_York",
        )
        self.thorne = Doctor.objects.create(
            clinic=self.clinic,
            full_name="Dr. Aris Thorne",
            title="DDS",
            is_active=True,
        )
        Doctor.objects.create(
            clinic=self.clinic,
            full_name="Dr. Elena Park",
            title="DDS",
            is_active=True,
        )

    def test_high_confidence_substring(self):
        resolution = resolve_doctor_candidates(self.clinic, "dr aris free monday?")
        self.assertEqual(resolution.confidence_band, "high")
        self.assertEqual(resolution.status, "resolved")
        self.assertEqual(resolution.doctor["id"], str(self.thorne.id))

    def test_medium_confidence_typo_clarify(self):
        resolution = resolve_doctor_candidates(self.clinic, "book dr aris throne")
        self.assertIn(resolution.confidence_band, {"high", "medium"})
        self.assertIsNotNone(resolution.doctor)
        reply = did_you_mean_doctor_reply(resolution)
        if resolution.status == "clarify":
            self.assertIn("Did you mean", reply or "")

    def test_resolve_from_text_uses_candidates(self):
        hit = resolve_doctor_from_text(self.clinic, "is doc aris available")
        self.assertIsNotNone(hit)
        self.assertEqual(hit["id"], str(self.thorne.id))

    def test_confidence_band_thresholds(self):
        self.assertEqual(confidence_band(0.9), "high")
        self.assertEqual(confidence_band(0.7), "medium")
        self.assertEqual(confidence_band(0.5), "low")

    def test_generic_words_do_not_hallucinate_a_doctor(self):
        """Regression: "there" in free text used to fuzzy-collide with the
        surname "Thorne" (Levenshtein ratio 0.667, above the 0.65 clarify
        gate) and produce a spurious "Did you mean Dr. Aris Thorne?" on
        messages that never named a doctor."""
        for message in (
            "is there any doc available tomorrow night?",
            "is there any General Dentistry",
            "any doctor free tomorrow?",
        ):
            resolution = resolve_doctor_candidates(self.clinic, message)
            self.assertEqual(resolution.status, "unknown", message)
            self.assertIsNone(resolution.doctor, message)
