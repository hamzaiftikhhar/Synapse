"""Natural patient-language regression coverage."""

from __future__ import annotations

from django.test import SimpleTestCase

from apps.chatbot.nlu.rules import try_rule_classify
from apps.chatbot.nlu.schemas import Intent, parse_nlu_payload
from apps.chatbot.planner import build_execution_plan, build_planner_facts
from apps.chatbot.routing.signals import (
    is_business_hours_query,
    is_doctor_availability_query,
    is_urgent_availability_request,
)


def _plan(message: str, intent: str):
    nlu = parse_nlu_payload({"intent": intent, "confidence": 0.9})
    facts = build_planner_facts(
        message=message,
        nlu=nlu,
        doctor_availability_query=is_doctor_availability_query(message),
        urgent_availability=is_urgent_availability_request(message),
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

    def test_yo_is_not_hours(self):
        self.assertFalse(is_business_hours_query("yo"))

    def test_squeeze_me_in_is_urgent_availability(self):
        self.assertTrue(is_urgent_availability_request("can yall squeeze me in"))

    def test_urgent_availability_plan_uses_availability_task(self):
        plan = _plan("can yall squeeze me in", Intent.UNKNOWN.value)
        self.assertIn("availability", plan.sql_tasks)
