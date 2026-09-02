"""Horizon golden regressions for Small-LLM-first router inversion."""

from __future__ import annotations

from django.test import SimpleTestCase

from apps.chatbot.nlu.rules import try_rule_classify
from apps.chatbot.nlu.schemas import Intent, parse_nlu_payload
from apps.chatbot.routing.confidence import apply_confidence_policy
from apps.chatbot.routing.heuristics import apply_routing_heuristics
from apps.chatbot.routing.lanes import Lane, resolve_lane
from apps.chatbot.routing.signals import (
    is_business_hours_query,
    is_service_list_query,
    looks_like_knowledge_question,
    match_services_in_message,
    service_filter_mode,
)
from apps.chatbot.nlu.schemas import Route
from apps.chatbot.sql_tool.formatter import format_sql_results


_SERVICES = (
    {"id": "s1", "name": "Adult Cleaning, Exam & X-Rays"},
    {"id": "s5", "name": "Urgent Care Visit (Level 1 / Basic)"},
    {"id": "s7", "name": "Blood Draw / Routine Labs"},
    {"id": "s8", "name": "Adult Physical Exam"},
)

_DOCS = (
    {
        "id": "d1",
        "title": "Patient Agreement",
        "routing_summary": "Cancellation fees, deposits, membership refunds, arrive early.",
        "routing_keywords": [
            "cancellation",
            "fee",
            "deposit",
            "refund",
            "membership",
            "arrive",
            "policy",
        ],
    },
)


class HorizonGoldenSafetyTests(SimpleTestCase):
    def test_chest_pressure_arm_is_emergency_not_hours(self):
        msg = "chest pressure into my arm for an hour right now"
        hit = try_rule_classify(msg, tier="safety")
        self.assertIsNotNone(hit)
        self.assertTrue(hit["is_emergency"])
        self.assertFalse(is_business_hours_query(msg))

    def test_chest_hurts_open_is_emergency_via_safety(self):
        # Safety gate must fire before any hours path
        hit = try_rule_classify(
            "my chest hurts are you open",
            tier="safety",
        )
        self.assertIsNotNone(hit)
        self.assertEqual(hit["intent"], Intent.EMERGENCY.value)


class HorizonGoldenServiceMatchTests(SimpleTestCase):
    def test_visit_specialized_doctor_no_urgent_care_sku(self):
        hits = match_services_in_message(
            "how many times visit specialized doctor", list(_SERVICES)
        )
        self.assertEqual(hits, [])

    def test_urgent_care_list_query_filter_none(self):
        msg = "What urgent care do you provide?"
        self.assertTrue(is_service_list_query(msg))
        hits = match_services_in_message(msg, list(_SERVICES))
        self.assertEqual(hits, [])
        self.assertEqual(service_filter_mode(msg, hits), "none")

    def test_dispensary_does_not_match_blood_draw_routine(self):
        hits = match_services_in_message(
            "how much for dispensary meds pricing", list(_SERVICES)
        )
        names = [h["name"] for h in hits]
        self.assertNotIn("Blood Draw / Routine Labs", names)


class HorizonGoldenPolicyTests(SimpleTestCase):
    def test_cancel_fee_is_knowledge_not_pricing(self):
        msg = "what is the cancel fee if under 24 hours?"
        self.assertTrue(looks_like_knowledge_question(msg))
        # Strong legacy FAQ still wins over pricing when policy frames present
        hit = try_rule_classify(msg, tier="strong")
        if hit is not None:
            self.assertEqual(hit["intent"], Intent.FAQ.value)
            self.assertTrue(hit["needs_vector"])

    def test_cancel_fee_heuristics_prefer_vector_with_docs(self):
        msg = "Cancel & under 24h fee?"
        nlu = parse_nlu_payload(
            {
                "intent": "pricing",
                "confidence": 0.86,
                "needs_sql": True,
            }
        )
        out = apply_routing_heuristics(
            message=msg,
            nlu=nlu,
            document_catalog=list(_DOCS),
            service_catalog=list(_SERVICES),
        )
        # Intent is no longer rewritten to FAQ here (Phase: FAQ overwrite
        # removal) — build_execution_plan attaches the vector task from
        # knowledge_q/topic independently, so preserving the real intent
        # (pricing) keeps _INTENT_SQL_TASKS's matching SQL task available too.
        self.assertEqual(out.intent, Intent.PRICING)
        self.assertTrue(out.needs_vector)
        self.assertFalse(out.needs_sql)


class HorizonGoldenTimeoutTests(SimpleTestCase):
    def test_timeout_unknown_does_not_keep_sql_on_service_hit(self):
        nlu = parse_nlu_payload(
            {
                "intent": "unknown",
                "confidence": 0.35,
                "clarification_needed": True,
            }
        )
        out = apply_routing_heuristics(
            message="how many times visit specialized doctor",
            nlu=nlu,
            document_catalog=list(_DOCS),
            service_catalog=list(_SERVICES),
        )
        policy = apply_confidence_policy(
            out,
            has_catalog=True,
            service_hit=False,
            knowledge_q=False,
        )
        self.assertTrue(policy.prefer_clarify or policy.nlu.clarification_needed)
        self.assertFalse(policy.nlu.needs_sql)
        lane = resolve_lane(
            nlu=policy.nlu,
            route=Route.CLARIFY,
            is_booking_intent=False,
            soft_medical=False,
            needs_vector=False,
            doc_match=False,
            has_catalog=True,
            prefer_vector=policy.prefer_vector,
            prefer_clarify=policy.prefer_clarify,
        )
        self.assertIn(lane, {Lane.CLARIFY, Lane.DIRECT})


class HorizonGoldenCancelAuthTests(SimpleTestCase):
    def test_unauth_cancel_copy_is_patient_friendly(self):
        text = format_sql_results(
            [
                {
                    "handler": "patient_appointments",
                    "found": False,
                    "rows": [],
                    "summary": (
                        "To cancel or reschedule, please verify your phone number first "
                        "so I can pull up your appointments. You can also start booking "
                        "a new visit if you prefer."
                    ),
                    "meta": {"requires_auth": True},
                }
            ]
        )
        self.assertIn("verify", text.lower())
        self.assertNotIn("not authenticated", text.lower())


class HorizonGoldenSulphuricTests(SimpleTestCase):
    def test_sulphuric_acid_not_forced_to_services(self):
        nlu = parse_nlu_payload(
            {
                "intent": "unknown",
                "confidence": 0.35,
                "clarification_needed": True,
            }
        )
        out = apply_routing_heuristics(
            message="how much time for sulphuric acid to dissolve",
            nlu=nlu,
            document_catalog=list(_DOCS),
            service_catalog=list(_SERVICES),
        )
        self.assertNotEqual(out.intent, Intent.SERVICES_OFFERED)
        self.assertNotEqual(out.intent, Intent.PRICING)
        self.assertFalse(out.needs_sql)
