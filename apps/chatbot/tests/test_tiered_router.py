"""Tests for tiered chat router: lanes, rules, heuristics, SQL honesty."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.chatbot.nlu.decision import DecisionEngine
from apps.chatbot.nlu.rules import try_rule_classify
from apps.chatbot.nlu.schemas import Intent, Route, parse_nlu_payload
from apps.chatbot.routing.heuristics import apply_routing_heuristics
from apps.chatbot.routing.lanes import Lane, resolve_lane
from apps.chatbot.sql_tool.formatter import (
    EMPTY_AVAILABILITY,
    EMPTY_DOCTORS,
    format_sql_results,
)


class RulesLaneTests(SimpleTestCase):
    def test_find_doctor_is_sql_only(self):
        hit = try_rule_classify("Help me find a doctor", tier="strong")
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit["intent"], Intent.DOCTOR_SEARCH.value)
        self.assertTrue(hit["needs_sql"])
        self.assertFalse(hit["needs_vector"])
        self.assertFalse(hit["needs_llm"])

    def test_hours_is_sql_only(self):
        hit = try_rule_classify("What are your hours?", tier="strong")
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit["intent"], Intent.CLINIC_HOURS.value)
        self.assertTrue(hit["needs_sql"])
        self.assertFalse(hit["needs_vector"])
        self.assertFalse(hit["needs_llm"])

    def test_insurance_is_sql_only(self):
        hit = try_rule_classify("Do you accept Aetna?", tier="strong")
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit["intent"], Intent.INSURANCE_ACCEPTED.value)
        self.assertTrue(hit["needs_sql"])
        self.assertFalse(hit["needs_vector"])
        self.assertFalse(hit["needs_llm"])

    def test_off_topic_food_fast(self):
        hit = try_rule_classify("I want pizza", tier="strong")
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit["intent"], Intent.OFF_TOPIC.value)
        self.assertTrue(hit["can_respond_directly"] or hit["is_off_topic"])

    def test_cancellation_policy_faq_vector(self):
        hit = try_rule_classify(
            "What is your cancellation policy for appointments?",
            tier="strong",
        )
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit["intent"], Intent.FAQ.value)
        self.assertTrue(hit["needs_vector"])
        self.assertTrue(hit["needs_llm"])


class HeuristicsTests(SimpleTestCase):
    def test_heuristics_force_sql_for_doctors(self):
        nlu = parse_nlu_payload(
            {
                "intent": "unknown",
                "confidence": 0.5,
                "needs_llm": True,
                "needs_vector": True,
            }
        )
        out = apply_routing_heuristics(
            message="Help me find a doctor",
            nlu=nlu,
            document_catalog=[],
        )
        self.assertEqual(out.intent, Intent.DOCTOR_SEARCH)
        self.assertTrue(out.needs_sql)
        self.assertFalse(out.needs_vector)
        self.assertFalse(out.needs_llm)

    def test_heuristics_force_vector_on_policy_catalog_hit(self):
        catalog = [
            {
                "id": "1",
                "title": "Booking Policy",
                "routing_summary": "Advance booking windows and cancellation rules.",
                "routing_keywords": ["cancel", "cancellation", "policy"],
            }
        ]
        nlu = parse_nlu_payload(
            {
                "intent": "unknown",
                "confidence": 0.6,
                "needs_sql": False,
            }
        )
        out = apply_routing_heuristics(
            message="What is your cancellation policy?",
            nlu=nlu,
            document_catalog=catalog,
        )
        self.assertTrue(out.needs_vector)
        self.assertTrue(out.needs_llm)
        self.assertEqual(out.intent, Intent.FAQ)

    def test_decision_drops_needs_llm_without_vector(self):
        nlu = parse_nlu_payload(
            {
                "intent": "doctor_search",
                "confidence": 0.9,
                "needs_sql": True,
                "needs_llm": True,
                "needs_vector": False,
            }
        )
        decision = DecisionEngine.decide(nlu)
        self.assertFalse(decision.needs_llm)
        self.assertEqual(decision.route, Route.SQL_ONLY)


class ResolveLaneTests(SimpleTestCase):
    def _nlu(self, **kwargs):
        return parse_nlu_payload({"intent": "greeting", "confidence": 0.99, **kwargs})

    def test_doctor_search_sql_fast(self):
        nlu = self._nlu(
            intent="doctor_search",
            needs_sql=True,
            needs_vector=False,
            needs_llm=False,
        )
        lane = resolve_lane(
            nlu=nlu,
            route=Route.SQL_ONLY,
            is_booking_intent=False,
            soft_medical=False,
            needs_vector=False,
            doc_match=False,
        )
        self.assertEqual(lane, Lane.SQL_FAST)

    def test_faq_vector_rag(self):
        nlu = self._nlu(
            intent="faq",
            needs_vector=True,
            needs_llm=True,
        )
        lane = resolve_lane(
            nlu=nlu,
            route=Route.VECTOR_LLM,
            is_booking_intent=False,
            soft_medical=False,
            needs_vector=True,
            doc_match=True,
        )
        self.assertEqual(lane, Lane.VECTOR_RAG)

    def test_booking_lane(self):
        nlu = self._nlu(intent="book_appointment", needs_sql=True)
        lane = resolve_lane(
            nlu=nlu,
            route=Route.SQL_LLM,
            is_booking_intent=True,
            soft_medical=False,
            needs_vector=False,
            doc_match=False,
        )
        self.assertEqual(lane, Lane.BOOKING)

    def test_clarify_lane(self):
        nlu = self._nlu(
            intent="unknown",
            clarification_needed=True,
            clarification_question="Could you clarify?",
        )
        lane = resolve_lane(
            nlu=nlu,
            route=Route.CLARIFY,
            is_booking_intent=False,
            soft_medical=False,
            needs_vector=False,
            doc_match=False,
        )
        self.assertEqual(lane, Lane.CLARIFY)


class SqlHonestyTests(SimpleTestCase):
    def test_empty_availability_fixed_copy(self):
        text = format_sql_results(
            [
                {
                    "handler": "doctor_availability",
                    "found": False,
                    "rows": [],
                    "summary": "No available slots found on Friday.",
                }
            ]
        )
        self.assertIn("No available", text)
        self.assertNotIn("call the clinic", text.lower())

    def test_empty_doctors_fixed_copy(self):
        text = format_sql_results(
            [{"handler": "search_doctors", "found": False, "rows": [], "summary": ""}]
        )
        self.assertEqual(text, EMPTY_DOCTORS)

    def test_empty_availability_generic(self):
        text = format_sql_results(
            [
                {
                    "handler": "doctor_availability",
                    "found": False,
                    "rows": [],
                    "summary": "DB query failed.",
                }
            ]
        )
        self.assertEqual(text, EMPTY_AVAILABILITY)


class EngineLaneIsolationTests(SimpleTestCase):
    """SQL lane must never call synthesize_clinic_reply; RAG lane must."""

    def _clinic(self):
        return SimpleNamespace(
            id="c1",
            name="Acme",
            phone="555",
            slug="acme-cardiology",
        )

    @patch("apps.chatbot.routing.build_document_catalog", return_value=[])
    @patch("apps.chatbot.response_llm.synthesize_clinic_reply")
    @patch("apps.chatbot.engine.ChatEngine._run_sql")
    @patch("apps.chatbot.nlu.intent_entity.IntentEntityService.analyze")
    def test_sql_lane_never_calls_large_llm(
        self, mock_analyze, mock_sql, mock_synth, _catalog
    ):
        from apps.chatbot.engine import ChatEngine

        mock_analyze.return_value = parse_nlu_payload(
            {
                "intent": "doctor_search",
                "confidence": 0.95,
                "needs_sql": True,
                "needs_vector": False,
                "needs_llm": False,
            }
        )
        mock_sql.return_value = [
            {
                "handler": "search_doctors",
                "found": True,
                "rows": [
                    {
                        "id": "1",
                        "full_name": "Dr. Test",
                        "specialties": ["Cardiology"],
                        "title": "MD",
                        "bio": "",
                    }
                ],
                "summary": "Found 1",
            }
        ]

        result = ChatEngine().process(
            clinic=self._clinic(),
            message="Help me find a doctor",
            session=None,
        )
        mock_synth.assert_not_called()
        self.assertEqual(result.lane, Lane.SQL_FAST.value)
        self.assertFalse(result.needs_llm)
        self.assertIn("Dr. Test", result.response)

    @patch(
        "apps.chatbot.routing.build_document_catalog",
        return_value=[
            {
                "id": "d1",
                "title": "Booking Policy",
                "routing_summary": "Cancellation policy for appointments.",
                "routing_keywords": ["cancel", "cancellation", "policy"],
            }
        ],
    )
    @patch(
        "apps.chatbot.response_llm.synthesize_clinic_reply",
        return_value="Policy says 24h.",
    )
    @patch(
        "apps.chatbot.engine.ChatEngine._run_vector",
        return_value=[
            {"score": 0.9, "heading": "Cancel", "text": "Cancel 24h ahead."}
        ],
    )
    @patch("apps.chatbot.nlu.intent_entity.IntentEntityService.analyze")
    def test_rag_lane_calls_large_llm(
        self, mock_analyze, _vector, mock_synth, _catalog
    ):
        from apps.chatbot.engine import ChatEngine

        mock_analyze.return_value = parse_nlu_payload(
            {
                "intent": "faq",
                "confidence": 0.9,
                "needs_vector": True,
                "needs_llm": True,
            }
        )

        result = ChatEngine().process(
            clinic=self._clinic(),
            message="What is your cancellation policy?",
            session=None,
        )
        mock_synth.assert_called_once()
        self.assertEqual(result.lane, Lane.VECTOR_RAG.value)
        self.assertTrue(result.needs_llm)
        self.assertIn("Policy", result.response)
