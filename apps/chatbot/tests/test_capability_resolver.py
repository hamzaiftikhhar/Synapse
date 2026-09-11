"""capability_resolver.py — Phase A isolation tests.

Covers only the deterministic Python half (validation, catalog scoping,
empty-input handling) with the LLM call mocked. The real-language behavior
of the LLM half is evaluated separately by the diagnostic management
command (run_capability_resolver_eval), not asserted here as pass/fail
since no threshold/expected-output contract exists yet for that half.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from apps.chatbot.booking.capability_resolver import (
    expressed_need_for_nlu,
    is_nlu_degraded,
    live_resolver_context_for_nlu,
    resolve_capability,
    resolver_context_for_nlu,
)
from apps.chatbot.nlu.schemas import ExtractedEntities, Intent, NLUResult, ResolvedIds
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
    return NLUResult(
        intent=intent,
        confidence=0.9,
        entities=ExtractedEntities(**entity_kwargs),
        resolved_ids=ResolvedIds(),
        service_filter_mode=service_filter_mode,
        medical_question_mode=medical_question_mode,
    )


class ResolverContextForNluTests(SimpleTestCase):
    """Shared by shadow mode and the live vertical slice -- one definition
    so the two can never decide "is this relevant" differently."""

    def test_services_offered_named_ask_is_explicit(self):
        result = _nlu_result(
            Intent.SERVICES_OFFERED, service_filter_mode="named", service="Whitening"
        )
        self.assertEqual(resolver_context_for_nlu(result), "explicit")

    def test_pricing_category_ask_is_explicit(self):
        result = _nlu_result(Intent.PRICING, service_filter_mode="category")
        self.assertEqual(resolver_context_for_nlu(result), "explicit")

    def test_services_offered_genuine_browse_is_skipped(self):
        """Live-confirmed bug found running the full suite: "what services
        do you offer" (service_filter_mode == "none", the deliberate-browse
        default, no entity) must not fire the resolver at all -- the
        existing unfiltered SQL browse already handles this correctly."""
        result = _nlu_result(Intent.SERVICES_OFFERED)
        self.assertIsNone(resolver_context_for_nlu(result))

    def test_doctor_search_with_nothing_at_all_is_skipped(self):
        """Live-confirmed bug found running the full suite: a plain "Help
        me find a doctor" (doctor_search, every entity null) must not fire
        the resolver -- the existing unfiltered browse already works, and
        this exact case broke a SimpleTestCase (DB-forbidden) test that
        assumed a bare doctor_search never touches the database."""
        result = _nlu_result(Intent.DOCTOR_SEARCH)
        self.assertIsNone(resolver_context_for_nlu(result))

    def test_doctor_search_with_bare_symptom_is_concern(self):
        result = _nlu_result(Intent.DOCTOR_SEARCH, symptom="yellow teeth")
        self.assertEqual(resolver_context_for_nlu(result), "concern")

    def test_doctor_search_with_named_specialty_is_explicit(self):
        result = _nlu_result(Intent.DOCTOR_SEARCH, symptom="yellow teeth", specialty="Dentistry")
        self.assertEqual(resolver_context_for_nlu(result), "explicit")

    def test_doctor_search_with_named_service_is_explicit(self):
        result = _nlu_result(Intent.DOCTOR_SEARCH, service="Whitening")
        self.assertEqual(resolver_context_for_nlu(result), "explicit")

    def test_doctor_availability_follows_the_same_rule_as_doctor_search(self):
        self.assertEqual(
            resolver_context_for_nlu(_nlu_result(Intent.DOCTOR_AVAILABILITY, symptom="tooth hurts")),
            "concern",
        )

    def test_medical_question_personal_mode_is_concern(self):
        result = _nlu_result(
            Intent.MEDICAL_QUESTION, symptom="yellow teeth", medical_question_mode="personal"
        )
        self.assertEqual(resolver_context_for_nlu(result), "concern")

    def test_medical_question_symptom_alone_without_personal_mode_is_skipped(self):
        """Live-confirmed bug: `medical_question_mode` must decide this
        alone, never OR'd with entities.symptom. "What causes bleeding
        gums?" sets entities.symptom (an existing, separate NLU rule: any
        body-part/condition word always sets it, even for a purely
        definitional question) but is not personal -- must stay excluded
        even with a symptom entity present, exactly the case that
        reached the live resolver incorrectly (2 of 3 real calls) before
        this fix, returning a doctor list instead of an educational
        answer."""
        result = _nlu_result(Intent.MEDICAL_QUESTION, symptom="bleeding gums")
        self.assertIsNone(resolver_context_for_nlu(result))

    def test_medical_question_without_symptom_is_skipped(self):
        """A purely definitional medical_question ("What is a crown?") has
        no personal-need shape at all -- must not reach the resolver."""
        result = _nlu_result(Intent.MEDICAL_QUESTION)
        self.assertIsNone(resolver_context_for_nlu(result))

    def test_unknown_intent_is_concern(self):
        """Live-confirmed gap: "I want braces for my kid" classified
        `unknown` with every entity null and had no resolution path at
        all today -- must now reach the resolver instead of dead-ending."""
        result = _nlu_result(Intent.UNKNOWN)
        self.assertEqual(resolver_context_for_nlu(result), "concern")

    def test_irrelevant_intents_are_skipped(self):
        for intent in (
            Intent.GREETING,
            Intent.FAREWELL,
            Intent.CLINIC_HOURS,
            Intent.INSURANCE_ACCEPTED,
            Intent.OFF_TOPIC,
            Intent.BOOK_APPOINTMENT,
        ):
            with self.subTest(intent=intent):
                self.assertIsNone(resolver_context_for_nlu(_nlu_result(intent)))

    def test_emergency_is_skipped(self):
        """Emergency detection is a separate, fail-closed layer that must
        take absolute precedence -- the resolver must never be consulted
        for an emergency-classified message."""
        self.assertIsNone(resolver_context_for_nlu(_nlu_result(Intent.EMERGENCY)))


class IsNluDegradedTests(SimpleTestCase):
    """Checks nlu_result.timings.classifier_source -- the actual attribute
    engine.py itself reads for this same signal (ui_meta["degraded"]).
    An earlier version of is_nlu_degraded checked a non-existent
    `nlu_result.source` and silently never caught a real rules_fallback
    case -- these tests pin the corrected attribute path down directly."""

    def test_rules_fallback_classifier_source_is_degraded(self):
        result = _nlu_result(Intent.UNKNOWN)
        result.timings.classifier_source = "rules_fallback"
        self.assertTrue(is_nlu_degraded(result))

    def test_raw_degraded_marker_is_degraded(self):
        result = _nlu_result(Intent.UNKNOWN)
        result.raw = {"_degraded": True}
        self.assertTrue(is_nlu_degraded(result))

    def test_healthy_openai_classifier_source_is_not_degraded(self):
        result = _nlu_result(Intent.DOCTOR_SEARCH, symptom="yellow teeth")
        result.timings.classifier_source = "openai"
        self.assertFalse(is_nlu_degraded(result))

    def test_no_top_level_source_attribute_is_ever_consulted(self):
        """Regression guard for the exact bug found: setting a bogus
        top-level `.source` (which is not a real NLUResult field and does
        nothing) must not be mistaken for the real signal."""
        result = _nlu_result(Intent.UNKNOWN)
        result.source = "rules_fallback"  # not a real field -- must be ignored
        self.assertFalse(is_nlu_degraded(result))


class LiveResolverContextForNluTests(SimpleTestCase):
    """live_resolver_context_for_nlu -- the live vertical slice's actual
    gate, distinct from (narrower than, in one specific way, than) the
    broader resolver_context_for_nlu shadow mode still uses in full."""

    def test_intent_unknown_is_always_excluded_even_if_not_flagged_degraded(self):
        """The one deliberate, permanent narrowing versus the broader
        mapping -- live-confirmed dangerous: "I have an MRI" classifying
        `unknown` (a real classification, not necessarily a rules_fallback/
        _degraded flagged one) still fed the resolver a "concern" with no
        real signal, surfacing generic weakly-relevant candidates as if
        they were a real answer ("Found 5 doctors" at a clinic with no
        imaging capability). Must stay excluded regardless of whether
        is_nlu_degraded would also catch this particular instance."""
        result = _nlu_result(Intent.UNKNOWN)
        result.timings.classifier_source = "openai"  # NOT flagged degraded -- excluded anyway
        self.assertIsNone(live_resolver_context_for_nlu(result))

    def test_degraded_result_is_excluded_regardless_of_intent(self):
        """Even an otherwise-live-eligible intent (services_offered) must
        be refused if the classification itself was a rules-fallback."""
        result = _nlu_result(Intent.SERVICES_OFFERED, service="Whitening")
        result.timings.classifier_source = "rules_fallback"
        self.assertIsNone(live_resolver_context_for_nlu(result))

    def test_services_offered_explicit_is_live_eligible(self):
        result = _nlu_result(
            Intent.SERVICES_OFFERED, service_filter_mode="named", service="Whitening"
        )
        result.timings.classifier_source = "openai"
        self.assertEqual(live_resolver_context_for_nlu(result), "explicit")

    def test_doctor_search_bare_concern_is_live_eligible(self):
        result = _nlu_result(Intent.DOCTOR_SEARCH, symptom="gums bleeding")
        result.timings.classifier_source = "openai"
        self.assertEqual(live_resolver_context_for_nlu(result), "concern")

    def test_doctor_search_zero_entity_unresolved_capability_is_explicit(self):
        """Phase 3 boundary fix, tested directly: live-confirmed gap --
        "which doctor handles root canals?" classifies doctor_search with
        every entity null ("root canal" isn't a literal catalog name the
        NLU can extract verbatim) and both the old resolver chain and the
        un-widened new gate failed it identically. Must now reach the
        resolver as "explicit" using the raw message, since it isn't a
        confirmed browse phrase."""
        result = _nlu_result(Intent.DOCTOR_SEARCH)
        result.timings.classifier_source = "openai"
        self.assertEqual(
            live_resolver_context_for_nlu(result, "which doctor handles root canals?"),
            "explicit",
        )

    def test_doctor_search_zero_entity_generic_browse_also_becomes_explicit(self):
        """Deliberate, documented tradeoff: a genuine browse ("who are
        your doctors?") ALSO becomes "explicit" now -- a regex pre-filter
        to exclude it was tried and abandoned (the existing
        is_doctor_browse_query classifies "which doctor handles root
        canals?" as a browse too, since both start with "which doctor...";
        confirmed by direct testing, not assumed). Correctness is
        protected by apply_capability_resolution's no-op-on-decline for an
        already-SQL-dispatching plan, not by this gate -- the existing
        unfiltered browse still runs untouched regardless of what the
        resolver returns. The accepted cost is one extra LLM call for
        this common phrasing while the flag is enabled."""
        result = _nlu_result(Intent.DOCTOR_SEARCH)
        result.timings.classifier_source = "openai"
        self.assertEqual(
            live_resolver_context_for_nlu(result, "who are your doctors?"),
            "explicit",
        )

    def test_doctor_availability_zero_entity_unresolved_capability_is_explicit(self):
        """Same widening applies to doctor_availability, not just
        doctor_search."""
        result = _nlu_result(Intent.DOCTOR_AVAILABILITY)
        result.timings.classifier_source = "openai"
        self.assertEqual(
            live_resolver_context_for_nlu(result, "which doctor handles root canals?"),
            "explicit",
        )

    def test_doctor_search_zero_entity_empty_message_stays_excluded(self):
        """The one real guard: an empty message has nothing for the
        resolver to reason about at all -- must never fire on nothing."""
        result = _nlu_result(Intent.DOCTOR_SEARCH)
        result.timings.classifier_source = "openai"
        self.assertIsNone(live_resolver_context_for_nlu(result, ""))
        self.assertIsNone(live_resolver_context_for_nlu(result, "   "))

    def test_medical_question_concern_is_live_eligible(self):
        """Phase 2 boundary fix, tested directly: medical_question is a
        real classification (unlike unknown), so a genuine concern
        phrased that way ("my teeth are a bit yellow", no "who should I
        see" tail) must now reach the live resolver instead of dead-
        ending at the old soft_medical canned reply."""
        result = _nlu_result(
            Intent.MEDICAL_QUESTION, symptom="yellow teeth", medical_question_mode="personal"
        )
        result.timings.classifier_source = "openai"
        self.assertEqual(live_resolver_context_for_nlu(result), "concern")

    def test_medical_question_definitional_stays_excluded(self):
        """A purely definitional medical question ("What causes bleeding
        gums?") must still never reach the resolver -- unchanged by the
        Phase 2 widening, which only affects the concern sub-case."""
        result = _nlu_result(Intent.MEDICAL_QUESTION)
        result.timings.classifier_source = "openai"
        self.assertIsNone(live_resolver_context_for_nlu(result))

    def test_medical_question_symptom_without_personal_mode_stays_excluded_live(self):
        """The exact live-confirmed bug, tested at the live gate too:
        entities.symptom being set must never substitute for an explicit
        medical_question_mode=="personal" classification."""
        result = _nlu_result(Intent.MEDICAL_QUESTION, symptom="bleeding gums")
        result.timings.classifier_source = "openai"
        self.assertIsNone(live_resolver_context_for_nlu(result))

    def test_irrelevant_intents_stay_excluded(self):
        for intent in (Intent.GREETING, Intent.CLINIC_HOURS, Intent.OFF_TOPIC, Intent.FAQ):
            result = _nlu_result(intent)
            result.timings.classifier_source = "openai"
            with self.subTest(intent=intent):
                self.assertIsNone(live_resolver_context_for_nlu(result))


class ExpressedNeedForNluTests(SimpleTestCase):
    """Capability-family reliability phase: `context="explicit"` must
    always use the raw message, never the extracted symptom -- regression
    for the real, live-confirmed bug where "I cut my hand and need
    stitches" extracted entities.symptom="hand" (a bare body-part word,
    per the NLU's own separate "any body-part word sets symptom" rule),
    which fed the resolver a token with no capability signal at all and
    silently regressed a real, resolvable capability to the generic
    fallback."""

    def test_explicit_context_always_uses_the_full_message(self):
        nlu = NLUResult(
            intent=Intent.SERVICES_OFFERED,
            entities=ExtractedEntities(symptom="hand"),
            resolved_ids=ResolvedIds(),
        )
        message = "I cut my hand and need stitches"
        self.assertEqual(
            expressed_need_for_nlu(nlu, message, context="explicit"), message
        )

    def test_explicit_context_uses_message_even_with_no_symptom_at_all(self):
        nlu = NLUResult(
            intent=Intent.SERVICES_OFFERED,
            entities=ExtractedEntities(),
            resolved_ids=ResolvedIds(),
        )
        message = "Do you offer a flu test?"
        self.assertEqual(
            expressed_need_for_nlu(nlu, message, context="explicit"), message
        )

    def test_concern_context_still_prefers_the_symptom(self):
        """Unchanged existing behavior: a concern is often a longer,
        less-relevant sentence with the symptom as the one clean signal
        buried inside it -- this preference is deliberately preserved."""
        nlu = NLUResult(
            intent=Intent.MEDICAL_QUESTION,
            entities=ExtractedEntities(symptom="yellow teeth"),
            resolved_ids=ResolvedIds(),
        )
        message = "my teeth are a bit yellow, is that normal or should I worry?"
        self.assertEqual(
            expressed_need_for_nlu(nlu, message, context="concern"),
            "yellow teeth",
        )

    def test_concern_context_falls_back_to_message_with_no_symptom(self):
        nlu = NLUResult(
            intent=Intent.UNKNOWN,
            entities=ExtractedEntities(),
            resolved_ids=ResolvedIds(),
        )
        message = "I want braces for my kid"
        self.assertEqual(
            expressed_need_for_nlu(nlu, message, context="concern"), message
        )

    def test_no_context_given_preserves_original_always_prefer_symptom_behavior(self):
        """Backward-compatible default (context=None) for any caller that
        doesn't yet know its own context -- today, no real caller does
        this (engine.py always passes the resolver context it already
        computed), but the default must not silently change behavior for
        a hypothetical future one that doesn't."""
        nlu = NLUResult(
            intent=Intent.SERVICES_OFFERED,
            entities=ExtractedEntities(symptom="hand"),
            resolved_ids=ResolvedIds(),
        )
        message = "I cut my hand and need stitches"
        self.assertEqual(expressed_need_for_nlu(nlu, message), "hand")


def _clinic(slug: str) -> Clinic:
    return Clinic.objects.create(
        slug=slug,
        name=slug.replace("-", " ").title(),
        email=f"{slug}@clinic.test",
        phone="+12125550000",
        timezone="America/New_York",
    )


class CapabilityValidationTests(TestCase):
    """The Python-side guarantee: an id survives only if it's real, active,
    tenant-scoped, and of the claimed type -- mirrors
    nlu/resolvers.py::resolve_catalog_match's exact discipline."""

    def setUp(self):
        self.clinic = _clinic("validation-clinic")
        self.other_clinic = _clinic("other-clinic")
        self.service = Service.objects.create(
            clinic=self.clinic,
            name="Simple Wound Laceration Repair (Sutures)",
            description="Surgical closure of a skin cut using sutures.",
            is_active=True,
        )
        self.specialty = Specialty.objects.create(
            clinic=self.clinic,
            name="Family Medicine",
            slug="family-medicine",
            is_active=True,
        )

    def _mock_llm(self, payload: dict):
        return patch(
            "apps.chatbot.booking.capability_resolver._call_response_llm",
            return_value=json.dumps(payload),
        )

    def test_valid_service_id_survives(self):
        payload = {
            "candidates": [
                {
                    "type": "service",
                    "id": str(self.service.id),
                    "confidence": 0.9,
                    "reasoning": "matches",
                }
            ]
        }
        with self._mock_llm(payload):
            result = resolve_capability(
                self.clinic, "I need stitches", context="explicit"
            )
        self.assertEqual(len(result.candidates), 1)
        self.assertEqual(result.candidates[0].id, str(self.service.id))
        self.assertEqual(result.candidates[0].target_type, "service")

    def test_fabricated_id_is_dropped(self):
        payload = {
            "candidates": [
                {
                    "type": "service",
                    "id": "00000000-0000-0000-0000-000000000000",
                    "confidence": 0.95,
                    "reasoning": "invented",
                }
            ]
        }
        with self._mock_llm(payload):
            result = resolve_capability(
                self.clinic, "I need stitches", context="explicit"
            )
        self.assertEqual(result.candidates, [])

    def test_inactive_service_id_is_dropped(self):
        inactive = Service.objects.create(
            clinic=self.clinic,
            name="Discontinued Service",
            is_active=False,
        )
        payload = {
            "candidates": [
                {
                    "type": "service",
                    "id": str(inactive.id),
                    "confidence": 0.9,
                    "reasoning": "matches",
                }
            ]
        }
        with self._mock_llm(payload):
            result = resolve_capability(
                self.clinic, "something", context="explicit"
            )
        self.assertEqual(result.candidates, [])

    def test_cross_clinic_id_is_dropped(self):
        other_service = Service.objects.create(
            clinic=self.other_clinic,
            name="Other Clinic Service",
            is_active=True,
        )
        payload = {
            "candidates": [
                {
                    "type": "service",
                    "id": str(other_service.id),
                    "confidence": 0.9,
                    "reasoning": "matches",
                }
            ]
        }
        with self._mock_llm(payload):
            result = resolve_capability(
                self.clinic, "something", context="explicit"
            )
        self.assertEqual(result.candidates, [])

    def test_wrong_type_id_is_dropped(self):
        """The service's real id claimed as a specialty must not survive --
        type must match what was actually shown under that label."""
        payload = {
            "candidates": [
                {
                    "type": "specialty",
                    "id": str(self.service.id),
                    "confidence": 0.9,
                    "reasoning": "matches",
                }
            ]
        }
        with self._mock_llm(payload):
            result = resolve_capability(
                self.clinic, "something", context="explicit"
            )
        self.assertEqual(result.candidates, [])

    def test_valid_specialty_id_survives(self):
        payload = {
            "candidates": [
                {
                    "type": "specialty",
                    "id": str(self.specialty.id),
                    "confidence": 0.8,
                    "reasoning": "matches",
                }
            ]
        }
        with self._mock_llm(payload):
            result = resolve_capability(
                self.clinic, "who should I see", context="concern"
            )
        self.assertEqual(len(result.candidates), 1)
        self.assertEqual(result.candidates[0].target_type, "specialty")

    def test_confidence_is_clamped_to_0_1(self):
        payload = {
            "candidates": [
                {
                    "type": "service",
                    "id": str(self.service.id),
                    "confidence": 5.0,
                    "reasoning": "overclaimed",
                }
            ]
        }
        with self._mock_llm(payload):
            result = resolve_capability(
                self.clinic, "I need stitches", context="explicit"
            )
        self.assertEqual(result.candidates[0].confidence, 1.0)

    def test_malformed_json_is_reported_as_provider_error_not_no_match(self):
        """A malformed response is not a semantic 'no matching capability'
        result -- it must be distinguishable so a caller never confuses
        infrastructure failure with an honest empty result (Phase A's own
        diagnostic run found ~5/75 calls silently collapsing the two)."""
        with patch(
            "apps.chatbot.booking.capability_resolver._call_response_llm",
            return_value="not json at all",
        ):
            result = resolve_capability(
                self.clinic, "I need stitches", context="explicit"
            )
        self.assertEqual(result.candidates, [])
        self.assertEqual(result.outcome, "provider_error")

    def test_provider_exception_is_reported_as_provider_error_not_no_match(self):
        with patch(
            "apps.chatbot.booking.capability_resolver._call_response_llm",
            side_effect=RuntimeError("provider down"),
        ):
            result = resolve_capability(
                self.clinic, "I need stitches", context="explicit"
            )
        self.assertEqual(result.candidates, [])
        self.assertEqual(result.outcome, "provider_error")

    def test_genuine_no_match_is_reported_as_ok(self):
        """A well-formed empty candidates array (the model genuinely found
        nothing relevant) must be distinguishable from a provider failure
        -- both return an empty list, only `outcome` tells them apart."""
        with self._mock_llm({"candidates": []}):
            result = resolve_capability(
                self.clinic, "I need an MRI", context="explicit"
            )
        self.assertEqual(result.candidates, [])
        self.assertEqual(result.outcome, "ok")


class CapabilityEmptyInputTests(TestCase):
    def setUp(self):
        self.clinic = _clinic("empty-catalog-clinic")

    def test_empty_catalog_returns_empty_without_calling_llm(self):
        with patch(
            "apps.chatbot.booking.capability_resolver._call_response_llm"
        ) as mock_llm:
            result = resolve_capability(
                self.clinic, "I need stitches", context="explicit"
            )
        mock_llm.assert_not_called()
        self.assertEqual(result.candidates, [])

    def test_empty_expressed_need_returns_empty_without_calling_llm(self):
        Specialty.objects.create(
            clinic=self.clinic, name="Family Medicine", slug="family-medicine"
        )
        with patch(
            "apps.chatbot.booking.capability_resolver._call_response_llm"
        ) as mock_llm:
            result = resolve_capability(self.clinic, "", context="explicit")
        mock_llm.assert_not_called()
        self.assertEqual(result.candidates, [])


class CapabilityNotOfferedReplyTests(TestCase):
    """engine.py::_capability_not_offered_reply -- the decline reply for a
    concern the resolver couldn't tie to any specialty. Live-confirmed gap:
    capability_routing_policy's "concern_no_specialty_candidate" case can
    still carry a real, relevant service candidate (its own governing rule
    is only that a concern's service candidate must never silently become
    a SQL filter -- being informational is exactly what it's for), but
    that candidate was computed, logged in capability_resolver_live, and
    then discarded outright -- never reached this reply at all."""

    def setUp(self):
        self.clinic = _clinic("not-offered-reply-clinic")
        self.service = Service.objects.create(
            clinic=self.clinic, name="Surgical Tooth Extraction", is_active=True
        )

    def test_no_candidates_is_the_plain_decline(self):
        from apps.chatbot.engine import ChatEngine

        text = ChatEngine()._capability_not_offered_reply(self.clinic, [])
        self.assertIn("don't have a specialist for that here", text)
        self.assertNotIn("Surgical Tooth Extraction", text)

    def test_real_service_candidate_is_named(self):
        from apps.chatbot.engine import ChatEngine

        text = ChatEngine()._capability_not_offered_reply(
            self.clinic, [str(self.service.id)]
        )
        self.assertIn("Surgical Tooth Extraction", text)
        self.assertIn("you might ask about", text)

    def test_fabricated_id_never_reaches_the_reply(self):
        """The id must be re-validated here, not trusted just because a
        RoutingDecision carried it this far -- same discipline as every
        other id this resolver ever hands downstream."""
        from apps.chatbot.engine import ChatEngine

        text = ChatEngine()._capability_not_offered_reply(
            self.clinic, ["00000000-0000-0000-0000-000000000000"]
        )
        self.assertIn("don't have a specialist for that here", text)

    def test_cross_clinic_id_never_reaches_the_reply(self):
        other_clinic = _clinic("not-offered-reply-other-clinic")
        from apps.chatbot.engine import ChatEngine

        text = ChatEngine()._capability_not_offered_reply(
            other_clinic, [str(self.service.id)]
        )
        self.assertIn("don't have a specialist for that here", text)

    def test_inactive_service_id_never_reaches_the_reply(self):
        inactive = Service.objects.create(
            clinic=self.clinic, name="Discontinued Service", is_active=False
        )
        from apps.chatbot.engine import ChatEngine

        text = ChatEngine()._capability_not_offered_reply(
            self.clinic, [str(inactive.id)]
        )
        self.assertIn("don't have a specialist for that here", text)
