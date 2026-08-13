"""Latency/stability: circuit breaker, deadlines, medical/aesthetic planner paths."""

from __future__ import annotations

import time
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from apps.chatbot.nlu.schemas import parse_nlu_payload
from apps.chatbot.planner import ExecutionPlan, build_execution_plan, build_planner_facts
from apps.chatbot.providers import circuit_breaker
from apps.chatbot.response_llm import ResponseLLMError, empty_rag_reply, synthesize_clinic_reply
from apps.chatbot.routing.lanes import Lane
from apps.chatbot.routing.signals import (
    is_booking_commit,
    is_generic_book_request,
    is_transactional_booking,
    is_typo_book_request,
    is_view_appointments_request,
)


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

    def test_generic_book_request_is_not_a_slot_commit(self):
        msg = "i would like to book an appointment"
        self.assertTrue(is_generic_book_request(msg))
        self.assertTrue(is_generic_book_request("I would like to book an appointment!"))
        self.assertFalse(is_booking_commit(msg))
        self.assertTrue(is_booking_commit("book with Dr. Rostova"))

    def test_colloquial_book_requests_are_generic(self):
        for msg in (
            "can you book me",
            "i want ot book",
            "i want to book",
            "book me",
            "write book me an appointment detailed essay on clinic and also",
        ):
            self.assertTrue(is_generic_book_request(msg), msg)

    def test_named_when_or_who_is_not_generic(self):
        self.assertFalse(is_generic_book_request("book with Dr. Tariq"))
        self.assertFalse(is_generic_book_request("book me Friday"))
        self.assertFalse(is_generic_book_request("book at 3pm"))

    def test_typo_book_me_is_transactional_not_a_lookup(self):
        for msg in ("koob me", "bbok me", "bok me", "boook me"):
            self.assertTrue(is_typo_book_request(msg), msg)
            self.assertTrue(is_transactional_booking(msg), msg)
            self.assertTrue(is_generic_book_request(msg), msg)
            self.assertFalse(is_view_appointments_request(msg), msg)

    def test_real_words_near_book_are_not_typos(self):
        self.assertFalse(is_typo_book_request("look me"))
        self.assertFalse(is_typo_book_request("cook me"))
        self.assertFalse(is_typo_book_request("hook me"))

    def test_view_language_is_not_a_book_typo(self):
        for msg in (
            "show my appointments",
            "do I have an appointment",
            "what's my next appointment",
            "check my appointment",
        ):
            self.assertTrue(is_view_appointments_request(msg), msg)
            self.assertFalse(is_typo_book_request(msg), msg)


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

    @override_settings(
        CHAT_RESPONSE_PROVIDER="openai",
        CHAT_RESPONSE_SECONDARY_PROVIDER="gemini",
        CHAT_RESPONSE_TIMEOUT_SECONDS=8.0,
    )
    @patch("apps.chatbot.response_llm._gemini_generate")
    @patch("apps.chatbot.response_llm._openai_generate")
    def test_fallback_splits_budget_instead_of_full_timeout_each(
        self, mock_openai, mock_gemini
    ):
        """Regression: each provider used to get its own independent
        min(remaining, CHAT_RESPONSE_TIMEOUT_SECONDS) slice, so a primary
        timeout plus a secondary timeout could stack to 2x the per-provider
        cap (the 16s stalls in production). Each attempt must now get a fair
        share of the total budget instead."""
        circuit_breaker.reset()
        mock_openai.side_effect = ResponseLLMError("boom")
        mock_gemini.return_value = "ok"
        clinic = type("C", (), {"name": "Acme", "phone": "555"})()

        text = synthesize_clinic_reply(
            clinic=clinic,
            message="hi",
            vector_rows=[{"score": 0.9, "heading": "x", "text": "y"}],
            deadline_seconds=18.0,
        )

        self.assertEqual(text, "ok")
        openai_deadline = mock_openai.call_args.kwargs["deadline"]
        gemini_deadline = mock_gemini.call_args.kwargs["deadline"]
        self.assertLessEqual(openai_deadline, 9.5)
        self.assertLessEqual(gemini_deadline, 9.5)

    @patch("apps.chatbot.response_llm.synthesize_clinic_reply")
    def test_llm_failure_never_returns_raw_chunk_text(self, mock_synth):
        """Regression: on LLM failure, engine.py used to return an unedited,
        arbitrarily-truncated vector chunk (real production symptom: a
        policy document dumped verbatim, cut off mid-sentence) instead of
        the clean empty_rag_reply() fallback that already exists for this."""
        from apps.chatbot.engine import ChatEngine

        mock_synth.side_effect = ResponseLLMError("boom")
        clinic = type("C", (), {"name": "Acme", "phone": "555"})()
        raw_chunk = (
            "PATIENT AGREEMENT, FINANCIAL POLICIES & CLINICAL PROTOCOLS\n\n"
            "Acme Dental provides general, cosmetic, and orthodontic dental "
            "care. Patients are expected to arrive 10 minutes prior..."
        )

        text = ChatEngine()._generate_response(
            clinic=clinic,
            message="what types do you have",
            nlu=None,
            sql_rows=[],
            vector_rows=[{"score": 0.9, "heading": "Policy", "text": raw_chunk}],
            session=None,
        )

        self.assertNotIn("PATIENT AGREEMENT", text)
        self.assertEqual(text, empty_rag_reply(clinic))


class ComposeFromPlanFallbackTests(SimpleTestCase):
    """Regression: when the response LLM can't run (no vector context yet,
    or the request budget runs out before it's called), _compose_from_plan
    used to always fall back to the generic empty_rag_reply() apology even
    when sql_rows already had the answer — e.g. a pricing question would
    show a $450 service card while the text said "I couldn't find clinic-
    specific information... call us." It must prefer the SQL-grounded text
    instead, exactly like _generate_response's own exception-handler
    fallback already does."""

    def _plan(self):
        return ExecutionPlan(
            sql_tasks=["services"], vector_tasks=["clinic_documents"], use_response_llm=True
        )

    def _sql_rows(self):
        return [
            {
                "handler": "services_offered",
                "found": True,
                "rows": [{"name": "In-Office Laser Teeth Whitening", "price_cents": 45000}],
            }
        ]

    def _compose(self, **overrides):
        from apps.chatbot.engine import ChatEngine

        clinic = type("C", (), {"name": "Acme", "phone": "555"})()
        kwargs = dict(
            clinic=clinic,
            message="how much is teeth whitening",
            nlu=None,
            exec_plan=self._plan(),
            sql_rows=self._sql_rows(),
            vector_rows=[],
            session=None,
            booking_commit=False,
            suggested=[],
            guidance="",
            soft_medical=False,
            timings={},
        )
        kwargs.update(overrides)
        return ChatEngine()._compose_from_plan(**kwargs)

    def test_empty_vector_prefers_sql_over_generic_apology(self):
        text = self._compose(vector_rows=[])
        self.assertNotIn("couldn't find clinic-specific information", text)

    def test_generic_booking_does_not_claim_times_are_below(self):
        from apps.chatbot.planner import ExecutionPlan

        nlu = type("N", (), {"entities": type("E", (), {"date": None, "time": None})()})()
        text = self._compose(
            message="i would like to book an appointment",
            nlu=nlu,
            exec_plan=ExecutionPlan(booking=True),
            sql_rows=[],
            vector_rows=[],
            booking_commit=True,
        )
        self.assertNotIn("Choose a time below", text)
        self.assertNotIn("Pick a time below", text)
        self.assertIn("let's get you booked", text.lower())

    def test_budget_exhausted_prefers_sql_over_generic_apology(self):
        text = self._compose(
            vector_rows=[{"score": 0.9, "heading": "x", "text": "y"}],
            request_started=time.perf_counter() - 100,
            request_budget=20.0,
            min_llm_remaining=2.0,
        )
        self.assertNotIn("couldn't find clinic-specific information", text)
