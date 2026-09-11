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

    def test_not_anymore_inside_long_symptom_narrative_is_not_a_cancel(self):
        """Phase 40: a real eHealthForum question — "it use to hurt but not
        anymore" is a ~70-word symptom description where "not anymore"
        modifies "used to hurt", not a request to cancel anything. Fired
        _STRONG_CANCEL_RE unconditionally (no thread, no length check) and
        swallowed the patient's actual question behind a generic reverse
        reply."""
        text = (
            "i have a hard bump on the up side of the left foot it use to "
            "hurt but not anymore it could be from trauma but i am not "
            "sure i am worried because i do not remember if i hit my foot "
            "or not when i rub my feet i feel like a little mountain "
            "really hard"
        )
        action = detect_recovery(text, ConversationTimeline())
        self.assertEqual(action.kind, "none")

    def test_short_not_anymore_cancel_still_recovers(self):
        action = detect_recovery("not anymore, thanks", ConversationTimeline())
        self.assertEqual(action.kind, "reverse")
        self.assertTrue(action.strong_cancel)

    def test_dont_want_inside_a_real_followup_question_is_not_a_cancel(self):
        """Live-confirmed (stress test against real chatbot failure-mode
        research): "I don't want a female doctor, who's available besides
        Dr. Rostova?" is short enough to pass _STRONG_CANCEL_MAX_WORDS, and
        "don't want" matches _STRONG_CANCEL_RE, but this is a preference
        clause inside a real, answerable follow-up question -- not a
        whole-thread cancellation. It used to get swallowed into the
        generic "Sure — what would you like to do instead?" reverse reply
        instead of reaching the doctor-search handling underneath. A
        genuine cancel ("never mind", "actually no", "forget it") is
        essentially always a bare statement, never a message that goes on
        to ask something real -- the trailing "?" is what distinguishes
        this case."""
        action = detect_recovery(
            "I don't want a female doctor, who's available besides Dr. Rostova?",
            ConversationTimeline(),
        )
        self.assertEqual(action.kind, "none")

    def test_short_dont_want_cancel_without_a_question_still_recovers(self):
        """The new question-mark guard must not swallow a genuine short
        cancel that happens to have no trailing question."""
        action = detect_recovery("actually I don't want that anymore", ConversationTimeline())
        self.assertEqual(action.kind, "reverse")
        self.assertTrue(action.strong_cancel)

    # Live-reproduced (ROADMAP.md "context-switch pricing-anchor" phase):
    # a real cancel phrase followed by a genuine follow-up *typed without a
    # trailing "?"* used to still swallow the follow-up into the generic
    # "what would you like to do instead?" reverse reply, discarding an
    # already-correct, already-computed answer downstream. These are the
    # exact 7 topic-switch shapes reproduced live against the real
    # ChatEngine/real Horizon clinic/real OpenAI NLU (pricing->hours,
    # pricing->insurance, pricing->doctors, pricing->checkup, booking->
    # information, doctor_search->pricing, service_search->hours) —
    # `detect_recovery` alone is the exact layer that decided this, so a
    # unit test here is the precise regression lock; the full-pipeline
    # version is `test_unpunctuated_cancel_plus_followup_is_not_swallowed`
    # below.
    def test_pricing_to_hours_switch_without_question_mark_is_not_a_cancel(self):
        action = detect_recovery(
            "ok cool, and what time do you guys close today", ConversationTimeline()
        )
        self.assertEqual(action.kind, "none")

    def test_pricing_to_doctors_switch_without_question_mark_is_not_a_cancel(self):
        action = detect_recovery(
            "actually forget that, who are your doctors", ConversationTimeline()
        )
        self.assertEqual(action.kind, "none")

    def test_pricing_to_checkup_switch_without_question_mark_is_not_a_cancel(self):
        action = detect_recovery(
            "never mind, i think i just need a checkup", ConversationTimeline()
        )
        self.assertEqual(action.kind, "none")

    def test_doctor_search_to_pricing_switch_without_question_mark_is_not_a_cancel(self):
        action = detect_recovery(
            "ok never mind that, how much is a physical", ConversationTimeline()
        )
        self.assertEqual(action.kind, "none")

    def test_service_search_to_hours_switch_without_question_mark_is_not_a_cancel(self):
        action = detect_recovery(
            "forget it, what time do you open tomorrow", ConversationTimeline()
        )
        self.assertEqual(action.kind, "none")

    def test_booking_to_information_switch_without_question_mark_is_not_a_cancel(self):
        action = detect_recovery(
            "actually forget it, can I get your address", ConversationTimeline()
        )
        self.assertEqual(action.kind, "none")

    def test_bare_cancel_with_only_filler_after_it_still_recovers(self):
        """The new remainder-word-count signal must not become "any text
        after the cancel phrase at all counts as a real follow-up" — pure
        filler ("thanks", "that's it") is still a bare cancel."""
        action = detect_recovery("never mind, thanks", ConversationTimeline())
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
        # The real, SQL-backed multi-doctor result renders as "Found N
        # doctors... take a look below" (formatter.py no longer repeats
        # names/specialties already shown in the doctor cards) -- this
        # still proves the real response wasn't discarded, which is what
        # this test actually checks; a specific doctor's name is no longer
        # part of that text for a 2+-result browse (see the single-result
        # case in test_or_nah_preserves_hamza_response below, which still
        # names the doctor since only one row matches there).
        self.assertIn("Found 2 doctors", result.response)
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
    def test_unpunctuated_cancel_plus_followup_is_not_swallowed(self, mock_analyze):
        """Full-pipeline lock for the live-reproduced bug: a real cancel
        phrase ("actually forget that") followed by a real follow-up
        question typed with no "?" must reach the actual doctor_search
        answer, not the generic reverse reply -- even though there's an
        active prior thread (pricing) recovery could otherwise latch onto."""
        mock_analyze.return_value = self._fake_nlu(intent=Intent.DOCTOR_SEARCH)
        tl = ConversationTimeline(intent_thread="pricing", service={"name": "Sutures"})
        ctx = {"timeline": tl.to_dict(), "last_service": {"name": "Sutures"}}
        result = ChatEngine().process(
            clinic=self.clinic,
            message="actually forget that, who are your doctors",
            session=None,
            conversation_context=ctx,
        )
        self.assertNotIn("what would you like to do instead", result.response.lower())
        self.assertIn("Found 2 doctors", result.response)

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
