from __future__ import annotations

from django.test import SimpleTestCase

from apps.api.chat.router import _fallback_out
from apps.chatbot.nlu.schemas import Intent, parse_nlu_payload
from apps.chatbot.planner import choose_plan
from apps.chatbot.routing.lanes import Lane


class PlannerLayerTests(SimpleTestCase):
    def test_emergency_beats_booking(self):
        nlu = parse_nlu_payload(
            {
                "intent": "emergency",
                "confidence": 0.95,
                "is_emergency": True,
                "can_respond_directly": True,
            }
        )
        plan = choose_plan(
            nlu=nlu,
            is_booking_intent=True,
            soft_medical=False,
            needs_vector=False,
            doc_match=False,
            has_catalog=True,
            prefer_vector=False,
            prefer_clarify=False,
            degraded=False,
            doctor_ranking_request=False,
            instruction_injection=False,
            unknown_doctor_requested=False,
        )
        self.assertEqual(plan.lane, Lane.DIRECT)
        self.assertEqual(plan.direct_mode, "emergency")

    def test_doctor_ranking_refuses_directly(self):
        nlu = parse_nlu_payload(
            {"intent": "doctor_search", "confidence": 0.9, "needs_sql": True}
        )
        plan = choose_plan(
            nlu=nlu,
            is_booking_intent=False,
            soft_medical=False,
            needs_vector=False,
            doc_match=False,
            has_catalog=False,
            prefer_vector=False,
            prefer_clarify=False,
            degraded=False,
            doctor_ranking_request=True,
            instruction_injection=False,
            unknown_doctor_requested=False,
        )
        self.assertEqual(plan.lane, Lane.DIRECT)
        self.assertEqual(plan.direct_mode, "doctor_ranking_refusal")

    def test_unknown_doctor_booking_never_starts_booking(self):
        nlu = parse_nlu_payload(
            {
                "intent": "book_appointment",
                "confidence": 0.92,
                "needs_sql": True,
                "entities": {"doctor_name": ["Harrison Wells"]},
            }
        )
        plan = choose_plan(
            nlu=nlu,
            is_booking_intent=True,
            soft_medical=False,
            needs_vector=False,
            doc_match=False,
            has_catalog=False,
            prefer_vector=False,
            prefer_clarify=False,
            degraded=False,
            doctor_ranking_request=False,
            instruction_injection=False,
            unknown_doctor_requested=True,
        )
        self.assertEqual(plan.lane, Lane.DIRECT)
        self.assertEqual(plan.direct_mode, "unknown_doctor_refusal")

    def test_prompt_injection_refuses_directly(self):
        nlu = parse_nlu_payload({"intent": "pricing", "confidence": 0.9, "needs_sql": True})
        plan = choose_plan(
            nlu=nlu,
            is_booking_intent=False,
            soft_medical=False,
            needs_vector=False,
            doc_match=False,
            has_catalog=False,
            prefer_vector=False,
            prefer_clarify=False,
            degraded=False,
            doctor_ranking_request=False,
            instruction_injection=True,
            unknown_doctor_requested=False,
        )
        self.assertEqual(plan.lane, Lane.DIRECT)
        self.assertEqual(plan.direct_mode, "prompt_injection_refusal")


class CompoundRoutingGuardTests(SimpleTestCase):
    """Phase 2 eval slice: is_unresolved_compound() (routing/signals.py)
    guards four sensor-driven add_sql sites in build_execution_plan plus
    one heuristics.py reclassification -- live-confirmed that without it,
    a compound message NLU itself couldn't resolve (intent=unknown) still
    got silently routed to a single-topic SQL answer, dropping whichever
    half the sensor didn't happen to match. These tests lock in both
    halves of that fix: compound+unknown must clarify, and a genuinely
    single-topic unknown message must keep today's rescue behavior."""

    def _plan(self, message: str, **overrides):
        nlu = parse_nlu_payload({"intent": "unknown", "confidence": 0.5})
        kwargs = dict(
            nlu=nlu,
            is_booking_intent=False,
            soft_medical=False,
            needs_vector=False,
            doc_match=False,
            has_catalog=True,
            prefer_vector=False,
            prefer_clarify=False,
            degraded=False,
            doctor_ranking_request=False,
            instruction_injection=False,
            unknown_doctor_requested=False,
            message=message,
        )
        kwargs.update(overrides)
        return choose_plan(**kwargs)

    def test_compound_unresolved_message_does_not_force_doctor_availability_sql(self):
        plan = self._plan(
            "tell me about Dr Lee and is he available friday",
            doctor_availability_query=True,
        )
        self.assertEqual(plan.execution_plan.sql_tasks, [])
        self.assertEqual(plan.lane, Lane.CLARIFY)

    def test_noncompound_unresolved_message_still_gets_availability_rescue(self):
        plan = self._plan(
            "is anyone free tmrw",
            doctor_availability_query=True,
        )
        self.assertIn("availability", plan.execution_plan.sql_tasks)
        self.assertEqual(plan.lane, Lane.SQL_FAST)

    def test_compound_unresolved_message_does_not_force_specialty_list_sql(self):
        plan = self._plan(
            "what specialties do you have and is there parking",
            specialty_list=True,
        )
        self.assertEqual(plan.execution_plan.sql_tasks, [])
        self.assertEqual(plan.lane, Lane.CLARIFY)

    def test_noncompound_unresolved_message_still_gets_specialty_list_rescue(self):
        plan = self._plan(
            "what specialties do you have",
            specialty_list=True,
        )
        self.assertIn("specialties", plan.execution_plan.sql_tasks)
        self.assertEqual(plan.lane, Lane.SQL_FAST)


class FallbackOutTests(SimpleTestCase):
    def test_chat_api_fallback_is_degraded_clarify(self):
        out = _fallback_out()
        self.assertEqual(out.route, "clarify")
        self.assertEqual(out.intent, "unknown")
        self.assertTrue(out.meta["degraded"])
        self.assertEqual(out.meta["degraded_reason"], "chat_engine_exception")
