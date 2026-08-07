"""ExecutionPlan planner: multi-task, capability tables, ignore LLM orchestration."""

from __future__ import annotations

from django.test import SimpleTestCase

from apps.chatbot.nlu.schemas import parse_nlu_payload
from apps.chatbot.planner import (
    build_execution_plan,
    build_planner_facts,
    choose_plan,
)
from apps.chatbot.routing.lanes import Lane


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


class ExecutionPlanTests(SimpleTestCase):
    def test_medicare_booking_plus_insurance_and_billing(self):
        nlu = parse_nlu_payload(
            {
                "intent": "book_appointment",
                "secondary_intents": ["insurance_accepted"],
                "confidence": 0.92,
                "topic": "billing_policy",
                "entities": {
                    "insurance_provider": "Medicare Part B",
                    "date": "today",
                },
                # Deprecated orchestration — must be ignored
                "needs_sql": False,
                "needs_vector": False,
                "sql_tool": None,
            }
        )
        msg = (
            "I have Medicare Part B. Can I book an appointment today, "
            "and will you bill Medicare directly for my visit?"
        )
        plan = build_execution_plan(
            nlu=nlu,
            facts=_facts(
                nlu=nlu,
                message=msg,
                is_booking_intent=True,
                knowledge_q=False,
            ),
        )
        self.assertTrue(plan.booking)
        self.assertIn("insurance", plan.sql_tasks)
        self.assertIn("billing_policy", plan.vector_tasks)
        self.assertTrue(plan.use_response_llm)
        self.assertEqual(plan.primary_lane, Lane.BOOKING)

    def test_secondary_insurance_topic_without_entity_is_not_trusted(self):
        """Regression: live-verifying the "Clarification flow" case found that
        gibberish input ("banana purple seven") gets classified intent=faq
        with topic="insurance" and secondary_intents=["insurance_verification"]
        hallucinated by the small NLU classifier — no insurance_provider entity
        was ever extracted, because there was nothing in the message to extract.
        That used to still attach a real insurance SQL task (and render an
        insurance card) on a reply whose own text says "could you clarify your
        question?". Only the primary intent should be trusted unconditionally;
        a topic or secondary intent needs a real entity to back it up."""
        nlu = parse_nlu_payload(
            {
                "intent": "faq",
                "secondary_intents": ["insurance_verification"],
                "confidence": 0.85,
                "topic": "insurance",
                "entities": {},
            }
        )
        msg = "banana purple seven"
        plan = build_execution_plan(
            nlu=nlu,
            facts=_facts(nlu=nlu, message=msg, knowledge_q=False),
        )
        self.assertNotIn("insurance", plan.sql_tasks)

    def test_primary_insurance_intent_stays_trusted_without_entity(self):
        """The primary intent is never gated — "do you accept Delta Dental?"
        with intent=insurance_accepted as the *primary* classification must
        still get the insurance SQL task even before any entity is resolved
        downstream."""
        nlu = parse_nlu_payload(
            {
                "intent": "insurance_accepted",
                "confidence": 0.95,
                "entities": {},
            }
        )
        msg = "do you accept Delta Dental?"
        plan = build_execution_plan(
            nlu=nlu,
            facts=_facts(nlu=nlu, message=msg, knowledge_q=False),
        )
        self.assertIn("insurance", plan.sql_tasks)

    def test_cancel_fee_is_vector_not_pricing_sql(self):
        nlu = parse_nlu_payload(
            {
                "intent": "pricing",
                "confidence": 0.9,
                "needs_sql": True,
                "sql_tool": "pricing",
            }
        )
        msg = "What is the cancel fee if I cancel less than 24 hours?"
        plan = build_execution_plan(
            nlu=nlu,
            facts=_facts(
                nlu=nlu,
                message=msg,
                knowledge_q=True,
                has_catalog=True,
                doc_match=True,
            ),
        )
        self.assertIn("cancellation", plan.vector_tasks)
        self.assertNotIn("pricing", plan.sql_tasks)
        self.assertEqual(plan.primary_lane, Lane.VECTOR_RAG)

    def test_hours_is_sql_only(self):
        nlu = parse_nlu_payload(
            {
                "intent": "clinic_hours",
                "confidence": 0.95,
                "needs_vector": True,  # deprecated noise — ignore
                "document_needed": True,
            }
        )
        plan = build_execution_plan(
            nlu=nlu,
            facts=_facts(nlu=nlu, message="What are your clinic hours?"),
        )
        self.assertEqual(plan.sql_tasks, ["hours"])
        self.assertEqual(plan.vector_tasks, [])
        self.assertFalse(plan.use_response_llm)
        self.assertEqual(plan.primary_lane, Lane.SQL_FAST)

    def test_choose_plan_wrapper_still_works(self):
        nlu = parse_nlu_payload(
            {"intent": "emergency", "is_emergency": True, "confidence": 0.99}
        )
        decision = choose_plan(
            nlu=nlu,
            is_booking_intent=True,
            soft_medical=False,
            needs_vector=True,
            doc_match=False,
            has_catalog=True,
            prefer_vector=False,
            prefer_clarify=False,
            degraded=False,
            doctor_ranking_request=False,
            instruction_injection=False,
            unknown_doctor_requested=False,
            message="chest pain radiating to arm",
        )
        self.assertEqual(decision.lane, Lane.DIRECT)
        self.assertEqual(decision.direct_mode, "emergency")
        self.assertIsNotNone(decision.execution_plan)
        self.assertTrue(decision.execution_plan.emergency)

    def test_ignores_llm_sql_tool_for_task_selection(self):
        nlu = parse_nlu_payload(
            {
                "intent": "faq",
                "confidence": 0.9,
                "sql_tool": "hours",
                "needs_sql": True,
                "topic": "cancellation",
            }
        )
        plan = build_execution_plan(
            nlu=nlu,
            facts=_facts(
                nlu=nlu,
                message="What is your cancellation refund policy?",
                knowledge_q=True,
            ),
        )
        self.assertNotIn("hours", plan.sql_tasks)
        self.assertTrue(plan.vector_tasks)

    def test_soft_schedule_faq_routes_to_availability_not_rag(self):
        nlu = parse_nlu_payload(
            {
                "intent": "faq",
                "confidence": 0.85,
                "entities": {
                    "date": ["Thursday"],
                    "time": ["afternoon", "night"],
                },
                "topic": "general_faq",
            }
        )
        plan = build_execution_plan(
            nlu=nlu,
            facts=_facts(
                nlu=nlu,
                message=(
                    "i was thinking about booking a slot for me "
                    "on thursday afternoon or might be night"
                ),
                knowledge_q=False,
                has_catalog=True,
            ),
        )
        self.assertIn("availability", plan.sql_tasks)
        self.assertNotIn("general_faq", plan.vector_tasks)
        self.assertFalse(plan.booking)
