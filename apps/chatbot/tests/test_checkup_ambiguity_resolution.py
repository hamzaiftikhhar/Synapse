"""Capability-family reliability (follow-up phase): a genuinely ambiguous
explicit capability ask must surface every plausible catalog match, never
silently commit to one.

Root cause (live-reproduced, real production log): "I need a checkup"
classified `services_offered`/`service_filter_mode="named"` with no
`entities.service` (NLU's own `reasoning_short` even guessed "matches
pediatric exam service" -- proof that field is not tied to execution, see
CLAUDE.md's warning against trusting an LLM's own free-text reasoning as
ground truth). This reached the Capability Resolver in `explicit`
context, whose prompt said "be decisive... do not hedge on an obvious
match" with no concept of genuine ambiguity. The resolver returned exactly
one candidate (Establish Patient Adult Physical, confidence 1.0) despite
the clinic also offering a Pediatric Well-Child Exam that is an equally
plausible "checkup" -- nothing in "I need a checkup" says adult or child.
`capability_routing_policy.decide_routing`'s explicit branch then took
only the single top candidate per type (by design, prior to this phase),
so the second option was silently discarded before the SQL layer ever
saw it.

Fixed at two points:
1. `_EXPLICIT_INSTRUCTIONS` (capability_resolver.py) now requires the
   model to return every equally-plausible candidate when nothing in the
   patient's wording favors one over another, and to stay decisive
   otherwise ("checkup for my son", "flu test", "stitches" all still
   resolve to exactly one candidate).
2. `decide_routing`'s explicit branch (capability_routing_policy.py) now
   takes every candidate of a given type, not just the first, mirroring
   the "concern" branch's existing "surface options, don't discard"
   philosophy. `services_offered`/`search_doctors` already accept
   multiple resolved ids via `id__in` and list every match -- no handler
   changes were needed.

Live-validated (this phase, real OpenAI calls against the real Horizon
catalog, see ROADMAP.md): bare "checkup" returned both Adult Physical and
Pediatric Well-Child Exam as separate candidates on 5/5 repeated real
calls after the fix; "I need a checkup for my son" (patient-type given)
and "flu test cost"/"I need stitches for a cut" (only one real catalog
item is plausible) stayed decisive to exactly one candidate on 5/5 runs
each -- proving the fix targets genuine ambiguity, not every explicit ask.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from django.test import TestCase

from apps.chatbot.booking.capability_resolver import (
    live_resolver_context_for_nlu,
    resolve_capability,
)
from apps.chatbot.booking.capability_routing_policy import decide_routing
from apps.chatbot.nlu.schemas import ExtractedEntities, Intent, NLUResult, ResolvedIds
from apps.chatbot.planner import ExecutionPlan, apply_capability_resolution
from apps.chatbot.sql_tool.base import SQLContext
from apps.chatbot.sql_tool.handlers.services import services_offered
from apps.clinics.models import Clinic
from apps.services.models import Service


def _nlu_result(intent: Intent, *, service_filter_mode: str = "none", **entity_kwargs) -> NLUResult:
    result = NLUResult(
        intent=intent,
        confidence=0.95,
        entities=ExtractedEntities(**entity_kwargs),
        resolved_ids=ResolvedIds(),
        service_filter_mode=service_filter_mode,
    )
    result.timings.classifier_source = "openai"
    return result


def _mock_llm(payload: dict):
    return patch(
        "apps.chatbot.booking.capability_resolver._call_response_llm",
        return_value=json.dumps(payload),
    )


class CheckupAmbiguityResolutionTests(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="checkup-ambiguity-clinic",
            name="Checkup Ambiguity Clinic",
            email="checkup-ambiguity@clinic.test",
            phone="+12125550003",
            timezone="America/New_York",
        )
        self.adult_physical = Service.objects.create(
            clinic=self.clinic,
            name="Establish Patient Adult Physical",
            price_cents=18500,
            duration_min=45,
            is_active=True,
        )
        self.pediatric_exam = Service.objects.create(
            clinic=self.clinic,
            name="Pediatric Well-Child Exam",
            price_cents=12000,
            duration_min=30,
            is_active=True,
        )

    def _run_chain(self, message: str, payload: dict) -> tuple[list[str], object]:
        nlu = _nlu_result(Intent.SERVICES_OFFERED, service_filter_mode="named")
        ctx = live_resolver_context_for_nlu(nlu, message)
        self.assertEqual(ctx, "explicit")
        with _mock_llm(payload):
            resolution = resolve_capability(self.clinic, message, context=ctx)
        decision = decide_routing(ctx, resolution)
        plan = apply_capability_resolution(
            ExecutionPlan(direct=False, sql_tasks=["services"], reason="planner_test"),
            decision=decision,
            was_unclaimed=False,
        )
        sql_ctx = SQLContext(
            clinic=self.clinic,
            nlu=nlu,
            message=message,
            resolved_service_ids=plan.resolved_service_ids,
            resolved_specialty_ids=plan.resolved_specialty_ids,
            capability_resolver_used=plan.capability_resolver_used,
            informational_service_candidates=plan.informational_service_candidates,
        )
        result = services_offered(sql_ctx)
        return plan.resolved_service_ids, result

    def test_bare_checkup_surfaces_both_adult_and_pediatric_never_picks_one_silently(self):
        payload = {
            "candidates": [
                {
                    "type": "service",
                    "id": str(self.adult_physical.id),
                    "confidence": 1.0,
                    "reasoning": "adult physical is an equally plausible checkup match",
                },
                {
                    "type": "service",
                    "id": str(self.pediatric_exam.id),
                    "confidence": 1.0,
                    "reasoning": "pediatric well-child exam is an equally plausible checkup match",
                },
            ]
        }
        resolved_ids, result = self._run_chain("I need a checkup", payload)
        self.assertEqual(
            set(resolved_ids), {str(self.adult_physical.id), str(self.pediatric_exam.id)}
        )
        self.assertTrue(result.found)
        returned_ids = {r["id"] for r in result.rows}
        self.assertEqual(
            returned_ids, {str(self.adult_physical.id), str(self.pediatric_exam.id)}
        )
        # Each option keeps its own real, distinct price -- the patient
        # can actually choose, not just see a generic combined answer.
        prices = {r["id"]: r["price"] for r in result.rows}
        self.assertEqual(prices[str(self.adult_physical.id)], "$185.00")
        self.assertEqual(prices[str(self.pediatric_exam.id)], "$120.00")

    def test_checkup_for_my_son_is_not_ambiguous_resolves_to_pediatric_only(self):
        """Patient-type given -- the resolver (live-validated 5/5) stays
        decisive; this test proves the routing/handler side doesn't
        introduce ambiguity on its own for a single-candidate response."""
        payload = {
            "candidates": [
                {
                    "type": "service",
                    "id": str(self.pediatric_exam.id),
                    "confidence": 1.0,
                    "reasoning": "explicitly for a son -- pediatric",
                }
            ]
        }
        resolved_ids, result = self._run_chain(
            "I need a checkup for my son", payload
        )
        self.assertEqual(resolved_ids, [str(self.pediatric_exam.id)])
        self.assertEqual(len(result.rows), 1)
        self.assertEqual(result.rows[0]["id"], str(self.pediatric_exam.id))
        # Single-row named-mode summary format, unaffected by this fix.
        self.assertIn("$120.00", result.summary)
