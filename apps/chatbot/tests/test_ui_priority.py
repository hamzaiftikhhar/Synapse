"""UIPriority: backend-only decision of how much cross-sell UI a turn allows."""

from __future__ import annotations

from django.test import SimpleTestCase

from apps.chatbot.nlu.schemas import parse_nlu_payload
from apps.chatbot.planner import UIPriority, build_execution_plan, build_planner_facts


def _facts(**kwargs):
    nlu = kwargs.pop("nlu")
    defaults = dict(
        message="",
        is_booking_intent=False,
        soft_medical=False,
        knowledge_q=False,
        has_catalog=True,
        doc_match=True,
        degraded=False,
        doctor_ranking_request=False,
        instruction_injection=False,
        unknown_doctor_requested=False,
    )
    defaults.update(kwargs)
    return build_planner_facts(nlu=nlu, **defaults)


class UIPriorityTests(SimpleTestCase):
    def test_insurance_question_is_none_priority(self):
        nlu = parse_nlu_payload({"intent": "insurance_accepted", "confidence": 0.95})
        plan = build_execution_plan(
            nlu=nlu, facts=_facts(nlu=nlu, message="Does insurance cover Botox?")
        )
        self.assertEqual(plan.ui_priority, UIPriority.NONE)

    def test_clinic_hours_is_none_priority(self):
        nlu = parse_nlu_payload({"intent": "clinic_hours", "confidence": 0.95})
        plan = build_execution_plan(
            nlu=nlu, facts=_facts(nlu=nlu, message="What are your hours?")
        )
        self.assertEqual(plan.ui_priority, UIPriority.NONE)

    def test_pricing_question_is_none_priority(self):
        nlu = parse_nlu_payload({"intent": "pricing", "confidence": 0.9})
        plan = build_execution_plan(
            nlu=nlu, facts=_facts(nlu=nlu, message="How much is a consultation?")
        )
        self.assertEqual(plan.ui_priority, UIPriority.NONE)

    def test_doctor_search_is_primary_priority(self):
        nlu = parse_nlu_payload({"intent": "doctor_search", "confidence": 0.95})
        plan = build_execution_plan(
            nlu=nlu, facts=_facts(nlu=nlu, message="Help me find a doctor")
        )
        self.assertEqual(plan.ui_priority, UIPriority.PRIMARY)

    def test_booking_is_booking_priority(self):
        nlu = parse_nlu_payload({"intent": "book_appointment", "confidence": 0.95})
        plan = build_execution_plan(
            nlu=nlu,
            facts=_facts(
                nlu=nlu, message="I want to book an appointment", is_booking_intent=True
            ),
        )
        self.assertTrue(plan.booking)
        self.assertEqual(plan.ui_priority, UIPriority.BOOKING)

    def test_emergency_is_emergency_priority(self):
        nlu = parse_nlu_payload(
            {"intent": "emergency", "is_emergency": True, "confidence": 0.99}
        )
        plan = build_execution_plan(
            nlu=nlu, facts=_facts(nlu=nlu, message="I have severe chest pain")
        )
        self.assertEqual(plan.ui_priority, UIPriority.EMERGENCY)

    def test_unknown_low_signal_is_inline_priority(self):
        nlu = parse_nlu_payload({"intent": "unknown", "confidence": 0.2})
        plan = build_execution_plan(
            nlu=nlu,
            facts=_facts(
                nlu=nlu, message="asdkfjhaskdjfh", has_catalog=False, doc_match=False
            ),
        )
        self.assertTrue(plan.clarify)
        self.assertEqual(plan.ui_priority, UIPriority.INLINE)
