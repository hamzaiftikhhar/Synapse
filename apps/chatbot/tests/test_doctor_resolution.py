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
        self.chandrasekaran = Doctor.objects.create(
            clinic=self.clinic,
            full_name="Dr. Priya Chandrasekaran",
            title="MD",
            is_active=True,
        )
        self.whitaker = Doctor.objects.create(
            clinic=self.clinic,
            full_name="James Whitaker",
            title="PA-C",
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

    def test_honorific_only_does_not_pick_a_doctor(self):
        """'Schedule me with Dr.' names no one. Fuzzy matching on leftover
        verbs like 'schedule' must not resolve to a real roster member."""
        for message in (
            "Schedule me with Dr.",
            "book with a doctor",
            "I want to see a doctor please",
            "can you schedule me with the doctor",
        ):
            with self.subTest(message=message):
                resolution = resolve_doctor_candidates(self.clinic, message)
                self.assertEqual(resolution.status, "unknown", message)
                self.assertIsNone(resolution.doctor, message)

    def test_common_word_mid_string_in_a_surname_does_not_hallucinate_a_doctor(self):
        """Live-confirmed bug (capability-family reliability phase): "I cut
        my hand and need stitches, do you have any doctor for that one"
        produced a spurious "Did you mean Dr. Priya Chandrasekaran?" --
        "hand" is a literal, coincidental mid-string substring of
        "cHANDrasekaran", which the old `n in c or c in n` substring check
        scored at 0.65 (medium/clarify band) purely because "hand" is >=4
        chars, with nothing to do with the doctor's actual name. Restricted
        to a prefix relationship (`startswith`) so only genuine name
        abbreviations/typos (see the priya/priyanka and had/haddad tests
        below) can hit this branch, not any word that happens to appear
        anywhere inside a longer name. A second, never-yet-live instance
        of the same class ("take" mid-string inside "whitAKEr") is also
        covered here."""
        for message in (
            "I cut my hand and need stitches, do you have any doctor for that one",
            "can you take my insurance and book an appointment",
        ):
            with self.subTest(message=message):
                resolution = resolve_doctor_candidates(self.clinic, message)
                self.assertEqual(resolution.status, "unknown", message)
                self.assertIsNone(resolution.doctor, message)

    def test_genuine_name_prefix_typo_still_surfaces_a_clarify(self):
        """Must not be a casualty of the mid-string-substring fix above --
        a real prefix/typo of an actual doctor's surname ("priyanka" for
        "Chandrasekaran"'s first name "Priya") is exactly the case this
        branch exists for and must still surface a "did you mean"."""
        resolution = resolve_doctor_candidates(self.clinic, "what about dr priyanka")
        self.assertEqual(resolution.status, "clarify")
        self.assertEqual(resolution.confidence_band, "medium")
        self.assertEqual(
            resolution.candidates[0].doctor["id"], str(self.chandrasekaran.id)
        )

    def test_named_doctor_still_resolves_in_booking_talk(self):
        for message in (
            "Schedule me with Dr Thorne",
            "could you get me in with Aris this week",
            "is doc aris free monday",
        ):
            with self.subTest(message=message):
                resolution = resolve_doctor_candidates(self.clinic, message)
                self.assertEqual(resolution.status, "resolved", message)
                self.assertEqual(resolution.doctor["id"], str(self.thorne.id), message)
