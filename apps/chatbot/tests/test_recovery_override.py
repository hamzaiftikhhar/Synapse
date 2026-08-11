"""Recovery detection and engine override regression tests."""

from __future__ import annotations

from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from apps.chatbot.conversation_state import (
    ConversationTimeline,
    detect_recovery,
    recovery_reply,
    should_apply_recovery_override,
)
from apps.chatbot.engine import ChatEngine
from apps.chatbot.nlu.schemas import ExtractedEntities, Intent, NLUResult, ResolvedIds
from apps.clinics.models import Clinic
from apps.doctors.models import Doctor


class RecoveryDetectionTests(SimpleTestCase):
    def test_strong_cancel_without_thread(self):
        action = detect_recovery("nah forget it", ConversationTimeline())
        self.assertEqual(action.kind, "reverse")
        self.assertTrue(action.strong_cancel)

    def test_never_mind_with_insurance_thread(self):
        tl = ConversationTimeline(intent_thread="insurance", insurance={"name": "Aetna"})
        action = detect_recovery("never mind", tl)
        self.assertEqual(action.kind, "reverse")
        self.assertTrue(action.strong_cancel)
        self.assertIn("insurance", recovery_reply(action, tl).lower())

    def test_nah_fr_doctors_not_recovery(self):
        action = detect_recovery("nah fr who are ur doctors rn", ConversationTimeline())
        self.assertEqual(action.kind, "none")

    def test_or_nah_not_recovery(self):
        action = detect_recovery("wait do u even have dr hamza or nah", ConversationTimeline())
        self.assertEqual(action.kind, "none")

    def test_you_guys_have_hamza_or_nah(self):
        action = detect_recovery("you guys have hamza or nah", ConversationTimeline())
        self.assertEqual(action.kind, "none")

    def test_nah_who_available_not_recovery(self):
        action = detect_recovery("nah, who is available?", ConversationTimeline())
        self.assertEqual(action.kind, "none")

    def test_weak_nah_with_booking_thread(self):
        tl = ConversationTimeline(booking_stage="pick_time")
        action = detect_recovery("nah", tl)
        self.assertEqual(action.kind, "reverse")
        self.assertFalse(action.strong_cancel)

    def test_nah_never_mind_strong(self):
        action = detect_recovery("nah, never mind", ConversationTimeline())
        self.assertEqual(action.kind, "reverse")
        self.assertTrue(action.strong_cancel)


class RecoveryOverrideGuardTests(SimpleTestCase):
    def test_weak_cold_start_does_not_override_sql(self):
        from apps.chatbot.conversation_state import RecoveryAction

        recovery = RecoveryAction(kind="reverse", thread=None, strong_cancel=False)
        self.assertFalse(should_apply_recovery_override(recovery, sql_found=True))

    def test_strong_cancel_overrides_sql(self):
        from apps.chatbot.conversation_state import RecoveryAction

        recovery = RecoveryAction(kind="reverse", thread=None, strong_cancel=True)
        self.assertTrue(should_apply_recovery_override(recovery, sql_found=True))

    def test_weak_with_thread_overrides_sql(self):
        from apps.chatbot.conversation_state import RecoveryAction

        recovery = RecoveryAction(kind="reverse", thread="booking", strong_cancel=False)
        self.assertTrue(should_apply_recovery_override(recovery, sql_found=True))


class RecoveryEngineIntegrationTests(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="recovery-engine-clinic",
            name="Recovery Engine Clinic",
            email="re@clinic.com",
            phone="+12125550100",
            address={"street": "2 Main", "city": "Boston", "state": "MA", "zip": "02101"},
            timezone="America/New_York",
        )
        Doctor.objects.create(
            clinic=self.clinic,
            full_name="Dr. Hamza Ali",
            is_accepting_patients=True,
        )
        Doctor.objects.create(
            clinic=self.clinic,
            full_name="Dr. Choe Martin",
            is_accepting_patients=True,
        )

    def _fake_nlu(self, **kwargs) -> NLUResult:
        return NLUResult(
            intent=kwargs.get("intent", Intent.DOCTOR_SEARCH),
            confidence=0.9,
            entities=kwargs.get("entities", ExtractedEntities()),
            resolved_ids=ResolvedIds(),
            needs_sql=True,
        )

    @patch("apps.chatbot.nlu.intent_entity.IntentEntityService.analyze")
    def test_nah_fr_preserves_doctor_sql_response(self, mock_analyze):
        mock_analyze.return_value = self._fake_nlu(
            entities=ExtractedEntities(specialty="Heart stunts"),
        )
        result = ChatEngine().process(
            clinic=self.clinic,
            message="nah fr who are ur doctors rn",
            session=None,
        )
        self.assertIn("Hamza", result.response)
        self.assertNotIn("what would you like to do instead", result.response)

    @patch("apps.chatbot.nlu.intent_entity.IntentEntityService.analyze")
    def test_or_nah_preserves_hamza_response(self, mock_analyze):
        mock_analyze.return_value = self._fake_nlu(
            entities=ExtractedEntities(doctor_name=["hamza"]),
        )
        result = ChatEngine().process(
            clinic=self.clinic,
            message="wait do u even have dr hamza or nah",
            session=None,
        )
        self.assertIn("Hamza", result.response)
        self.assertNotIn("what would you like to do instead", result.response)

    @patch("apps.chatbot.nlu.intent_entity.IntentEntityService.analyze")
    def test_strong_cancel_still_recovers(self, mock_analyze):
        mock_analyze.return_value = self._fake_nlu(intent=Intent.DOCTOR_SEARCH)
        tl = ConversationTimeline(intent_thread="insurance", insurance={"name": "Aetna"})
        ctx = {"timeline": tl.to_dict(), "last_insurance": {"name": "Aetna"}}
        result = ChatEngine().process(
            clinic=self.clinic,
            message="nah, never mind",
            session=None,
            conversation_context=ctx,
        )
        self.assertIn("insurance", result.response.lower())
