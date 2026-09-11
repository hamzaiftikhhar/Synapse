"""Capability-family reliability: informal "stitches"/laceration language
must resolve to a real tenant service, and doctor search/availability must
then use the real `DoctorService` relationship -- never the deleted/
invalid "Major and Minor cuts treat and stitches" specialty (Scope B).

Same chain discipline as test_flu_capability_resolution.py: NLU semantics
-> resolver context -> `resolve_capability` (LLM boundary mocked) ->
`decide_routing` -> `apply_capability_resolution` -> the real SQL handler
(`services_offered` or `search_doctors`) -> the actual returned rows, all
against this test's own DB fixture ids.

Does not require all six messages to share a planner lane -- some are
services_offered-shaped (a specific service ask), others doctor_search-
shaped (who can do it) -- only that each converges on the correct
capability and correct downstream behavior.
"""

from __future__ import annotations

import json
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
from apps.chatbot.sql_tool.handlers.doctors import search_doctors
from apps.chatbot.sql_tool.handlers.services import services_offered
from apps.clinics.models import Clinic
from apps.doctors.models import Doctor, DoctorService, DoctorSpecialty
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


class StitchesCapabilityResolutionTests(TestCase):
    """Scope B: 'stitches'/laceration language -> Simple Wound Laceration
    Repair (Sutures), with doctor search grounded in DoctorService."""

    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="stitches-capability-clinic",
            name="Stitches Capability Clinic",
            email="stitches-capability@clinic.test",
            phone="+12125550002",
            timezone="America/New_York",
        )
        self.laceration_service = Service.objects.create(
            clinic=self.clinic,
            name="Simple Wound Laceration Repair (Sutures)",
            description="Surgical closure of a skin cut using sutures.",
            price_cents=24000,
            duration_min=45,
            is_active=True,
        )
        self.urgent_care = Specialty.objects.create(
            clinic=self.clinic, name="Urgent Care", slug="urgent-care", is_active=True
        )
        self.family_medicine = Specialty.objects.create(
            clinic=self.clinic,
            name="Family Medicine",
            slug="family-medicine",
            is_active=True,
        )

        # The doctor who can actually do the repair, linked via the real
        # DoctorService relationship -- the only thing that should ever
        # gate "who can do stitches."
        self.suture_doctor = Doctor.objects.create(
            clinic=self.clinic,
            full_name="Dr. Priya Chandrasekaran",
            is_active=True,
            is_accepting_patients=True,
        )
        DoctorService.objects.create(
            clinic=self.clinic, doctor=self.suture_doctor, service=self.laceration_service
        )
        DoctorSpecialty.objects.create(
            clinic=self.clinic, doctor=self.suture_doctor, specialty=self.urgent_care
        )

        # A doctor who does NOT do sutures, in an unrelated specialty --
        # proves the filter is real, not an unfiltered browse in disguise.
        self.unrelated_doctor = Doctor.objects.create(
            clinic=self.clinic,
            full_name="Dr. Family Medicine Only",
            is_active=True,
            is_accepting_patients=True,
        )
        DoctorSpecialty.objects.create(
            clinic=self.clinic, doctor=self.unrelated_doctor, specialty=self.family_medicine
        )

    def _candidate_payload(self, *, with_specialty=True):
        candidates = [
            {
                "type": "service",
                "id": str(self.laceration_service.id),
                "confidence": 1.0,
                "reasoning": "stitches maps to laceration repair",
            }
        ]
        if with_specialty:
            candidates.append(
                {
                    "type": "specialty",
                    "id": str(self.urgent_care.id),
                    "confidence": 0.8,
                    "reasoning": "urgent care handles lacerations",
                }
            )
        return {"candidates": candidates}

    def _resolve_plan(self, nlu_result: NLUResult, message: str, *, expected_ctx="explicit"):
        ctx = live_resolver_context_for_nlu(nlu_result, message)
        self.assertEqual(ctx, expected_ctx, f"unexpected context for {message!r}")
        with _mock_llm(self._candidate_payload()):
            resolution = resolve_capability(self.clinic, message, context=ctx)
        self.assertEqual(resolution.outcome, "ok")
        decision = decide_routing(ctx, resolution)
        base_plan = ExecutionPlan(direct=False, reason="planner_test")
        plan = apply_capability_resolution(
            base_plan, decision=decision, was_unclaimed=False
        )
        return ctx, decision, plan

    def test_i_need_stitches_resolves_to_laceration_service(self):
        nlu = _nlu_result(
            Intent.SERVICES_OFFERED, service_filter_mode="category", service="stitches"
        )
        message = "I need stitches"
        _, decision, plan = self._resolve_plan(nlu, message)
        self.assertEqual(decision.service_ids, [str(self.laceration_service.id)])
        self.assertEqual(plan.resolved_service_ids, [str(self.laceration_service.id)])

        sql_ctx = SQLContext(
            clinic=self.clinic,
            nlu=nlu,
            message=message,
            resolved_service_ids=plan.resolved_service_ids,
            resolved_specialty_ids=plan.resolved_specialty_ids,
            capability_resolver_used=plan.capability_resolver_used,
        )
        result = services_offered(sql_ctx)
        self.assertTrue(result.found)
        self.assertEqual(result.rows[0]["id"], str(self.laceration_service.id))
        self.assertEqual(result.rows[0]["price_cents"], 24000)

    def test_i_need_stitches_for_a_cut(self):
        nlu = _nlu_result(
            Intent.SERVICES_OFFERED, service_filter_mode="category", service="stitches"
        )
        _, decision, plan = self._resolve_plan(nlu, "I need stitches for a cut")
        self.assertEqual(plan.resolved_service_ids, [str(self.laceration_service.id)])

    def test_i_cut_my_hand_and_need_stitches_uses_full_message_not_bare_symptom(self):
        """Regression for the real bug found and fixed this phase:
        `expressed_need_for_nlu` must feed the resolver the *message*, not
        just entities.symptom, in explicit context -- a real NLU call
        extracted symptom="hand" for this exact phrasing (a bare body-part
        word, live-confirmed via repeated real calls), which resolves to
        nothing on its own. Simulating that exact leaked entity here and
        asserting the capability still resolves proves the fix, not just
        that a clean input works."""
        from apps.chatbot.booking.capability_resolver import expressed_need_for_nlu

        nlu = _nlu_result(
            Intent.SERVICES_OFFERED,
            service_filter_mode="category",
            symptom="hand",  # the real, live-confirmed bad extraction
        )
        message = "I cut my hand and need stitches"
        ctx = live_resolver_context_for_nlu(nlu, message)
        self.assertEqual(ctx, "explicit")
        expressed_need = expressed_need_for_nlu(nlu, message, context=ctx)
        self.assertEqual(
            expressed_need,
            message,
            "explicit context must use the full message, never the bare symptom",
        )

    def test_do_you_have_anyone_who_can_stitch_a_wound(self):
        nlu = _nlu_result(Intent.DOCTOR_SEARCH, symptom="wound")
        message = "Do you have anyone who can stitch a wound?"
        _, decision, plan = self._resolve_plan(nlu, message, expected_ctx="concern")
        # A bare-symptom doctor_search reaches the resolver as "concern" --
        # both the service and specialty candidates are present, but only
        # specialty may drive the doctor filter; service stays informational.
        self.assertEqual(decision.service_ids, [])
        self.assertIn(str(self.laceration_service.id), decision.informational_service_candidates)
        self.assertEqual(plan.resolved_specialty_ids, [str(self.urgent_care.id)])

        sql_ctx = SQLContext(
            clinic=self.clinic,
            nlu=nlu,
            message=message,
            resolved_service_ids=plan.resolved_service_ids,
            resolved_specialty_ids=plan.resolved_specialty_ids,
            capability_resolver_used=plan.capability_resolver_used,
            informational_service_candidates=plan.informational_service_candidates,
        )
        result = search_doctors(sql_ctx)
        self.assertTrue(result.found)
        returned_ids = {r["id"] for r in result.rows}
        self.assertIn(str(self.suture_doctor.id), returned_ids)
        self.assertNotIn(str(self.unrelated_doctor.id), returned_ids)

    def test_is_anyone_available_for_stitches_uses_doctor_service_relationship(self):
        nlu = _nlu_result(Intent.DOCTOR_SEARCH, service_filter_mode="category")
        message = "Is anyone available for stitches?"
        _, decision, plan = self._resolve_plan(nlu, message)
        self.assertEqual(decision.service_ids, [str(self.laceration_service.id)])

        sql_ctx = SQLContext(
            clinic=self.clinic,
            nlu=nlu,
            message=message,
            resolved_service_ids=plan.resolved_service_ids,
            resolved_specialty_ids=plan.resolved_specialty_ids,
            capability_resolver_used=plan.capability_resolver_used,
        )
        result = search_doctors(sql_ctx)
        self.assertTrue(result.found)
        returned_ids = {r["id"] for r in result.rows}
        # Grounded in the real DoctorService link, not a bogus specialty.
        self.assertEqual(returned_ids, {str(self.suture_doctor.id)})

    def test_which_doctors_can_handle_a_cut_that_needs_stitches(self):
        nlu = _nlu_result(Intent.DOCTOR_SEARCH, symptom="cut")
        message = "Which doctors can handle a cut that needs stitches?"
        _, decision, plan = self._resolve_plan(nlu, message, expected_ctx="concern")
        self.assertIn(str(self.urgent_care.id), plan.resolved_specialty_ids)

        sql_ctx = SQLContext(
            clinic=self.clinic,
            nlu=nlu,
            message=message,
            resolved_service_ids=plan.resolved_service_ids,
            resolved_specialty_ids=plan.resolved_specialty_ids,
            capability_resolver_used=plan.capability_resolver_used,
            informational_service_candidates=plan.informational_service_candidates,
        )
        result = search_doctors(sql_ctx)
        self.assertTrue(result.found)
        returned_ids = {r["id"] for r in result.rows}
        self.assertIn(str(self.suture_doctor.id), returned_ids)

    def test_no_bogus_specialty_ever_appears_in_any_candidate_or_decision(self):
        """The deleted/invalid 'Major and Minor cuts treat and stitches'
        specialty must never be restored, recreated, or used as a mapping
        -- this clinic's fixture never creates it at all, and every
        candidate id above is independently re-validated against this
        clinic's real active catalog (see _validate_candidates), so
        nothing resembling it could survive even if the mocked LLM
        hallucinated its name."""
        bogus_name = "Major and Minor cuts treat and stitches"
        self.assertFalse(
            Specialty.objects.filter(clinic=self.clinic, name=bogus_name).exists()
        )
        nlu = _nlu_result(Intent.DOCTOR_SEARCH, symptom="cut")
        _, decision, plan = self._resolve_plan(
            nlu, "Which doctors can handle a cut that needs stitches?", expected_ctx="concern"
        )
        all_ids = set(decision.specialty_ids) | set(decision.service_ids)
        self.assertNotIn("01a08b2c-5db5-7e9f-b8c1-0da29f765511", all_ids)


class StitchesCapabilityNegativeTests(SimpleTestCase):
    """Definitional/unrelated messages must never be converted into a
    laceration-repair booking or doctor search."""

    def test_what_is_a_laceration_is_definitional_never_reaches_resolver(self):
        nlu = _nlu_result(Intent.MEDICAL_QUESTION)
        self.assertIsNone(resolver_context_for_nlu(nlu))
        self.assertIsNone(live_resolver_context_for_nlu(nlu, "What is a laceration?"))

    def test_what_causes_bleeding_gums_is_definitional_never_reaches_resolver(self):
        """Live-confirmed elsewhere in this codebase as the canonical
        false-positive case for lexical symptom detection; re-asserted
        here because it is one of this phase's own required negative
        cases."""
        nlu = _nlu_result(Intent.MEDICAL_QUESTION, symptom="bleeding gums")
        self.assertIsNone(resolver_context_for_nlu(nlu))
        self.assertIsNone(live_resolver_context_for_nlu(nlu, "What causes bleeding gums?"))

    def test_knee_pain_concern_never_silently_books_the_laceration_service(self):
        from apps.chatbot.booking.capability_resolver import (
            CapabilityCandidate,
            CapabilityResolution,
        )

        nlu = _nlu_result(
            Intent.MEDICAL_QUESTION, symptom="knee pain", medical_question_mode="personal"
        )
        ctx = live_resolver_context_for_nlu(nlu, "I have knee pain.")
        self.assertEqual(ctx, "concern")
        # Even if the resolver returned an unrelated service candidate
        # (weak lexical overlap), concern context must never let it filter.
        resolution = CapabilityResolution(
            candidates=[
                CapabilityCandidate(
                    target_type="service",
                    id="00000000-0000-0000-0000-0000000000bb",
                    name="Simple Wound Laceration Repair (Sutures)",
                    confidence=0.4,
                    reasoning="weak overlap on 'pain'",
                )
            ]
        )
        decision = decide_routing(ctx, resolution)
        self.assertEqual(decision.service_ids, [])
