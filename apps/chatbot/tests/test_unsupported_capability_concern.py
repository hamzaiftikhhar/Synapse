"""Capability-family reliability (follow-up phase): a concern naming a
capability this clinic structurally does not provide (organ transplant,
chemotherapy, major surgery, dialysis, ICU care, radiation therapy) must
produce an honest "we don't have that here" decline -- never a doctor
list dressed up as an endorsement.

Root cause (live-reproduced, real production log): "do you treat the
heart transplant" classified `medical_question`/`personal` (entities.
symptom="heart transplant" is a lexical artifact of an existing, separate
"any body-part/illness phrase always sets symptom" NLU rule) and reached
the Capability Resolver as a `concern`. Before this phase, the resolver's
own concern-mode prompt let the model rank a general primary-care
specialty as "potentially relevant" via a "may be involved in ongoing
management" rationale -- Internal Medicine at 0.80 confidence, Family
Medicine at 0.60, for a literal organ transplant. `decide_routing`'s
concern branch (by design, see capability_routing_policy.py's own
docstring) takes every specialty candidate with no confidence cutoff, so
this became an authoritative doctor-search filter and returned 4 real
doctors framed as "may be a good fit" -- implying the clinic performs
heart transplants.

Fixed at the prompt level (`_CONCERN_INSTRUCTIONS`/`_SYSTEM_PROMPT` in
capability_resolver.py), not by adding a confidence threshold to
`decide_routing` (that module's own docstring records a deliberate,
evidenced decision against using confidence as a threshold, for an
unrelated reason -- linguistic certainty of the ask, not relevance-
worthiness -- and this phase does not relitigate that). The prompt now
requires the model to return an empty candidates array whenever the
concern names or implies hospital-level/tertiary/specialist-surgical care
this type of clinic does not provide, reusing the *existing*
`decide_routing`: `if not resolution.candidates: action="decline"` path
-- no new state, no new field, no confidence math.

Live-validated (this phase, real OpenAI calls against the real Horizon
catalog, see ROADMAP.md for the full record): "heart transplant",
"chemotherapy", and "I need dialysis" each returned an empty candidates
array in concern context on 5/5 repeated real calls after the prompt fix
(vs. non-empty, wrong specialty candidates before it); legitimate concerns
("I cut my hand", "my knee hurts", "I think I have the flu") were
unaffected, still correctly resolving to the real, appropriate specialty/
service on 5/5 runs each.

This test file covers the deterministic Python half only (the LLM
boundary is mocked, matching test_capability_resolver.py's existing
pattern) -- the prompt's actual real-language behavior is the live
evidence above and in ROADMAP.md, not re-provable in a mocked unit test.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from apps.chatbot.booking.capability_resolver import (
    _CONCERN_INSTRUCTIONS,
    _SYSTEM_PROMPT,
    live_resolver_context_for_nlu,
    resolve_capability,
)
from apps.chatbot.booking.capability_routing_policy import decide_routing
from apps.chatbot.engine import ChatEngine
from apps.chatbot.nlu.schemas import ExtractedEntities, Intent, NLUResult, ResolvedIds
from apps.chatbot.planner import ExecutionPlan, apply_capability_resolution
from apps.chatbot.sql_tool.base import SQLContext
from apps.chatbot.sql_tool.handlers.doctors import search_doctors
from apps.clinics.models import Clinic
from apps.doctors.models import Doctor, DoctorSpecialty
from apps.specialties.models import Specialty


def _nlu_result(
    intent: Intent,
    *,
    medical_question_mode: str | None = None,
    **entity_kwargs,
) -> NLUResult:
    result = NLUResult(
        intent=intent,
        confidence=0.85,
        entities=ExtractedEntities(**entity_kwargs),
        resolved_ids=ResolvedIds(),
        service_filter_mode="none",
        medical_question_mode=medical_question_mode,
    )
    result.timings.classifier_source = "openai"
    return result


def _mock_llm(payload: dict):
    return patch(
        "apps.chatbot.booking.capability_resolver._call_response_llm",
        return_value=json.dumps(payload),
    )


class ConcernPromptTripwireTests(SimpleTestCase):
    """Cheap, fast guard against silently reverting the prompt fix -- not
    a substitute for the live evidence above, but catches an accidental
    deletion of the hard rule immediately instead of only via the next
    live-validation pass."""

    def test_concern_instructions_forbid_tertiary_care_rationalization(self):
        self.assertIn("hospital-level", _CONCERN_INSTRUCTIONS)
        self.assertIn("organ transplant", _CONCERN_INSTRUCTIONS)

    def test_system_prompt_forbids_tangential_relevance(self):
        self.assertIn("directly give the patient meaningful care", _SYSTEM_PROMPT)


class UnsupportedConcernIntegrationTests(TestCase):
    """Full authorized chain for the exact reproduced failure, with the
    LLM boundary mocked to return what the fixed prompt now reliably
    returns live (empty candidates) -- proving the *Python* side of the
    fix (decide_routing -> apply_capability_resolution ->
    _capability_not_offered_reply) behaves correctly given that input."""

    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="unsupported-concern-clinic",
            name="Unsupported Concern Clinic",
            email="unsupported@clinic.test",
            phone="+12125550002",
            timezone="America/New_York",
        )
        self.family_medicine = Specialty.objects.create(
            clinic=self.clinic,
            name="Family Medicine",
            slug="family-medicine",
            is_active=True,
        )
        self.doctor = Doctor.objects.create(
            clinic=self.clinic,
            full_name="Dr. Test Rostova",
            title="MD",
            is_active=True,
        )
        DoctorSpecialty.objects.create(
            clinic=self.clinic, doctor=self.doctor, specialty=self.family_medicine
        )

    def _resolve_and_route(self, nlu: NLUResult, message: str, expressed_need: str):
        ctx = live_resolver_context_for_nlu(nlu, message)
        self.assertEqual(ctx, "concern", f"expected concern context for {message!r}")
        with _mock_llm({"candidates": []}):
            resolution = resolve_capability(self.clinic, expressed_need, context=ctx)
        self.assertEqual(resolution.outcome, "ok")
        decision = decide_routing(ctx, resolution)
        return decision

    def test_heart_transplant_concern_is_an_honest_decline_not_a_doctor_list(self):
        nlu = _nlu_result(
            Intent.MEDICAL_QUESTION,
            symptom="heart transplant",
            medical_question_mode="personal",
        )
        message = "do you treat the heart transplant"
        decision = self._resolve_and_route(nlu, message, "heart transplant")
        self.assertEqual(decision.action, "decline")
        self.assertEqual(decision.specialty_ids, [])

        base_plan = ExecutionPlan(direct=False, direct_mode="soft_medical", reason="planner_test")
        plan = apply_capability_resolution(base_plan, decision=decision, was_unclaimed=True)
        self.assertEqual(plan.direct_mode, "capability_not_offered")
        self.assertEqual(plan.sql_tasks, [])
        self.assertEqual(plan.resolved_specialty_ids, [])

        # The actual response text a patient would see -- no doctors, no
        # implication the clinic performs heart transplants.
        response = ChatEngine()._capability_not_offered_reply(
            self.clinic, plan.informational_service_candidates
        )
        self.assertIn("don't have a specialist for that", response)
        self.assertNotIn("Family Medicine", response)

    def test_chemotherapy_concern_is_also_an_honest_decline(self):
        nlu = _nlu_result(
            Intent.MEDICAL_QUESTION,
            symptom="chemotherapy",
            medical_question_mode="personal",
        )
        decision = self._resolve_and_route(
            nlu, "do you offer chemotherapy", "chemotherapy"
        )
        self.assertEqual(decision.action, "decline")
        self.assertEqual(decision.specialty_ids, [])

    def test_legitimate_concern_still_reaches_the_real_doctor_unaffected(self):
        """Regression guard: the fix must not overcorrect into declining
        every concern -- an ordinary concern this clinic can actually
        address must still resolve to a real doctor via the specialty
        filter, exactly as before this phase."""
        nlu = _nlu_result(
            Intent.MEDICAL_QUESTION,
            symptom="knee pain",
            medical_question_mode="personal",
        )
        with _mock_llm(
            {
                "candidates": [
                    {
                        "type": "specialty",
                        "id": str(self.family_medicine.id),
                        "confidence": 0.9,
                        "reasoning": "ordinary primary care fits a knee concern",
                    }
                ]
            }
        ):
            resolution = resolve_capability(self.clinic, "knee pain", context="concern")
        decision = decide_routing("concern", resolution)
        self.assertEqual(decision.action, "filter")
        self.assertEqual(decision.specialty_ids, [str(self.family_medicine.id)])

        base_plan = ExecutionPlan(direct=False, direct_mode="soft_medical", reason="planner_test")
        plan = apply_capability_resolution(base_plan, decision=decision, was_unclaimed=True)
        self.assertEqual(plan.sql_tasks, ["doctors"])
        self.assertEqual(plan.resolved_specialty_ids, [str(self.family_medicine.id)])

        sql_ctx = SQLContext(
            clinic=self.clinic,
            nlu=nlu,
            message="my knee hurts",
            resolved_specialty_ids=plan.resolved_specialty_ids,
            capability_resolver_used=plan.capability_resolver_used,
        )
        result = search_doctors(sql_ctx)
        self.assertTrue(result.found)
        self.assertEqual(result.rows[0]["id"], str(self.doctor.id))
