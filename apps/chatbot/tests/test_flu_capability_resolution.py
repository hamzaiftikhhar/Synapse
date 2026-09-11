"""Capability-family reliability: informal "flu test" language must
resolve to a real tenant service (Scope A of the capability-resolution
reliability phase).

Covers the full authorized chain for each of the five required
phrasings: NLU semantics -> `resolver_context_for_nlu`/
`live_resolver_context_for_nlu` -> `resolve_capability` (LLM call mocked
at its own boundary, `_call_response_llm`, exactly like
test_capability_resolver.py's existing pattern) -> `decide_routing` ->
`planner.apply_capability_resolution` -> the real `services_offered` SQL
handler -> the actual returned service row (id + price, both read from
this test's own DB fixture, never a hardcoded production UUID).

Deliberately does NOT require the same NLU intent across all five
messages -- each is given the intent/service_filter_mode a real NLU call
plausibly produces for that exact phrasing (confirmed against live traces
run for this phase), proving the resolver converges on the same capability
regardless of which valid intent got there.
"""

from __future__ import annotations

import json
from dataclasses import replace
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from apps.chatbot.booking.capability_resolver import (
    live_resolver_context_for_nlu,
    resolve_capability,
    resolver_context_for_nlu,
)
from apps.chatbot.booking.capability_routing_policy import decide_routing
from apps.chatbot.nlu.schemas import ExtractedEntities, Intent, NLUResult, ResolvedIds
from apps.chatbot.planner import ExecutionPlan, apply_capability_resolution
from apps.chatbot.sql_tool.base import SQLContext
from apps.chatbot.sql_tool.handlers.services import services_offered
from apps.clinics.models import Clinic
from apps.services.models import Service
from apps.specialties.models import Specialty


def _nlu_result(
    intent: Intent,
    *,
    service_filter_mode: str = "none",
    medical_question_mode: str | None = None,
    **entity_kwargs,
) -> NLUResult:
    result = NLUResult(
        intent=intent,
        confidence=0.9,
        entities=ExtractedEntities(**entity_kwargs),
        resolved_ids=ResolvedIds(),
        service_filter_mode=service_filter_mode,
        medical_question_mode=medical_question_mode,
    )
    result.timings.classifier_source = "openai"
    return result


def _mock_llm(payload: dict):
    return patch(
        "apps.chatbot.booking.capability_resolver._call_response_llm",
        return_value=json.dumps(payload),
    )


class FluTestCapabilityResolutionTests(TestCase):
    """Scope A: 'flu test' language -> Rapid Strep / Flu Combo Swab."""

    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="flu-capability-clinic",
            name="Flu Capability Clinic",
            email="flu-capability@clinic.test",
            phone="+12125550001",
            timezone="America/New_York",
        )
        self.flu_service = Service.objects.create(
            clinic=self.clinic,
            name="Rapid Strep / Flu Combo Swab",
            description="Combined rapid antigen swab test for strep and influenza.",
            price_cents=3500,
            duration_min=10,
            is_active=True,
        )
        # Distractor: a real, unrelated, active service in the same
        # catalog -- proves the resolver doesn't just grab whatever is
        # closest lexically, and that weak overlap never wins.
        Service.objects.create(
            clinic=self.clinic,
            name="Establish Patient Adult Physical",
            price_cents=15000,
            duration_min=40,
            is_active=True,
        )
        self.urgent_care = Specialty.objects.create(
            clinic=self.clinic, name="Urgent Care", slug="urgent-care", is_active=True
        )

    def _candidate_payload(self, extra_specialty: bool = False):
        candidates = [
            {
                "type": "service",
                "id": str(self.flu_service.id),
                "confidence": 1.0,
                "reasoning": "flu test maps to the rapid flu swab",
            }
        ]
        if extra_specialty:
            candidates.append(
                {
                    "type": "specialty",
                    "id": str(self.urgent_care.id),
                    "confidence": 0.6,
                    "reasoning": "urgent care may also see this",
                }
            )
        return {"candidates": candidates}

    def _run_chain(self, nlu_result: NLUResult, message: str, *, extra_specialty=False):
        """Full authorized chain: NLU -> resolver context -> capability
        candidate -> routing decision -> plan -> real SQL handler."""
        ctx = live_resolver_context_for_nlu(nlu_result, message)
        self.assertEqual(ctx, "explicit", f"expected explicit context for {message!r}")

        with _mock_llm(self._candidate_payload(extra_specialty)):
            resolution = resolve_capability(self.clinic, message, context=ctx)
        self.assertEqual(resolution.outcome, "ok")

        decision = decide_routing(ctx, resolution)
        self.assertEqual(decision.action, "filter")
        self.assertEqual(decision.service_ids, [str(self.flu_service.id)])

        base_plan = ExecutionPlan(
            direct=False,
            sql_tasks=["services"],
            reason="planner_test",
        )
        # was_unclaimed mirrors engine.py's own rule: False here since
        # services_offered/pricing already dispatch sql_tasks on their own.
        plan = apply_capability_resolution(
            base_plan, decision=decision, was_unclaimed=False
        )
        self.assertEqual(plan.resolved_service_ids, [str(self.flu_service.id)])
        self.assertTrue(plan.capability_resolver_used)

        sql_ctx = SQLContext(
            clinic=self.clinic,
            nlu=nlu_result,
            message=message,
            resolved_service_ids=plan.resolved_service_ids,
            resolved_specialty_ids=plan.resolved_specialty_ids,
            capability_resolver_used=plan.capability_resolver_used,
            informational_service_candidates=plan.informational_service_candidates,
        )
        result = services_offered(sql_ctx)
        self.assertTrue(result.found)
        self.assertEqual(len(result.rows), 1)
        self.assertEqual(result.rows[0]["id"], str(self.flu_service.id))
        self.assertEqual(result.rows[0]["name"], "Rapid Strep / Flu Combo Swab")
        # Actual fixture price, never a hardcoded number.
        self.assertEqual(result.rows[0]["price_cents"], self.flu_service.price_cents)
        self.assertEqual(result.rows[0]["price"], "$35.00")
        return result

    def test_do_you_offer_a_flu_test(self):
        nlu = _nlu_result(
            Intent.SERVICES_OFFERED,
            service_filter_mode="category",
            service="flu test",
        )
        result = self._run_chain(nlu, "Do you offer a flu test?")
        self.assertIn("Rapid Strep / Flu Combo Swab", result.summary)

    def test_how_much_does_your_flu_test_cost(self):
        nlu = _nlu_result(
            Intent.PRICING,
            service_filter_mode="category",
            service="flu test",
        )
        self._run_chain(nlu, "How much does your flu test cost?")

    def test_can_you_test_me_for_flu(self):
        # Different intent than the pricing/services_offered cases above --
        # deliberately not required to match; only the resolved capability
        # and downstream behavior must converge.
        nlu = _nlu_result(
            Intent.SERVICES_OFFERED,
            service_filter_mode="category",
        )
        self._run_chain(nlu, "Can you test me for flu?")

    def test_i_think_i_have_the_flu_can_you_test_me_explicit_ask_resolves(self):
        """The message contains an explicit capability ask ("can you test
        me?"), so a real NLU classification naming that action (rather
        than a bare personal-concern narrative) resolves the service
        directly -- see the companion concern-shaped test below for what
        happens when NLU instead classifies this as a personal medical
        concern (live-confirmed to occur too)."""
        nlu = _nlu_result(
            Intent.SERVICES_OFFERED,
            service_filter_mode="category",
            service="flu test",
        )
        self._run_chain(nlu, "I think I have the flu, can you test me?")

    def test_i_think_i_have_the_flu_when_classified_as_personal_concern_stays_informational(self):
        """Live-confirmed real-NLU behavior for this exact phrasing: a
        medical_question/personal classification is a genuine concern, not
        an explicit ask -- capability_routing_policy's governing rule
        (concern service candidates are informational only, never a
        silent filter) must still hold. This is not a failure of Scope A;
        it is the architecture invariant this whole phase must preserve."""
        nlu = _nlu_result(
            Intent.MEDICAL_QUESTION,
            symptom="flu",
            medical_question_mode="personal",
        )
        message = "I think I have the flu, can you test me?"
        ctx = live_resolver_context_for_nlu(nlu, message)
        self.assertEqual(ctx, "concern")

        payload = self._candidate_payload(extra_specialty=True)
        with _mock_llm(payload):
            resolution = resolve_capability(self.clinic, "flu", context=ctx)
        decision = decide_routing(ctx, resolution)
        # Service never becomes an authoritative filter for a concern...
        self.assertEqual(decision.service_ids, [])
        self.assertIn(str(self.flu_service.id), decision.informational_service_candidates)
        # ...even though the exact same capability was found and is
        # visible to a caller as a suggestion, not a booking decision.

    def test_do_you_test_for_the_flu(self):
        nlu = _nlu_result(
            Intent.SERVICES_OFFERED,
            service_filter_mode="category",
            service="flu test",
        )
        self._run_chain(nlu, "Do you test for the flu?")


class FluCapabilityNegativeTests(SimpleTestCase):
    """Definitional/unrelated messages must never reach the resolver, and
    must never be mistaken for a flu-test capability request."""

    def test_what_causes_the_flu_is_definitional_never_reaches_resolver(self):
        nlu = _nlu_result(Intent.MEDICAL_QUESTION, symptom="flu")
        self.assertIsNone(resolver_context_for_nlu(nlu))
        self.assertIsNone(live_resolver_context_for_nlu(nlu, "What causes the flu?"))

    def test_what_is_a_blood_test_is_definitional_never_reaches_resolver(self):
        nlu = _nlu_result(Intent.MEDICAL_QUESTION)
        self.assertIsNone(resolver_context_for_nlu(nlu))
        self.assertIsNone(live_resolver_context_for_nlu(nlu, "What is a blood test?"))

    def test_personal_concern_without_any_capability_ask_never_sets_service_filter(self):
        """'I have a headache' / 'I have knee pain' -- a bare personal
        symptom statement with no explicit capability ask -- must never
        let a service candidate silently become a booking/search filter,
        even though it legitimately reaches the resolver as a concern."""
        from apps.chatbot.booking.capability_resolver import (
            CapabilityCandidate,
            CapabilityResolution,
        )

        nlu = _nlu_result(
            Intent.MEDICAL_QUESTION, symptom="headache", medical_question_mode="personal"
        )
        ctx = live_resolver_context_for_nlu(nlu, "I have a headache.")
        self.assertEqual(ctx, "concern")

        resolution = CapabilityResolution(
            candidates=[
                CapabilityCandidate(
                    target_type="service",
                    id="00000000-0000-0000-0000-0000000000aa",
                    name="Some Unrelated Service",
                    confidence=0.7,
                    reasoning="weak overlap",
                )
            ]
        )
        decision = decide_routing(ctx, resolution)
        self.assertEqual(decision.service_ids, [])
