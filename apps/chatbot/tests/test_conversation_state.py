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
