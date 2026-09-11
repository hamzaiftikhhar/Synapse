"""Router-inversion regressions from Horizon production transcript."""

from __future__ import annotations

from django.test import SimpleTestCase

from apps.chatbot.nlu.entity_extract import has_symptom_cues
from apps.chatbot.nlu.rules import try_rule_classify
from dataclasses import replace

from apps.chatbot.nlu.schemas import CatalogMatch, Intent, parse_nlu_payload
from apps.chatbot.routing.confidence import apply_confidence_policy
from apps.chatbot.routing.heuristics import apply_routing_heuristics
from apps.chatbot.routing.signals import (
    is_business_hours_query,
    is_service_list_query,
    match_services_in_message,
    service_filter_mode,
)


_HORIZON_SERVICES = [
    {"id": "1", "name": "Urgent Care Visit (Level 1 / Basic)"},
    {"id": "2", "name": "Establish Patient Adult Physical"},
    {"id": "3", "name": "Routine Blood Draw (Venipuncture)"},
    {"id": "4", "name": "Pediatric Well-Child Exam"},
]


class ServiceMatchHardeningTests(SimpleTestCase):
    def test_visit_token_does_not_match_urgent_care_visit(self):
        hits = match_services_in_message(
            "how many times we can visit a specialized doctor",
            _HORIZON_SERVICES,
        )
        self.assertEqual(hits, [])

    def test_urgent_care_list_query_returns_no_sku_hits(self):
        msg = "What are the urgent care your clinic provides?"
        self.assertTrue(is_service_list_query(msg))
        hits = match_services_in_message(msg, _HORIZON_SERVICES)
        self.assertEqual(hits, [])
        self.assertEqual(service_filter_mode(msg, hits), "none")

    def test_named_physical_still_matches(self):
        hits = match_services_in_message(
            "How much is it for Establish Patient Adult Physical",
            _HORIZON_SERVICES,
        )
        self.assertEqual(len(hits), 1)
        self.assertIn("Adult Physical", hits[0]["name"])

    def test_routine_alone_does_not_match_blood_draw(self):
        hits = match_services_in_message(
            "If I get my routine meds from your dispensary how does pricing work",
            _HORIZON_SERVICES,
        )
        self.assertEqual(hits, [])


class EmergencySafetyTests(SimpleTestCase):
    def test_chest_pressure_radiating_arm_is_emergency(self):
        msg = (
            "My husband has been complaining about this tight pressure in his chest "
            "that's radiating down his arm for the past hour. Can I bring him in "
            "for a quick walk-in right now?"
        )
        self.assertTrue(has_symptom_cues(msg))
        self.assertFalse(is_business_hours_query(msg))
        hit = try_rule_classify(msg, tier="safety")
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit["intent"], Intent.EMERGENCY.value)
        self.assertTrue(hit["is_emergency"])

    def test_hours_rule_blocked_when_symptom_cues(self):
        msg = "chest hurts are you open right now"
        self.assertTrue(has_symptom_cues(msg))
        self.assertFalse(is_business_hours_query(msg))


class CancelFeeAndTimeoutTests(SimpleTestCase):
    def test_cancel_fee_is_faq_not_pricing(self):
        hit = try_rule_classify(
            "am I gonna get charged a fee for canceling less than 24 hours away",
            tier="strong",
        )
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit["intent"], Intent.FAQ.value)
        self.assertTrue(hit["needs_vector"])

    def test_unknown_plus_service_hit_does_not_keep_sql_at_low_confidence(self):
        nlu = parse_nlu_payload(
            {
                "intent": "unknown",
                "confidence": 0.5,
                "clarification_needed": True,
            }
        )
        nlu = apply_routing_heuristics(
            message="how many times we can visit a specialized doctor",
            nlu=nlu,
            document_catalog=[],
            service_catalog=_HORIZON_SERVICES,
        )
        policy = apply_confidence_policy(
            nlu,
            has_catalog=False,
            service_hit=False,
            knowledge_q=False,
        )
        self.assertNotEqual(policy.nlu.intent, Intent.SERVICES_OFFERED)
        self.assertFalse(policy.nlu.needs_sql)

    def test_sulphuric_acid_timeout_does_not_become_services(self):
        nlu = parse_nlu_payload(
            {
                "intent": "unknown",
                "confidence": 0.5,
                "clarification_needed": True,
            }
        )
        out = apply_routing_heuristics(
            message=(
                "if we put 55 kg of meat in Sulphuric acid how much time "
                "it will take to completely dissolve"
            ),
            nlu=nlu,
            document_catalog=[],
            service_catalog=_HORIZON_SERVICES,
        )
        self.assertNotIn(out.intent, {Intent.SERVICES_OFFERED, Intent.PRICING})
        self.assertFalse(out.needs_sql)


class NLUResultFieldPreservationTests(SimpleTestCase):
    """Severe, previously-undetected live bug (ROADMAP.md): both
    apply_routing_heuristics (routing/heuristics.py::_result) and
    apply_confidence_policy (routing/confidence.py) rebuild NLUResult
    field-by-field instead of via dataclasses.replace() -- so
    catalog_match (Phase 2) and medical_question_mode were both silently
    reset to their inert defaults on every single real ChatEngine.process()
    call, since both functions always run in the real pipeline between
    the raw NLU parse and the code that consumes those fields (planner.py,
    sql_tool handlers). Confirmed live: a real "Do you have a cardiology
    specialist?" call correctly produced catalog_match=no_match from the
    LLM, but by the time discovery.py's resolver saw it, it had already
    been wiped back to not_applicable -- masked in earlier verification
    only because those manual scripts happened to call the NLU/resolver
    functions directly, skipping apply_routing_heuristics/
    apply_confidence_policy entirely. These tests exist so adding a THIRD
    such field in the future doesn't silently repeat this exact bug --
    the fix must be maintained in both places, not just added once and
    forgotten as a passing test elsewhere masks the regression."""

    def _nlu_with_both_fields(self, **overrides):
        nlu = parse_nlu_payload(
            {"intent": "medical_question", "medical_question_mode": "definitional", **overrides}
        )
        return replace(
            nlu,
            catalog_match=CatalogMatch(
                status="matched", match_type="specialty", catalog_id="abc-123"
            ),
        )

    def test_apply_routing_heuristics_preserves_catalog_match(self):
        nlu = self._nlu_with_both_fields()
        out = apply_routing_heuristics(
            message="What is hypothyroidism?",
            nlu=nlu,
            document_catalog=[],
            service_catalog=[],
        )
        self.assertEqual(out.catalog_match.status, "matched")
        self.assertEqual(out.catalog_match.catalog_id, "abc-123")

    def test_apply_routing_heuristics_preserves_medical_question_mode(self):
        nlu = self._nlu_with_both_fields()
        out = apply_routing_heuristics(
            message="What is hypothyroidism?",
            nlu=nlu,
            document_catalog=[],
            service_catalog=[],
        )
        self.assertEqual(out.medical_question_mode, "definitional")

    def test_apply_confidence_policy_preserves_catalog_match(self):
        nlu = self._nlu_with_both_fields(confidence=0.9)
        policy = apply_confidence_policy(
            nlu, has_catalog=False, service_hit=False, knowledge_q=False
        )
        self.assertEqual(policy.nlu.catalog_match.status, "matched")
        self.assertEqual(policy.nlu.catalog_match.catalog_id, "abc-123")

    def test_apply_confidence_policy_preserves_medical_question_mode(self):
        nlu = self._nlu_with_both_fields(confidence=0.9)
        policy = apply_confidence_policy(
            nlu, has_catalog=False, service_hit=False, knowledge_q=False
        )
        self.assertEqual(policy.nlu.medical_question_mode, "definitional")

    def test_both_fields_survive_the_full_real_chain(self):
        """The real pipeline order: apply_routing_heuristics, then
        apply_confidence_policy -- both must preserve both fields end to
        end, not just individually."""
        nlu = self._nlu_with_both_fields(confidence=0.9)
        nlu = apply_routing_heuristics(
            message="What is hypothyroidism?",
            nlu=nlu,
            document_catalog=[],
            service_catalog=[],
        )
        policy = apply_confidence_policy(
            nlu, has_catalog=False, service_hit=False, knowledge_q=False
        )
        self.assertEqual(policy.nlu.catalog_match.status, "matched")
        self.assertEqual(policy.nlu.medical_question_mode, "definitional")
