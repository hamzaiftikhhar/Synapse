"""Tests for apps.chatbot.ui_actions — deterministic UI-action handlers.

These bypass NLU/LLM entirely (see ui_actions.py's module docstring), so
tests call the module directly rather than through ChatEngine — routing
through ChatEngine would require mocking away the very NLU/LLM call this
module exists to avoid, which would test the mock, not the code.
"""

from __future__ import annotations

from unittest.mock import patch

from apps.chatbot.tests.test_sql_tool import SQLToolTestBase
from apps.chatbot.ui_actions import browse_doctors, clinic_hours_info, search_doctors_for_specialty
from apps.specialties.models import Specialty


class SearchDoctorsForSpecialtyTests(SQLToolTestBase):
    """SQLToolTestBase already gives us a real clinic with a Cardiology
    specialty linked to one doctor, and a General Practice specialty with
    none — exactly the found/no-match fixtures this needs, reused as-is."""

    def test_exact_match_returns_the_real_doctor(self):
        out = search_doctors_for_specialty(self.clinic, str(self.cardio.id))
        self.assertEqual(out["state"], "FOUND_MATCHES")
        doctors = out["meta"]["doctors"]
        self.assertEqual(len(doctors), 1)
        self.assertEqual(doctors[0]["name"], self.doctor.full_name)
        self.assertIn(self.doctor.full_name, out["response"])

    def test_specialty_with_no_doctors_is_an_honest_no_match(self):
        general = Specialty.objects.get(clinic=self.clinic, name="General Practice")
        out = search_doctors_for_specialty(self.clinic, str(general.id))
        self.assertEqual(out["state"], "NO_DIRECT_MATCH")
        self.assertIn("General Practice", out["response"])
        # Must never substitute an unrelated doctor/specialty just because
        # one happens to exist at the clinic (the discovery.py bug this
        # phase fixed).
        self.assertNotIn(self.doctor.full_name, out["response"])
        self.assertEqual(out["meta"].get("actions"), [])
        self.assertNotIn("doctors", out["meta"])

    def test_unknown_specialty_id_is_not_supported(self):
        out = search_doctors_for_specialty(
            self.clinic, "00000000-0000-0000-0000-000000000000"
        )
        self.assertEqual(out["state"], "NOT_SUPPORTED")

    def test_specialty_id_from_a_different_clinic_is_not_supported(self):
        from apps.clinics.models import Clinic

        other_clinic = Clinic.objects.create(
            slug="ui-actions-other-clinic",
            name="Other Clinic",
            email="other@clinic.com",
            phone="+12125550001",
            address={"street": "2 Main St", "city": "Boston", "state": "MA", "zip": "02101"},
            timezone="America/New_York",
        )
        other_specialty = Specialty.objects.create(
            clinic=other_clinic, name="Neurology", slug="neurology"
        )
        # Requesting *this* clinic's search with a specialty id that only
        # exists on a different clinic must not leak cross-tenant data.
        out = search_doctors_for_specialty(self.clinic, str(other_specialty.id))
        self.assertEqual(out["state"], "NOT_SUPPORTED")

    def test_never_calls_the_llm_or_nlu_classifier(self):
        """The whole point of this module is a zero-NLU, zero-LLM path --
        prove it by making the classifier explode and confirming it's
        never reached."""
        with patch(
            "apps.chatbot.nlu.intent_entity.IntentEntityService.analyze",
            side_effect=AssertionError("NLU/LLM must not be called for a UI action"),
        ):
            out = search_doctors_for_specialty(self.clinic, str(self.cardio.id))
        self.assertEqual(out["state"], "FOUND_MATCHES")


class BrowseDoctorsTests(SQLToolTestBase):
    """Backs the "Find a Doctor" main-menu button and its contextual
    follow-up chip — both frontend/backend-authored labels, never the
    patient's own words."""

    def test_returns_the_full_roster(self):
        out = browse_doctors(self.clinic)
        self.assertEqual(out["state"], "FOUND_MATCHES")
        self.assertEqual(len(out["meta"]["doctors"]), 1)
        self.assertEqual(out["meta"]["doctors"][0]["name"], self.doctor.full_name)

    def test_never_calls_the_llm_or_nlu_classifier(self):
        with patch(
            "apps.chatbot.nlu.intent_entity.IntentEntityService.analyze",
            side_effect=AssertionError("NLU/LLM must not be called for a UI action"),
        ):
            out = browse_doctors(self.clinic)
        self.assertEqual(out["state"], "FOUND_MATCHES")


class ClinicHoursInfoTests(SQLToolTestBase):
    """Backs the "Clinic Hours" main-menu button."""

    def test_returns_configured_hours(self):
        out = clinic_hours_info(self.clinic)
        self.assertEqual(out["state"], "FOUND_MATCHES")
        self.assertIn("open", out["response"].lower())

    def test_never_calls_the_llm_or_nlu_classifier(self):
        with patch(
            "apps.chatbot.nlu.intent_entity.IntentEntityService.analyze",
            side_effect=AssertionError("NLU/LLM must not be called for a UI action"),
        ):
            out = clinic_hours_info(self.clinic)
        self.assertEqual(out["state"], "FOUND_MATCHES")
