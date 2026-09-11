"""capability_routing_policy.py — Phase B policy rules, pure-function tests.

No DB, no LLM — this only tests the translation from a CapabilityResolution
into a RoutingDecision, encoding the rules agreed after Phase A's evidence.
"""

from __future__ import annotations

from django.test import SimpleTestCase

from apps.chatbot.booking.capability_resolver import (
    CapabilityCandidate,
    CapabilityResolution,
)
from apps.chatbot.booking.capability_routing_policy import decide_routing


def _svc(id_: str, confidence: float = 0.9) -> CapabilityCandidate:
    return CapabilityCandidate(
        target_type="service", id=id_, name=f"service-{id_}", confidence=confidence, reasoning=""
    )


def _spec(id_: str, confidence: float = 0.9) -> CapabilityCandidate:
    return CapabilityCandidate(
        target_type="specialty", id=id_, name=f"specialty-{id_}", confidence=confidence, reasoning=""
    )


class ProviderFailureTests(SimpleTestCase):
    def test_provider_error_is_never_reported_as_no_match(self):
        resolution = CapabilityResolution(candidates=[], outcome="provider_error")
        decision = decide_routing("explicit", resolution)
        self.assertEqual(decision.action, "unavailable")
        self.assertNotEqual(decision.action, "decline")


class NoMatchTests(SimpleTestCase):
    def test_genuine_empty_result_is_an_honest_decline(self):
        resolution = CapabilityResolution(candidates=[], outcome="ok")
        decision = decide_routing("explicit", resolution)
        self.assertEqual(decision.action, "decline")


class ExplicitRequestTests(SimpleTestCase):
    def test_explicit_service_only_drives_service_filter(self):
        resolution = CapabilityResolution(candidates=[_svc("svc-1")])
        decision = decide_routing("explicit", resolution)
        self.assertEqual(decision.action, "filter")
        self.assertEqual(decision.service_ids, ["svc-1"])
        self.assertEqual(decision.specialty_ids, [])

    def test_explicit_specialty_only_drives_specialty_filter(self):
        resolution = CapabilityResolution(candidates=[_spec("spec-1")])
        decision = decide_routing("explicit", resolution)
        self.assertEqual(decision.action, "filter")
        self.assertEqual(decision.specialty_ids, ["spec-1"])
        self.assertEqual(decision.service_ids, [])

    def test_explicit_mixed_candidates_populate_both_fields_regardless_of_rank(self):
        """Live-confirmed bug this replaces: "can i just walk in for a
        minor cut or do i need to book something first" (services_offered
        intent, sql_tasks=["services"]) resolved a specialty (Urgent Care)
        ranked ahead of the exact-match service (Simple Wound Laceration
        Repair (Sutures)), both at confidence 1.0. The old rule ("only
        resolution.candidates[0] counts") set specialty_ids and left
        service_ids empty -- but services_offered only ever reads
        resolved_service_ids, so the resolver's correct answer was silently
        discarded purely because of candidate order, not relevance. Each
        field is only ever consulted by the SQL task that actually needs
        it, so populating both whenever both types are present is never
        over-filtering -- it just stops losing the answer to sort order."""
        resolution = CapabilityResolution(candidates=[_spec("spec-1"), _svc("svc-1")])
        decision = decide_routing("explicit", resolution)
        self.assertEqual(decision.action, "filter")
        self.assertEqual(decision.specialty_ids, ["spec-1"])
        self.assertEqual(decision.service_ids, ["svc-1"])

    def test_explicit_returns_every_same_type_candidate_not_just_the_top_one(self):
        """Changed in the capability-family reliability phase (checkup
        ambiguity bug), superseding the old "same-type stays top-1-only"
        rule this test used to assert. Live-confirmed: "I need a checkup"
        is genuinely ambiguous between "Establish Patient Adult Physical"
        and "Pediatric Well-Child Exam" (both real services, nothing in
        the wording favors either), but the old top-1-per-type rule
        silently discarded the second one and always answered as if only
        Adult Physical existed. `_EXPLICIT_INSTRUCTIONS` was tightened so
        the resolver itself only returns 2+ same-type candidates when the
        request is genuinely ambiguous (never merely to hedge on a clear
        match, live-validated: "flu test"/"stitches" still return exactly
        one candidate every time) -- so this policy layer can safely take
        every same-type candidate without reopening the risk the old rule
        was protecting against."""
        resolution = CapabilityResolution(
            candidates=[_svc("svc-1"), _svc("svc-2"), _spec("spec-1")]
        )
        decision = decide_routing("explicit", resolution)
        self.assertEqual(set(decision.service_ids), {"svc-1", "svc-2"})
        self.assertEqual(decision.specialty_ids, ["spec-1"])


class ConcernTests(SimpleTestCase):
    def test_concern_never_lets_a_service_candidate_silently_filter(self):
        """The central governing principle, tested directly: a concern's
        service candidates must never reach `service_ids` (the field an
        eventual SQL filter would consume) -- only `specialty_ids` and the
        clearly-separate informational field."""
        resolution = CapabilityResolution(
            candidates=[_spec("dentistry"), _svc("whitening", confidence=1.0)]
        )
        decision = decide_routing("concern", resolution)
        self.assertEqual(decision.action, "filter")
        self.assertEqual(decision.specialty_ids, ["dentistry"])
        self.assertEqual(decision.service_ids, [])
        self.assertIn("whitening", decision.informational_service_candidates)

    def test_concern_uses_all_specialty_candidates_not_just_the_top_one(self):
        """No confidence threshold/margin is applied -- every specialty
        candidate the resolver returned forms one OR-filter set, the same
        granularity the existing concern-map chain already uses when it
        finds 2+ plausible specialties."""
        resolution = CapabilityResolution(
            candidates=[_spec("spec-1", 0.9), _spec("spec-2", 0.6)]
        )
        decision = decide_routing("concern", resolution)
        self.assertEqual(set(decision.specialty_ids), {"spec-1", "spec-2"})

    def test_concern_with_only_service_candidates_is_an_honest_decline(self):
        """No specialty signal at all for a concern -- must not fall back
        to silently filtering by the service candidate instead."""
        resolution = CapabilityResolution(candidates=[_svc("svc-1")])
        decision = decide_routing("concern", resolution)
        self.assertEqual(decision.action, "decline")
        self.assertEqual(decision.service_ids, [])
        self.assertIn("svc-1", decision.informational_service_candidates)

    def test_low_confidence_uncertain_wording_is_not_specially_downweighted(self):
        """Phase A evidence: 'I'm not sure if I need stitches' scored the
        SAME 1.0 confidence as the explicit ask. This policy deliberately
        does not try to compensate via a confidence threshold -- the
        action-level distinction (concern never sets service_ids) is what
        protects against over-committing, not the number."""
        resolution = CapabilityResolution(
            candidates=[_spec("urgent-care"), _svc("sutures", confidence=1.0)]
        )
        decision = decide_routing("concern", resolution)
        self.assertEqual(decision.service_ids, [])
        self.assertIn("sutures", decision.informational_service_candidates)
