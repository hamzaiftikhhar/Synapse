"""Intent prioritization for compound patient turns."""

from __future__ import annotations

from django.test import SimpleTestCase

from apps.chatbot.conversation_state import ConversationTimeline
from apps.chatbot.intent_priority import analyze_compound_turn, apply_priority_to_nlu
from apps.chatbot.nlu.schemas import Intent, parse_nlu_payload


class IntentPriorityTests(SimpleTestCase):
    def test_molar_pain_prioritizes_medical_then_booking(self):
        nlu = parse_nlu_payload({"intent": "medical_question", "confidence": 0.9})
        turn = analyze_compound_turn("my molar hurts bad", nlu)
        kinds = [s.kind for s in turn.sub_intents]
        self.assertEqual(kinds[0], "medical")
        self.assertTrue(turn.offer_earliest_slots)

    def test_doctor_free_monday_routes_availability(self):
        nlu = parse_nlu_payload({"intent": "clinic_hours", "confidence": 0.8})
        turn = analyze_compound_turn("dr aris free monday?", nlu)
        self.assertEqual(turn.primary_intent, Intent.DOCTOR_AVAILABILITY)

    def test_squeeze_me_in_is_urgent(self):
        nlu = parse_nlu_payload({"intent": "unknown", "confidence": 0.5})
        turn = analyze_compound_turn("can yall squeeze me in", nlu)
        self.assertTrue(turn.urgent_booking)

    def test_wedding_whitening_timeline_sensitive(self):
        nlu = parse_nlu_payload({"intent": "services_offered", "confidence": 0.85})
        turn = analyze_compound_turn("need whitening before wedding", nlu)
        self.assertTrue(turn.timeline_sensitive)
        self.assertTrue(turn.offer_earliest_slots)

    def test_apply_priority_overrides_hours_to_availability(self):
        nlu = parse_nlu_payload({"intent": "clinic_hours", "confidence": 0.88})
        turn = analyze_compound_turn("dr aris free monday?", nlu)
        adjusted = apply_priority_to_nlu(nlu, turn)
        self.assertEqual(adjusted.intent, Intent.DOCTOR_AVAILABILITY)
