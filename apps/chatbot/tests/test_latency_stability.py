"""Latency/stability: circuit breaker, deadlines, medical/aesthetic planner paths."""

from __future__ import annotations

from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from apps.chatbot.nlu.schemas import parse_nlu_payload
from apps.chatbot.planner import build_execution_plan, build_planner_facts
from apps.chatbot.providers import circuit_breaker
from apps.chatbot.response_llm import ResponseLLMError, empty_rag_reply, synthesize_clinic_reply
from apps.chatbot.routing.lanes import Lane
from apps.chatbot.routing.signals import is_transactional_booking


class CircuitBreakerTests(SimpleTestCase):
    def setUp(self):
        circuit_breaker.reset()

    def tearDown(self):
        circuit_breaker.reset()

    @override_settings(LLM_CIRCUIT_FAILURE_THRESHOLD=3, LLM_CIRCUIT_COOLDOWN_SECONDS=60)
    def test_opens_after_threshold(self):
        self.assertTrue(circuit_breaker.is_available("gemini"))
        circuit_breaker.record_failure("gemini", "timeout")
        circuit_breaker.record_failure("gemini", "timeout")
        self.assertTrue(circuit_breaker.is_available("gemini"))
        circuit_breaker.record_failure("gemini", "timeout")
        self.assertFalse(circuit_breaker.is_available("gemini"))
        circuit_breaker.record_success("gemini")
        self.assertTrue(circuit_breaker.is_available("gemini"))


class PlannerStabilityTests(SimpleTestCase):
    def test_medical_advice_refusal(self):
        nlu = parse_nlu_payload(
            {"intent": "medical_question", "confidence": 0.9}
        )
        msg = "I want Botox, but I have lupus and I'm taking blood thinners. Is it safe?"
        plan = build_execution_plan(
            nlu=nlu,
            facts=build_planner_facts(nlu=nlu, message=msg, has_catalog=True),
        )
        self.assertTrue(plan.direct)
        self.assertEqual(plan.direct_mode, "medical_advice_refusal")

    def test_aesthetic_uses_services_sql(self):
        nlu = parse_nlu_payload({"intent": "pricing", "confidence": 0.9})
        msg = "How much does a chemical peel cost?"
        plan = build_execution_plan(
            nlu=nlu,
            facts=build_planner_facts(nlu=nlu, message=msg, has_catalog=True),
        )
        self.assertIn("services", plan.sql_tasks)

    def test_reschedule_is_transactional(self):
        self.assertTrue(is_transactional_booking("I want to reschedule my appointment"))


class ResponseDeadlineTests(SimpleTestCase):
    @override_settings(
        CHAT_RESPONSE_PROVIDER="openai",
        CHAT_RESPONSE_TIMEOUT_SECONDS=0.2,
        OPENAI_API_KEY="sk-test",
    )
    @patch("apps.chatbot.response_llm.run_with_deadline")
    def test_timeout_raises_response_error(self, mock_deadline):
        mock_deadline.side_effect = TimeoutError("exceeded")
        clinic = type("C", (), {"name": "Acme", "phone": "555"})()
        with self.assertRaises(ResponseLLMError):
            synthesize_clinic_reply(
                clinic=clinic,
                message="What is cancel fee?",
                vector_rows=[{"score": 0.9, "heading": "x", "text": "fee is $50"}],
                deadline_seconds=0.2,
            )

    def test_empty_rag_copy(self):
        clinic = type("C", (), {"name": "Acme", "phone": "555-0144"})()
        text = empty_rag_reply(clinic)
        self.assertIn("clinic-specific", text.lower())
        self.assertNotIn("policy document", text.lower())
