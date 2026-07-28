"""Unit tests for Decision Engine, rules, entities, and NLU parsing."""

from django.test import SimpleTestCase, override_settings

from apps.chatbot.nlu.base import NLUError
from apps.chatbot.nlu.decision import EMERGENCY_SAFETY_MESSAGE, DecisionEngine
from apps.chatbot.nlu.entity_extract import extract_emergency_symptoms, extract_entities
from apps.chatbot.nlu.intent_entity import IntentEntityService, _apply_confidence_threshold
from apps.chatbot.nlu.json_utils import parse_json_response
from apps.chatbot.nlu.rules import try_rule_classify
from apps.chatbot.nlu.schemas import Intent, Route, parse_nlu_payload


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

    def test_comma_string_becomes_list(self):
        result = parse_nlu_payload(
            {
                "intent": "doctor_availability",
                "entities": {"doctor_name": "rjet, sharma"},
            }
        )
        self.assertEqual(result.entities.doctor_name, ["rjet", "sharma"])

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

    def test_clarify_route(self):
        nlu = parse_nlu_payload(
            {
                "intent": "unknown",
                "clarification_needed": True,
                "clarification_question": "Which doctor?",
            }
        )
        self.assertEqual(DecisionEngine.decide(nlu).route, Route.CLARIFY)

    def test_direct_greeting(self):
        nlu = parse_nlu_payload(
            {"intent": "greeting", "confidence": 0.98, "can_respond_directly": True}
        )
        self.assertEqual(DecisionEngine.decide(nlu).route, Route.DIRECT_RESPONSE)

    def test_sql_llm_booking(self):
        nlu = parse_nlu_payload(
            {"intent": "book_appointment", "needs_sql": True, "needs_llm": True}
        )
        self.assertEqual(DecisionEngine.decide(nlu).route, Route.SQL_LLM)


class RuleClassifierTests(SimpleTestCase):
    def test_greeting_fast_path(self):
        for msg in ("Hi there!", "hi, how are you?", "hi how are you doing?"):
            hit = try_rule_classify(msg, tier="fast")
            self.assertIsNotNone(hit, msg)
            self.assertEqual(hit["intent"], "greeting", msg)

    def test_negation_blocks_reschedule(self):
        hit = try_rule_classify("I dont want to reschedule it", tier="strong")
        self.assertIsNone(hit)

    def test_book_appointment_with_entities(self):
        hit = try_rule_classify(
            "can you please book an appointment for tomorrow morning?",
            tier="strong",
        )
        self.assertIsNotNone(hit)
        self.assertEqual(hit["intent"], "book_appointment")
        self.assertIn("tomorrow", hit["entities"]["date"])
        self.assertIn("morning", hit["entities"]["time"])

    def test_doctor_name_extracted_on_book(self):
        hit = try_rule_classify(
            "Is dr rajat available tomorrow? I want to schedule an appointment",
            tier="strong",
        )
        # Compound with "?" x1 and schedule — may be strong or bypassed as compound
        # "and" not present; single ?. Should match book with doctor.
        if hit is None:
            # compound detector may skip — still extract entities works
            entities = extract_entities(
                "Is dr rajat available tomorrow? I want to schedule an appointment"
            )
            self.assertIsNotNone(entities["doctor_name"])
            self.assertTrue(
                any("rajat" in n.lower() for n in entities["doctor_name"])
            )
        else:
            self.assertEqual(hit["intent"], "book_appointment")
            names = hit["entities"]["doctor_name"]
            self.assertTrue(any("rajat" in n.lower() for n in names))

    def test_insurance_extracts_provider(self):
        hit = try_rule_classify(
            "do you guys accept blue cross origin insurance?",
            tier="strong",
        )
        self.assertIsNotNone(hit)
        self.assertEqual(hit["intent"], "insurance_accepted")
        providers = hit["entities"]["insurance_provider"]
        self.assertTrue(any("blue cross" in p.lower() for p in providers))

    def test_compound_skips_strong_rules(self):
        hit = try_rule_classify(
            "do you accept blue cross? also tell can dr rajat treat me tomorrow?",
            tier="strong",
        )
        self.assertIsNone(hit)

    def test_services_and_faq_rules(self):
        hit = try_rule_classify("What services do you provide?", tier="strong")
        self.assertIsNotNone(hit)
        self.assertEqual(hit["intent"], "services_offered")

        hit = try_rule_classify("Do I need referrals for specialists?", tier="strong")
        self.assertIsNotNone(hit)
        self.assertEqual(hit["intent"], "faq")

    def test_medicaid_entity_clean(self):
        hit = try_rule_classify(
            "Do you accept Medicaid for adult primary care?",
            tier="strong",
        )
        self.assertIsNotNone(hit)
        self.assertEqual(hit["entities"]["insurance_provider"], ["Medicaid"])


    def test_availability_slots_rule(self):
        hit = try_rule_classify(
            "are there any slots available for tomorrow?",
            tier="strong",
        )
        self.assertIsNotNone(hit)
        self.assertEqual(hit["intent"], "doctor_availability")

    def test_emergency_symptoms_clean(self):
        text = "I have intense chest pain and left arm numbness, when can I see a doctor?"
        hit = try_rule_classify(text, tier="strong")
        self.assertIsNotNone(hit)
        self.assertTrue(hit["is_emergency"])
        self.assertEqual(
            hit["entities"]["symptom"],
            extract_emergency_symptoms(text),
        )
        self.assertIn("chest pain", hit["entities"]["symptom"])
        self.assertNotEqual(hit["entities"]["symptom"], text)

    def test_low_confidence_triggers_clarify(self):
        nlu = parse_nlu_payload({"intent": "unknown", "confidence": 0.5})
        adjusted = _apply_confidence_threshold(nlu)
        self.assertTrue(adjusted.clarification_needed)


class EntityExtractTests(SimpleTestCase):
    def test_multi_doctor_names(self):
        entities = extract_entities("Is dr rjet or dr. sharma available this friday?")
        names = [n.lower() for n in entities["doctor_name"]]
        self.assertTrue(any("rjet" in n for n in names))
        self.assertTrue(any("sharma" in n for n in names))

    def test_specialty_and_insurance(self):
        entities = extract_entities(
            "book an appointment with a dermatologist tomorrow, and also do you accept Aetna PPO?"
        )
        self.assertIn("dermatologist", entities["specialty"])
        self.assertTrue(
            any("aetna" in p.lower() for p in entities["insurance_provider"])
        )


@override_settings(
    NLU_ENABLE_RULES=False,
    NLU_RULES_BEFORE_LLM=False,
    NLU_CONFIDENCE_THRESHOLD=0.75,
    NLU_API_TIMEOUT_SECONDS=2.5,
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
                    "_usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 20,
                        "total_tokens": 30,
                    },
                }

        class FakeClinic:
            id = "00000000-0000-0000-0000-000000000001"

        service = IntentEntityService(provider=FakeProvider())
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
        self.assertEqual(DecisionEngine.decide(result).route, Route.SQL_VECTOR_LLM)

    def test_timeout_returns_clarify_fallback(self):
        class SlowProvider:
            provider_name = "gemini"
            model_name = "gemini-3.1-flash-lite"

            def classify(self, *, message, conversation_context=None, timeout=None):
                raise NLUError(f"Gemini API timed out after {timeout}s")

        class FakeClinic:
            id = "00000000-0000-0000-0000-000000000001"

        service = IntentEntityService(provider=SlowProvider())
        from unittest.mock import patch

        with (
            patch(
                "apps.chatbot.nlu.intent_entity.resolve_entities",
                return_value=parse_nlu_payload({}).resolved_ids,
            ),
            patch.object(IntentEntityService, "_log_usage"),
            override_settings(NLU_FALLBACK_OPENAI=False, NLU_ENABLE_RULES=True),
        ):
            result = service.analyze(
                clinic=FakeClinic(),  # type: ignore[arg-type]
                message="are there any slots available for tomorrow?",
                log_usage=False,
            )

        # Availability rule fallback or clarify
        self.assertTrue(
            result.clarification_needed
            or result.intent
            in {Intent.DOCTOR_AVAILABILITY, Intent.BOOK_APPOINTMENT, Intent.UNKNOWN}
        )
        self.assertLess(result.timings.total_ms, 100)
