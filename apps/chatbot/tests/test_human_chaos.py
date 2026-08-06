"""Natural patient-language regression coverage."""

from __future__ import annotations

from django.test import SimpleTestCase

from apps.chatbot.intent_priority import analyze_compound_turn
from apps.chatbot.nlu.rules import try_rule_classify
from apps.chatbot.nlu.schemas import Intent, parse_nlu_payload
from apps.chatbot.planner import build_execution_plan, build_planner_facts
from apps.chatbot.routing.signals import is_business_hours_query, is_doctor_availability_query


def _plan(message: str, intent: str):
    nlu = parse_nlu_payload({"intent": intent, "confidence": 0.9})
    facts = build_planner_facts(
        message=message,
        nlu=nlu,
        doctor_availability_query=is_doctor_availability_query(message),
        urgent_availability=bool(
            __import__("re").search(r"squeeze|asap", message, __import__("re").I)
        ),
    )
    return build_execution_plan(nlu=nlu, facts=facts)


class HumanChaosRoutingTests(SimpleTestCase):
    CASES = [
        ("dr aris free monday?", Intent.DOCTOR_AVAILABILITY.value),
        ("can yall squeeze me in", Intent.DOCTOR_AVAILABILITY.value),
        ("need xray asap", Intent.DOCTOR_AVAILABILITY.value),
        ("do u guys do implants", Intent.SERVICES_OFFERED.value),
    ]

    def test_rules_do_not_send_doctor_time_to_hours(self):
        for message, _ in self.CASES:
            if "dr aris" in message:
                self.assertFalse(is_business_hours_query(message), message)
                self.assertTrue(is_doctor_availability_query(message), message)

    def test_dr_aris_free_monday_rules_intent(self):
        hit = try_rule_classify("dr aris free monday?")
        self.assertIsNotNone(hit)
        self.assertEqual(hit["intent"], Intent.DOCTOR_AVAILABILITY.value)

    def test_availability_plan_uses_availability_task(self):
        plan = _plan("dr aris free monday?", Intent.DOCTOR_AVAILABILITY.value)
        self.assertIn("availability", plan.sql_tasks)
        self.assertNotIn("hours", plan.sql_tasks)

    def test_molar_hurt_offers_earliest(self):
        nlu = parse_nlu_payload({"intent": "medical_question", "confidence": 0.85})
        turn = analyze_compound_turn("my molar hurts bad", nlu)
        self.assertTrue(turn.offer_earliest_slots)

    def test_yo_is_not_hours(self):
        self.assertFalse(is_business_hours_query("yo"))

    def test_wedding_whitening_timeline(self):
        nlu = parse_nlu_payload({"intent": "services_offered", "confidence": 0.85})
        turn = analyze_compound_turn("need whitening before wedding", nlu)
        self.assertTrue(turn.timeline_sensitive)
