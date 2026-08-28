"""Phase 41 — doctor-pronoun resolution, ambiguity handling, gender
questions, and the multi-doctor-resolution-collapse fix, at the engine
level (NLU mocked, matching test_recovery_override.py's shape)."""

from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase

from apps.chatbot.conversation_state import ConversationTimeline
from apps.chatbot.engine import ChatEngine
from apps.chatbot.nlu.schemas import ExtractedEntities, Intent, NLUResult, ResolvedIds
from apps.clinics.models import Clinic
from apps.doctors.models import Doctor, DoctorService
from apps.services.models import Service


class DoctorContextResolutionTests(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="context-resolution-clinic",
            name="Context Resolution Clinic",
            email="context@clinic.com",
            phone="+12125550200",
            address={"street": "3 Main", "city": "Boston", "state": "MA", "zip": "02101"},
            timezone="America/New_York",
        )
        self.pediatric_service = Service.objects.create(
            clinic=self.clinic, name="Pediatric Well-Child Exam"
        )
        self.priya = Doctor.objects.create(
            clinic=self.clinic, full_name="Dr. Priya Chandrasekaran", is_accepting_patients=True
        )
        self.omar = Doctor.objects.create(
            clinic=self.clinic, full_name="Dr. Omar Haddad", is_accepting_patients=True
        )
        self.james = Doctor.objects.create(
            clinic=self.clinic, full_name="James Whitaker", is_accepting_patients=True
        )
        DoctorService.objects.create(
            clinic=self.clinic, doctor=self.priya, service=self.pediatric_service
        )
        DoctorService.objects.create(
            clinic=self.clinic, doctor=self.omar, service=self.pediatric_service
        )
        # James deliberately has no pediatric service.

    def _fake_nlu(self, **kwargs) -> NLUResult:
        return NLUResult(
            intent=kwargs.get("intent", Intent.OFF_TOPIC),
            confidence=kwargs.get("confidence", 0.5),
            entities=kwargs.get("entities", ExtractedEntities()),
            resolved_ids=kwargs.get("resolved_ids", ResolvedIds()),
            needs_sql=kwargs.get("needs_sql", False),
            is_off_topic=kwargs.get("is_off_topic", False),
        )

    def _ctx_with_shown(self, doctors: list[Doctor]) -> dict:
        tl = ConversationTimeline(
            shown_doctors=[{"id": str(d.id), "name": d.full_name} for d in doctors]
        )
        return {"timeline": tl.to_dict()}

    @patch("apps.chatbot.nlu.intent_entity.IntentEntityService.analyze")
    def test_single_shown_doctor_resolves_pronoun(self, mock_analyze):
        """"Can she see children?" after Priya alone was shown — even when
        NLU itself misclassifies the message, the pronoun resolver must
        still route it to Priya specifically."""
        mock_analyze.return_value = self._fake_nlu(intent=Intent.OFF_TOPIC, confidence=0.2)
        result = ChatEngine().process(
            clinic=self.clinic,
            message="Can she see children?",
            session=None,
            conversation_context=self._ctx_with_shown([self.priya]),
        )
        names = {
            r.get("full_name")
            for block in result.sql_results
            for r in block.get("rows", [])
        }
        self.assertEqual(names, {"Dr. Priya Chandrasekaran"})

    @patch("apps.chatbot.nlu.intent_entity.IntentEntityService.analyze")
    def test_ambiguous_shown_doctors_asks_which(self, mock_analyze):
        """"Can she see children?" after Priya AND Omar were both shown
        must ask which doctor, never guess or dump the full list."""
        mock_analyze.return_value = self._fake_nlu(intent=Intent.OFF_TOPIC, confidence=0.2)
        result = ChatEngine().process(
            clinic=self.clinic,
            message="Can she see children?",
            session=None,
            conversation_context=self._ctx_with_shown([self.priya, self.omar]),
        )
        self.assertIn("Dr. Priya Chandrasekaran", result.response)
        self.assertIn("Dr. Omar Haddad", result.response)
        self.assertEqual(result.sql_results, [])

    @patch("apps.chatbot.nlu.intent_entity.IntentEntityService.analyze")
    def test_family_relation_does_not_hijack_pronoun(self, mock_analyze):
        """"My daughter has a fever, can she see a doctor?" must not
        resolve "she" to a previously-shown doctor — she's the daughter."""
        mock_analyze.return_value = self._fake_nlu(
            intent=Intent.DOCTOR_SEARCH,
            confidence=0.7,
            entities=ExtractedEntities(symptom="fever"),
            needs_sql=True,
        )
        result = ChatEngine().process(
            clinic=self.clinic,
            message="My daughter has a fever, can she see a doctor?",
            session=None,
            conversation_context=self._ctx_with_shown([self.priya]),
        )
        # Falls through to the ordinary (unfiltered-by-pronoun) doctor
        # search — not silently narrowed to only Priya via "she".
        names = {
            r.get("full_name")
            for block in result.sql_results
            for r in block.get("rows", [])
        }
        self.assertIn("James Whitaker", names)

    @patch("apps.chatbot.nlu.intent_entity.IntentEntityService.analyze")
    def test_multi_doctor_resolution_not_collapsed_to_one(self, mock_analyze):
        """Phase 41 regression: resolve_entities correctly resolves both
        doctor_name entities for "Tell me about Priya and Omar" — the
        separate free-text fuzzy resolver (resolve_doctor_candidates) must
        not then collapse that back down to a single best guess."""
        mock_analyze.return_value = self._fake_nlu(
            intent=Intent.DOCTOR_SEARCH,
            confidence=0.95,
            entities=ExtractedEntities(doctor_name=["Priya", "Omar"]),
            needs_sql=True,
        )
        result = ChatEngine().process(
            clinic=self.clinic,
            message="Tell me about Priya and Omar.",
            session=None,
        )
        names = {
            r.get("full_name")
            for block in result.sql_results
            for r in block.get("rows", [])
        }
        self.assertEqual(names, {"Dr. Priya Chandrasekaran", "Dr. Omar Haddad"})

    @patch("apps.chatbot.nlu.intent_entity.IntentEntityService.analyze")
    def test_gender_question_never_reaches_sql(self, mock_analyze):
        """Gender is never stored on Doctor — must be a Python decision
        that stops before SQL/vector/LLM regardless of NLU's own intent."""
        mock_analyze.return_value = self._fake_nlu(
            intent=Intent.DOCTOR_SEARCH, confidence=0.6, needs_sql=True
        )
        result = ChatEngine().process(
            clinic=self.clinic,
            message="Do you have any female doctors?",
            session=None,
        )
        self.assertEqual(result.sql_results, [])
        self.assertIn("don't include gender", result.response)

    @patch("apps.chatbot.nlu.intent_entity.IntentEntityService.analyze")
    def test_should_is_not_extracted_as_doctor_name(self, mock_analyze):
        """Phase 41 regression: "which doctor should I see" — "should" was
        extracted as doctor_name, filtering out every real doctor."""
        mock_analyze.return_value = self._fake_nlu(
            intent=Intent.DOCTOR_SEARCH,
            confidence=0.9,
            entities=ExtractedEntities(doctor_name="should", symptom="fever"),
            needs_sql=True,
        )
        result = ChatEngine().process(
            clinic=self.clinic,
            message="Which doctor should I see?",
            session=None,
        )
        names = {
            r.get("full_name")
            for block in result.sql_results
            for r in block.get("rows", [])
        }
        self.assertTrue(names)
