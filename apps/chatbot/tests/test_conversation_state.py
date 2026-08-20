"""Conversation timeline and recovery helpers."""

from __future__ import annotations

from django.test import SimpleTestCase

from apps.chatbot.conversation_state import (
    ConversationTimeline,
    apply_recovery,
    detect_recovery,
    load_timeline,
    merge_turn_context,
    recovery_reply,
    save_timeline,
)


class ConversationStateTests(SimpleTestCase):
    def test_change_mind_recovery(self):
        tl = ConversationTimeline(intent_thread="insurance", insurance={"name": "Delta"})
        action = detect_recovery("nah i changed my mind", tl)
        self.assertEqual(action.kind, "reverse")
        text = recovery_reply(action, tl)
        self.assertIn("insurance", text.lower())

    def test_same_doctor_again(self):
        tl = ConversationTimeline(doctor={"id": "1", "name": "Dr. Aris Thorne"})
        action = detect_recovery("book same doctor again", tl)
        self.assertEqual(action.kind, "same_doctor")

    def test_timeline_roundtrip(self):
        tl = merge_turn_context(
            ConversationTimeline(),
            doctor={"id": "d1", "name": "Dr. A"},
            service={"id": "s1", "name": "Cleaning"},
            intent="book_appointment",
        )
        ctx = save_timeline({}, tl)
        loaded = load_timeline(ctx)
        self.assertEqual(loaded.doctor["name"], "Dr. A")
        self.assertEqual(loaded.service["name"], "Cleaning")

    def test_apply_recovery_clears_insurance(self):
        tl = ConversationTimeline(insurance={"name": "Aetna"}, intent_thread="insurance")
        action = detect_recovery("never mind", tl)
        tl = apply_recovery(action, tl)
        self.assertIsNone(tl.insurance)

    def test_nah_fr_not_recovery_on_empty_timeline(self):
        action = detect_recovery("nah fr who are ur doctors rn", ConversationTimeline())
        self.assertEqual(action.kind, "none")

    def test_or_nah_rhetorical_not_recovery(self):
        action = detect_recovery("do you have dr hamza or nah", ConversationTimeline())
        self.assertEqual(action.kind, "none")

    def test_nah_forget_it_is_strong_cancel(self):
        action = detect_recovery("nah forget it", ConversationTimeline())
        self.assertEqual(action.kind, "reverse")
        self.assertTrue(action.strong_cancel)


class PendingUptakeTests(SimpleTestCase):
    def test_varied_affirmations_are_uptake(self):
        from apps.chatbot.conversation_state import classify_uptake

        for text in ("Yep.", "Sure", "Please do", "Go ahead", "sounds good", "ok"):
            self.assertEqual(classify_uptake(text), "affirm", msg=text)

    def test_varied_declines_are_uptake(self):
        from apps.chatbot.conversation_state import classify_uptake

        for text in ("No thanks", "Not now", "maybe later", "nope"):
            self.assertEqual(classify_uptake(text), "decline", msg=text)

    def test_a_new_request_is_not_uptake(self):
        from apps.chatbot.conversation_state import classify_uptake

        for text in (
            "yes, Thursday morning if she's free",
            "is Cigna on the accepted list here",
            "what time do you close on Saturdays",
        ):
            self.assertIsNone(classify_uptake(text), msg=text)

    def test_without_a_pending_offer_uptake_does_not_matter(self):
        from apps.chatbot.conversation_state import classify_uptake

        self.assertEqual(classify_uptake("Yep."), "affirm")

    def test_affirm_rewrites_insurance_hallucination_to_availability(self):
        from apps.chatbot.conversation_state import apply_pending_uptake
        from apps.chatbot.nlu.schemas import ExtractedEntities, Intent, NLUResult

        nlu = NLUResult(
            intent=Intent.INSURANCE_VERIFICATION,
            confidence=0.95,
            entities=ExtractedEntities(),
        )
        pending = {
            "type": "availability_alternative",
            "doctor_id": "doc-1",
            "doctor_name": "Dr. Maya Lin",
        }
        bound = apply_pending_uptake(nlu, pending)
        self.assertEqual(bound.intent, Intent.DOCTOR_AVAILABILITY)
        self.assertEqual(bound.resolved_ids.doctor_id, "doc-1")
        self.assertIsNone(bound.entities.date)

    def test_empty_availability_records_an_alternative_offer(self):
        from apps.chatbot.conversation_state import pending_offer_from_turn
        from apps.chatbot.nlu.schemas import Intent, NLUResult

        offer = pending_offer_from_turn(
            sql_rows=[
                {
                    "handler": "doctor_availability",
                    "found": False,
                    "rows": [],
                    "meta": {"temporal_searchable": True},
                }
            ],
            nlu=NLUResult(intent=Intent.DOCTOR_AVAILABILITY, confidence=0.9),
            last_doctor={"id": "maya", "name": "Dr. Maya Lin"},
            matched_services=None,
        )
        self.assertEqual(offer["type"], "availability_alternative")
        self.assertEqual(offer["doctor_id"], "maya")

    def test_service_answer_records_a_followup_offer(self):
        from apps.chatbot.conversation_state import pending_offer_from_turn
        from apps.chatbot.nlu.schemas import Intent, NLUResult

        offer = pending_offer_from_turn(
            sql_rows=[],
            nlu=NLUResult(intent=Intent.MEDICAL_QUESTION, confidence=0.85),
            last_doctor=None,
            matched_services=[{"id": "rc-1", "name": "Root Canal"}],
        )
        self.assertEqual(offer["type"], "service_followup")
        self.assertEqual(offer["service_id"], "rc-1")
