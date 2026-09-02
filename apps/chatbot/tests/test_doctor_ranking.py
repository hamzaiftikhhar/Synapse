"""Phase 46 — is_doctor_ranking_request() generalization.

No dedicated test of this signal existed before this phase — every prior
test that touched "doctor_ranking_request" set it as a precomputed fact
directly on the planner, never exercising the detector function itself.
"""

from __future__ import annotations

from django.test import TestCase

from apps.chatbot.routing.signals import is_doctor_ranking_request
from apps.clinics.models import Clinic
from apps.doctors.models import Doctor, DoctorSpecialty
from apps.specialties.models import Specialty


class NoClinicRankingTests(TestCase):
    """The default, I/O-free path — used by planner.py's
    compute_message_sensors, shared verbatim with the offline eval battery
    (which has no live clinic/DB at all). Must never regress and must
    never gain new catalog-dependent behavior here."""

    def test_literal_doctor_phrases_recognized(self):
        for msg in (
            "who is the best doctor",
            "who is the top doctor",
            "who is the best doctor for me",
            "which doctor is the best",
            "which doctor is the worst",
        ):
            with self.subTest(msg=msg):
                self.assertTrue(is_doctor_ranking_request(msg))

    def test_legacy_odd_idioms_still_recognized(self):
        for msg in ("best and worst", "rank the doctors", "elite type treatment"):
            with self.subTest(msg=msg):
                self.assertTrue(is_doctor_ranking_request(msg))

    def test_previously_broken_doctor_templates_now_fixed(self):
        """Pre-existing gaps found during Phase 46 investigation, not
        related to specialty generalization — "which doctor is best"
        (missing "the") and "recommended doctor" (no template existed at
        all) both incorrectly returned False before this phase."""
        for msg in ("which doctor is best", "do you have a recommended doctor"):
            with self.subTest(msg=msg):
                self.assertTrue(is_doctor_ranking_request(msg))

    def test_specialty_terminology_not_recognized_without_clinic(self):
        """By design: without a clinic to verify against, a role-noun
        candidate is never trusted, specifically to avoid a false positive
        on an unrelated "-ist"/"-ian" word (see test_generic_role_noun_
        without_clinic_never_matches below)."""
        for msg in (
            "who is the best cardiologist",
            "who is the top pediatrician",
            "which cardiologist is best",
            "do you have a recommended pediatrician",
        ):
            with self.subTest(msg=msg):
                self.assertFalse(is_doctor_ranking_request(msg))

    def test_non_ranking_queries_not_flagged(self):
        for msg in (
            "who are your cardiologists",
            "do you have pediatricians",
            "show me your doctors",
            "which doctors work here",
            "who treats diabetes",
        ):
            with self.subTest(msg=msg):
                self.assertFalse(is_doctor_ranking_request(msg))

    def test_generic_role_noun_without_clinic_never_matches(self):
        """The morphological "-ist"/"-ian" pattern alone is not sufficient
        — without catalog confirmation it must never fire, precisely to
        avoid misclassifying an unrelated word (artist, guardian) as a
        provider-ranking request."""
        for msg in ("who is the best artist", "who is the best guardian for my child"):
            with self.subTest(msg=msg):
                self.assertFalse(is_doctor_ranking_request(msg))


class ClinicGroundedRankingTests(TestCase):
    """The catalog-grounded path — clinic passed explicitly (Tier 1's
    case). Generalizes to any specialty via the existing specialty
    resolver, never a hardcoded specialty/doctor name list."""

    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="ranking-test-clinic",
            name="Ranking Test Clinic",
            email="r@t.com",
            phone="+12125550000",
            address={"street": "1 Main St", "city": "Boston", "state": "MA", "zip": "02101"},
            timezone="America/New_York",
        )
        self.cardiology = Specialty.objects.create(
            clinic=self.clinic, name="Cardiology", slug="cardiology"
        )
        self.pediatrics = Specialty.objects.create(
            clinic=self.clinic, name="Pediatrics", slug="pediatrics"
        )
        doc = Doctor.objects.create(
            clinic=self.clinic, full_name="Dr. Test", title="MD", is_active=True
        )
        DoctorSpecialty.objects.create(clinic=self.clinic, doctor=doc, specialty=self.cardiology)

    def test_specialty_terminology_recognized_with_clinic(self):
        for msg in (
            "who is the best cardiologist",
            "who is the top pediatrician",
            "which cardiologist is best",
            "do you have a recommended pediatrician",
        ):
            with self.subTest(msg=msg):
                self.assertTrue(is_doctor_ranking_request(msg, clinic=self.clinic))

    def test_literal_doctor_phrases_still_recognized_with_clinic(self):
        self.assertTrue(is_doctor_ranking_request("who is the best doctor", clinic=self.clinic))

    def test_generic_word_specialist_does_not_resolve_to_any_real_specialty(self):
        """"specialist" is intentionally generic — it cannot catalog-resolve
        to one specific specialty, so it correctly does not trigger. This
        is a deliberate consequence of requiring catalog grounding, not a
        bug: there is no clinic anywhere with a specialty literally named
        "Specialist"."""
        self.assertFalse(is_doctor_ranking_request("who is the best specialist", clinic=self.clinic))

    def test_non_ranking_queries_still_not_flagged_with_clinic(self):
        for msg in (
            "who are your cardiologists",
            "do you have pediatricians",
            "show me your doctors",
            "which doctors work here",
            "who treats diabetes",
        ):
            with self.subTest(msg=msg):
                self.assertFalse(is_doctor_ranking_request(msg, clinic=self.clinic))

    def test_unrelated_word_still_never_matches_even_with_clinic(self):
        """Catalog grounding must reject "artist"/"guardian" even when a
        clinic is available — they are not specialty names, and
        _match_specialty's alias table has no entry that would resolve
        them to anything real."""
        for msg in ("who is the best artist", "who is the best guardian for my child"):
            with self.subTest(msg=msg):
                self.assertFalse(is_doctor_ranking_request(msg, clinic=self.clinic))

    def test_generalizes_to_a_specialty_never_seen_elsewhere_in_this_session(self):
        """Proves genericity rather than re-confirming cardiology/
        pediatrics (already used throughout this session's fixtures) —
        Dermatology appears nowhere else."""
        Specialty.objects.create(clinic=self.clinic, name="Dermatology", slug="dermatology")
        self.assertTrue(
            is_doctor_ranking_request("who is the best dermatologist", clinic=self.clinic)
        )

    def test_compound_connective_still_recognized_by_the_bare_function(self):
        """is_doctor_ranking_request() itself has never been compound-aware
        (true before this phase too — "best doctor and what are your
        hours" already returned True). Compound protection for Tier 1
        lives one level up, in try_catalog_fast_path's looks_like_compound
        gate, which runs before this function is ever reached — verified
        separately in test_tier1.py. This test documents the bare
        function's actual (unchanged) scope so that fact isn't assumed."""
        self.assertTrue(
            is_doctor_ranking_request(
                "who is the best cardiologist and do you accept Aetna", clinic=self.clinic
            )
        )
