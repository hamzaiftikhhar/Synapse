"""Unit tests for Decision Engine, rules, and NLU parsing (no live LLM)."""

from django.test import SimpleTestCase, override_settings

from apps.chatbot.nlu.decision import EMERGENCY_SAFETY_MESSAGE, DecisionEngine
from apps.chatbot.nlu.json_utils import parse_json_response
from apps.chatbot.nlu.rules import try_rule_classify
from apps.chatbot.nlu.schemas import Intent, Route, parse_nlu_payload
from apps.chatbot.nlu.base import NLUError
from apps.chatbot.nlu.intent_entity import IntentEntityService, _apply_confidence_threshold


class ParseNLUPayloadTests(SimpleTestCase):
    def test_unknown_intent_fallback(self):
        result = parse_nlu_payload({"intent": "not_a_real_intent", "confidence": 0.5})
        self.assertEqual(result.intent, Intent.UNKNOWN)

    def test_parses_entities_and_flags(self):
        result = parse_nlu_payload(
            {
                "intent": "book_appointment",
                "secondary_intents": ["doctor_availability"],
                "confidence": 0.91,
                "entities": {"specialty": "cardiology", "date": "Tuesday"},
                "needs_sql": True,
                "needs_llm": True,
            },
            provider="gemini",
            model="gemini-1.5-flash",
        )
        self.assertEqual(result.intent, Intent.BOOK_APPOINTMENT)
        self.assertEqual(result.entities.specialty, "cardiology")
        self.assertTrue(result.needs_sql)
        self.assertEqual(result.provider, "gemini")

    def test_confidence_clamped(self):
        result = parse_nlu_payload({"intent": "greeting", "confidence": 5})
        self.assertEqual(result.confidence, 1.0)


class JsonUtilsTests(SimpleTestCase):
    def test_strips_markdown_fence(self):
        data = parse_json_response('```json\n{"intent": "greeting"}\n```')
        self.assertEqual(data["intent"], "greeting")

    def test_empty_raises(self):
        with self.assertRaises(NLUError):
            parse_json_response("   ")


class DecisionEngineTests(SimpleTestCase):
    def test_emergency_route(self):
        nlu = parse_nlu_payload(
            {
                "intent": "emergency",
                "confidence": 0.99,
                "is_emergency": True,
                "can_respond_directly": True,
            }
        )
        decision = DecisionEngine.decide(nlu)
        self.assertEqual(decision.route, Route.EMERGENCY)
        self.assertEqual(decision.safety_message, EMERGENCY_SAFETY_MESSAGE)
        self.assertFalse(decision.needs_sql)

    def test_clarify_route(self):
        nlu = parse_nlu_payload(
            {
                "intent": "unknown",
                "clarification_needed": True,
                "clarification_question": "Which doctor?",
            }
        )
        decision = DecisionEngine.decide(nlu)
        self.assertEqual(decision.route, Route.CLARIFY)

    def test_direct_greeting(self):
        nlu = parse_nlu_payload(
            {
                "intent": "greeting",
                "confidence": 0.98,
                "can_respond_directly": True,
            }
        )
        decision = DecisionEngine.decide(nlu)
        self.assertEqual(decision.route, Route.DIRECT_RESPONSE)

    def test_sql_llm_booking(self):
        nlu = parse_nlu_payload(
            {
                "intent": "book_appointment",
                "needs_sql": True,
                "needs_llm": True,
            }
        )
        decision = DecisionEngine.decide(nlu)
        self.assertEqual(decision.route, Route.SQL_LLM)

    def test_vector_llm_faq(self):
        nlu = parse_nlu_payload(
            {
                "intent": "faq",
                "needs_vector": True,
                "needs_llm": True,
            }
        )
        decision = DecisionEngine.decide(nlu)
        self.assertEqual(decision.route, Route.VECTOR_LLM)

    def test_sql_vector_llm(self):
        nlu = parse_nlu_payload(
            {
                "intent": "insurance_accepted",
                "needs_sql": True,
                "needs_vector": True,
                "needs_llm": True,
            }
        )
        decision = DecisionEngine.decide(nlu)
        self.assertEqual(decision.route, Route.SQL_VECTOR_LLM)

    def test_sql_only(self):
        nlu = parse_nlu_payload({"intent": "doctor_search", "needs_sql": True})
        self.assertEqual(DecisionEngine.decide(nlu).route, Route.SQL_ONLY)

    def test_vector_only(self):
        nlu = parse_nlu_payload({"intent": "faq", "needs_vector": True})
        self.assertEqual(DecisionEngine.decide(nlu).route, Route.VECTOR_ONLY)

    def test_llm_only(self):
        nlu = parse_nlu_payload({"intent": "handoff_human", "needs_llm": True})
        self.assertEqual(DecisionEngine.decide(nlu).route, Route.LLM_ONLY)


class RuleClassifierTests(SimpleTestCase):
    def test_greeting_fast_path(self):
        hit = try_rule_classify("Hi there!", tier="fast")
        self.assertIsNotNone(hit)
        self.assertEqual(hit["intent"], "greeting")
        self.assertTrue(hit["can_respond_directly"])

    def test_book_appointment_strong_rule(self):
        hit = try_rule_classify(
            "can you please book an appointment for tomorrow morning?",
            tier="strong",
        )
        self.assertIsNotNone(hit)
        self.assertEqual(hit["intent"], "book_appointment")
        self.assertEqual(hit["entities"]["date"], "tomorrow")
        self.assertEqual(hit["entities"]["time"], "morning")

    def test_low_confidence_triggers_clarify(self):
        nlu = parse_nlu_payload({"intent": "unknown", "confidence": 0.5})
        adjusted = _apply_confidence_threshold(nlu)
        self.assertTrue(adjusted.clarification_needed)


@override_settings(
    NLU_ENABLE_RULES=False,
    NLU_RULES_BEFORE_LLM=False,
    NLU_CONFIDENCE_THRESHOLD=0.75,
)
class IntentEntityServiceMockedTests(SimpleTestCase):
    def test_analyze_with_fake_provider(self):
        class FakeProvider:
            provider_name = "gemini"
            model_name = "gemini-1.5-flash"

            def classify(self, *, message, conversation_context=None, timeout=None):
                return {
                    "intent": "clinic_hours",
                    "confidence": 0.9,
                    "entities": {"date": "Saturday"},
                    "needs_sql": True,
                    "needs_vector": True,
                    "needs_llm": True,
                    "_usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
                }

        class FakeClinic:
            id = "00000000-0000-0000-0000-000000000001"

        service = IntentEntityService(provider=FakeProvider())

        # Avoid ORM resolvers / usage log in this unit test
        from unittest.mock import patch

        with (
            patch(
                "apps.chatbot.nlu.intent_entity.resolve_entities",
                return_value=parse_nlu_payload({}).resolved_ids,
            ),
            patch.object(IntentEntityService, "_log_usage"),
        ):
            result = service.analyze(
                clinic=FakeClinic(),  # type: ignore[arg-type]
                message="What are your Saturday hours?",
                log_usage=False,
            )

        self.assertEqual(result.intent, Intent.CLINIC_HOURS)
        decision = DecisionEngine.decide(result)
        self.assertEqual(decision.route, Route.SQL_VECTOR_LLM)
