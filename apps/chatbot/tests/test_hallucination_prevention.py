"""Phase 51 — three confirmed hallucination/entity-drop bugs found by the
external adversarial evaluation (apps/chatbot/eval/adversarial/), not by
this project's own existing tests or eval battery. See ROADMAP.md Phase 51
for the full live reproduction, root cause, and severity for each.
"""

from __future__ import annotations

from dataclasses import replace

from django.test import SimpleTestCase, TestCase

from apps.chatbot.nlu.resolvers import _match_service, resolve_entities
from apps.chatbot.nlu.schemas import Intent, parse_nlu_payload
from apps.chatbot.routing.heuristics import apply_routing_heuristics
from apps.clinics.models import Clinic
from apps.services.models import Service


class BookAppointmentToFaqDoesNotFabricateDoctorTests(SimpleTestCase):
    """Live-confirmed: "can I grab an appointment with Dr. Vance" has
    doctor_id already resolved, but "grab" isn't a recognized transactional
    verb, so the message used to fall through to FAQ/vector-RAG — which has
    no doctor-roster data and free-generated "Dr. Vance is not listed among
    our providers," fabricating the non-existence of a real doctor."""

    def test_resolved_doctor_routes_to_doctor_search_not_faq(self):
        nlu = parse_nlu_payload(
            {"intent": "book_appointment", "confidence": 0.95, "entities": {"doctor_name": ["Vance"]}}
        )
        nlu = replace(nlu, resolved_ids=replace(nlu.resolved_ids, doctor_id="doc-123"))
        out = apply_routing_heuristics(
            message="can i grab an appointment with dr vance",
            nlu=nlu,
            document_catalog=[{"id": "1", "title": "contract"}],
            service_catalog=[],
        )
        self.assertEqual(out.intent, Intent.DOCTOR_SEARCH)
        self.assertTrue(out.needs_sql)
        self.assertFalse(out.needs_vector)

    def test_resolved_service_routes_to_services_offered_not_faq(self):
        nlu = parse_nlu_payload(
            {
                "intent": "book_appointment", "confidence": 0.9,
                "entities": {"service": "Adult Physical"}, "service_filter_mode": "named",
            }
        )
        nlu = replace(nlu, resolved_ids=replace(nlu.resolved_ids, service_id="svc-123"))
        out = apply_routing_heuristics(
            message="can i grab a physical sometime",
            nlu=nlu,
            document_catalog=[{"id": "1", "title": "contract"}],
            # A non-empty catalog containing the named service -- an empty
            # catalog hits a separate, pre-existing "nothing to resolve
            # against" clearing path unrelated to this fix.
            service_catalog=[{"id": "svc-123", "name": "Adult Physical"}],
        )
        self.assertEqual(out.intent, Intent.SERVICES_OFFERED)
        self.assertTrue(out.needs_sql)
        self.assertFalse(out.needs_vector)

    def test_no_entity_still_falls_through_to_faq(self):
        """The FAQ fallback is still correct and load-bearing for a
        genuinely knowledge-shaped, entity-free question — must not
        regress "do you take bookings on Saturdays"-style messages."""
        nlu = parse_nlu_payload({"intent": "book_appointment", "confidence": 0.7, "entities": {}})
        out = apply_routing_heuristics(
            message="do you take bookings on saturdays",
            nlu=nlu,
            document_catalog=[{"id": "1", "title": "contract"}],
            service_catalog=[],
        )
        self.assertEqual(out.intent, Intent.FAQ)
        self.assertTrue(out.needs_vector)

    def test_transactional_booking_language_unaffected(self):
        """A genuinely transactional booking message must still take the
        is_transactional_booking() branch entirely (this whole block is
        gated on NOT is_transactional_booking) — not touched by this fix."""
        nlu = parse_nlu_payload(
            {"intent": "book_appointment", "confidence": 0.95, "entities": {"doctor_name": ["Vance"]}}
        )
        nlu = replace(nlu, resolved_ids=replace(nlu.resolved_ids, doctor_id="doc-123"))
        out = apply_routing_heuristics(
            message="book an appointment with dr vance",
            nlu=nlu,
            document_catalog=[{"id": "1", "title": "contract"}],
            service_catalog=[],
        )
        # is_transactional_booking is True here, so this whole if-block
        # never runs at all -- intent stays book_appointment.
        self.assertEqual(out.intent, Intent.BOOK_APPOINTMENT)


class FuzzyServiceMatchDoesNotHallucinateTests(TestCase):
    """Live-confirmed: _fuzzy_score's token-overlap branch scores a flat
    0.85 for ANY single shared word — "executive cardiac physical"
    (fabricated) matched the real "Establish Patient Adult Physical"
    purely via the shared word "physical", attaching a real $185 price to
    a service name that was never actually offered."""

    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="fuzzy-match-clinic", name="Fuzzy Match Clinic",
            email="f@m.com", phone="+12125550000",
            address={"street": "1 Main St", "city": "Boston", "state": "MA", "zip": "02101"},
            timezone="America/New_York",
        )
        self.physical = Service.objects.create(
            clinic=self.clinic, name="Establish Patient Adult Physical",
            duration_min=45, price_cents=18500, is_active=True,
        )

    def test_fabricated_service_sharing_one_word_does_not_match(self):
        self.assertIsNone(_match_service(self.clinic, "executive cardiac physical"))

    def test_another_fabricated_variant_does_not_match(self):
        self.assertIsNone(_match_service(self.clinic, "premium diagnostic physical package"))

    def test_natural_paraphrase_still_matches(self):
        self.assertEqual(
            _match_service(self.clinic, "physical exam"), str(self.physical.id)
        )

    def test_bare_shared_word_still_matches(self):
        self.assertEqual(_match_service(self.clinic, "physical"), str(self.physical.id))

    def test_exact_name_still_matches(self):
        self.assertEqual(
            _match_service(self.clinic, "Establish Patient Adult Physical"),
            str(self.physical.id),
        )

    def test_resolve_entities_end_to_end_does_not_hallucinate(self):
        from apps.chatbot.nlu.schemas import ExtractedEntities

        resolved = resolve_entities(self.clinic, ExtractedEntities(service="executive cardiac physical"))
        self.assertIsNone(resolved.service_id)


class SpecialtyListDoesNotDropServiceEntityTests(TestCase):
    """Live-confirmed: "what specialties do you have and how much is a
    physical" silently dropped the pricing half entirely — _SERVICE_LIST_RE
    also matches "what specialt(y|ies)..." phrasing, which cleared the
    already-resolved "physical" service entity before the planner ever saw
    it, and match_services_in_message() has the identical guard internally
    so the same "none" outcome was reachable two different ways."""

    def test_service_entity_survives_when_price_language_present(self):
        nlu = parse_nlu_payload(
            {
                "intent": "faq", "secondary_intents": ["services_offered"], "confidence": 0.9,
                "entities": {"service": "Adult Physical"}, "service_filter_mode": "none",
            }
        )
        services = [{"id": "svc-1", "name": "Establish Patient Adult Physical"}]
        out = apply_routing_heuristics(
            message="what specialties do you have and how much is a physical",
            nlu=nlu,
            document_catalog=[{"id": "1", "title": "x"}],
            service_catalog=services,
        )
        self.assertEqual(out.entities.service, "Adult Physical")
        self.assertEqual(out.service_filter_mode, "named")

    def test_genuine_bare_specialty_browse_still_clears_service(self):
        """Regression: a real, non-compound "what specialties do you have"
        (no price language, no service entity) must still browse cleanly
        -- this fix must not weaken the original browse behavior."""
        nlu = parse_nlu_payload(
            {"intent": "faq", "confidence": 0.9, "entities": {}, "service_filter_mode": "none"}
        )
        out = apply_routing_heuristics(
            message="what specialties do you have",
            nlu=nlu,
            document_catalog=[{"id": "1", "title": "x"}],
            service_catalog=[],
        )
        self.assertEqual(out.service_filter_mode, "none")
        self.assertIsNone(out.entities.service)

    def test_service_entity_without_price_language_still_cleared(self):
        """The exception requires BOTH a resolved service entity AND
        price/duration language -- a bare specialty-list message that
        happens to have a stray service entity (e.g. left over from a
        prior turn's context) must still browse cleanly, not accidentally
        keep an unrelated entity just because it's present."""
        nlu = parse_nlu_payload(
            {
                "intent": "faq", "confidence": 0.9,
                "entities": {"service": "Adult Physical"}, "service_filter_mode": "none",
            }
        )
        out = apply_routing_heuristics(
            message="what specialties do you have",
            nlu=nlu,
            document_catalog=[{"id": "1", "title": "x"}],
            service_catalog=[],
        )
        self.assertEqual(out.service_filter_mode, "none")
        self.assertIsNone(out.entities.service)
