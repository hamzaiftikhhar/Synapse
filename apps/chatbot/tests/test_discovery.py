"""Tests for booking/discovery.py's specialty-suggestion matching.

Covers the fix for a live-confirmed bug: when nothing in the message
matched the symptom-keyword table, suggest_specialties() silently
substituted "clinic_specs[:limit]" (whichever specialties sorted first)
instead of returning no suggestion — so e.g. "I need a Cardiology and
Vascular doctor" at a clinic with no cardiology specialty got back
unrelated specialties framed as "may help."
"""

from __future__ import annotations

from django.test import TestCase

from apps.chatbot.booking.discovery import suggest_specialties
from apps.chatbot.engine import ChatEngine
from apps.clinics.models import Clinic
from apps.specialties.models import Specialty


class SuggestSpecialtiesNoMatchTests(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="discovery-clinic",
            name="Discovery Clinic",
            email="discovery@clinic.com",
            phone="+12125550002",
            address={"street": "3 Main St", "city": "Boston", "state": "MA", "zip": "02101"},
            timezone="America/New_York",
        )
        # None of these are in _SYMPTOM_MAP's hint lists (which target
        # generic specialty categories like "cardiology"/"neurology"/
        # "primary care", not compound brand-style names) and none of the
        # keywords below appear anywhere in their names.
        self.zzz = Specialty.objects.create(
            clinic=self.clinic, name="Zzyzx Regenerative Medicine", slug="zzyzx"
        )
        Specialty.objects.create(
            clinic=self.clinic, name="Aardvark Sports Recovery", slug="aardvark"
        )

    def test_no_keyword_match_returns_no_suggestions_not_first_in_list(self):
        suggested, guidance = suggest_specialties(
            self.clinic, message="I need a Cardiology and Vascular doctor"
        )
        self.assertEqual(suggested, [])
        self.assertNotIn("Zzyzx", guidance)
        self.assertNotIn("Aardvark", guidance)

    def test_keyword_match_still_works(self):
        migraine_specialty = Specialty.objects.create(
            clinic=self.clinic, name="Neurology", slug="neurology"
        )
        suggested, guidance = suggest_specialties(self.clinic, message="I have a migraine")
        names = [s["name"] for s in suggested]
        self.assertIn(migraine_specialty.name, names)
        self.assertIn(migraine_specialty.name, guidance)


class SoftMedicalReplyHonestFallbackTests(TestCase):
    """Exercises the real ChatEngine._soft_medical_reply method (not a
    mock) end to end against real Specialty rows -- the actual code path
    a patient's message reaches, not just the discovery function alone."""

    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="soft-medical-clinic",
            name="Soft Medical Clinic",
            email="softmed@clinic.com",
            phone="+12125550003",
            address={"street": "4 Main St", "city": "Boston", "state": "MA", "zip": "02101"},
            timezone="America/New_York",
        )
        Specialty.objects.create(
            clinic=self.clinic, name="Zzyzx Regenerative Medicine", slug="zzyzx"
        )

    def test_unmatched_specialty_name_gets_honest_generic_reply(self):
        reply = ChatEngine()._soft_medical_reply(
            self.clinic, "I need a Cardiology and Vascular doctor"
        )
        self.assertNotIn("these areas may help", reply)
        self.assertNotIn("Zzyzx", reply)
        self.assertIn("find a doctor", reply.lower())
