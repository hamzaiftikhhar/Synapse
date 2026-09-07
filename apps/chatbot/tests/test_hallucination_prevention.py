"""Phase 51 — three confirmed hallucination/entity-drop bugs found by the
external adversarial evaluation (apps/chatbot/eval/adversarial/), not by
this project's own existing tests or eval battery. See ROADMAP.md Phase 51
for the full live reproduction, root cause, and severity for each.
"""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from apps.chatbot.engine import ChatEngine
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


class LooselyRelatedExcerptDoesNotBecomeFabricatedAnswerTests(SimpleTestCase):
    """Live-confirmed, pre-production review: "what are your priorities in
    treating patients" retrieved a real but only loosely-related knowledge
    chunk (a membership-fee clause), and the response LLM generalized it
    into confident-sounding, entirely invented "clinic priorities" language
    ("continuous, personalized primary care... attentive, patient-centered
    care...") that appeared nowhere in the actual retrieved text. The
    constitution's existing "if knowledge is missing, say so" rule only
    covered zero retrieval hits (already handled in code by
    empty_rag_reply()) -- it said nothing about a hit that doesn't actually
    answer the question. This is a prompt-only fix (receptionist_
    constitution.md), so it can't be regression-locked by asserting model
    output deterministically -- this just confirms the instruction text
    the model receives actually contains the new rule. Live-verified
    separately (see ROADMAP.md) that the exact reported case now declines
    honestly instead of inventing content, and that genuinely answerable
    questions grounded in real document text are unaffected."""

    def test_constitution_instructs_against_generalizing_from_loose_excerpts(self):
        from apps.chatbot.response_llm import _system_prompt

        clinic = type("C", (), {"name": "Acme", "phone": "555"})()
        prompt = _system_prompt(clinic)
        lowered = prompt.lower()
        self.assertIn("loosely related", lowered)
        self.assertIn("fabrication", lowered)


class RagRepliesUseFullConversationWindowTests(SimpleTestCase):
    """Live-confirmed gap (found while investigating a "feels like it has
    no memory" report): the Large LLM's RAG-answer prompt truncated
    conversation history to the last exchange only (`history[-2:]`, "at
    most last 1-2 turns for latency"), even though up to 6 turns
    (recent_turns, Phase 37) were already loaded and available for free.
    Reproduced directly: a patient who disclosed a child's peanut allergy,
    then asked an unrelated question, then asked a fasting-instructions
    question referencing "her allergy" two exchanges later, got a reply
    that failed to acknowledge the already-disclosed allergy and read
    exactly like the disclosure had never happened. Separately, the
    constitution's "use ONLY provided knowledge excerpts and optional SQL
    context" instruction said nothing about the Recent conversation
    section also present in the same prompt -- clarified so the "ONLY"
    scope is unambiguously about clinic facts, not conversational
    continuity.

    This is a prompt-and-plumbing fix -- deterministic assertions below
    confirm the actual history that reaches the prompt/provider call is no
    longer silently re-truncated to 2, and that the clarifying instruction
    text is present. Live model behavior was verified separately (see
    ROADMAP.md), not asserted here, per this file's own established
    pattern for prompt-only fixes."""

    def test_system_prompt_authorizes_using_recent_conversation_for_continuity(self):
        from apps.chatbot.response_llm import _system_prompt

        clinic = type("C", (), {"name": "Acme", "phone": "555"})()
        prompt = _system_prompt(clinic)
        lowered = prompt.lower()
        self.assertIn("recent conversation", lowered)
        self.assertIn("refer back to it naturally", lowered)

    def test_system_prompt_scopes_the_only_instruction_to_clinic_facts(self):
        """The "ONLY" instruction must still exist (anti-fabrication guard
        for doctors/slots/hours/etc.) -- just no longer phrased broadly
        enough to also suppress using conversation history."""
        from apps.chatbot.response_llm import _system_prompt

        clinic = type("C", (), {"name": "Acme", "phone": "555"})()
        prompt = _system_prompt(clinic)
        self.assertIn("clinic-specific facts", prompt.lower())

    def test_user_block_includes_more_than_the_last_exchange(self):
        from apps.chatbot.response_llm import build_response_prompts

        clinic = type("C", (), {"name": "Acme", "phone": "555"})()
        history = [
            {"role": "user", "content": "My daughter has a peanut allergy."},
            {"role": "assistant", "content": "Noted, thank you for letting us know."},
            {"role": "user", "content": "Do you treat adults too?"},
            {"role": "assistant", "content": "Yes, we see patients of all ages."},
        ]
        prompts = build_response_prompts(
            clinic=clinic, message="Anything special given her allergy?", history=history
        )
        self.assertIn("peanut allergy", prompts["user_prompt"])

    def test_user_block_still_bounds_a_much_longer_history(self):
        """Not unbounded -- a defensive cap still applies even if a caller
        passes an unusually long history, so prompt size/latency stay
        predictable."""
        from apps.chatbot.response_llm import _MAX_HISTORY_TURNS, build_response_prompts

        clinic = type("C", (), {"name": "Acme", "phone": "555"})()
        # Zero-padded, fixed-width markers -- a plain f"message-{i}" would
        # false-positive on substring matches (e.g. "message-1" is a
        # substring of "message-14"), which is exactly what happened the
        # first time this test was written.
        history = [
            {"role": "user" if i % 2 == 0 else "assistant", "content": f"MARKER-{i:03d}-END"}
            for i in range(20)
        ]
        prompts = build_response_prompts(clinic=clinic, message="hi", history=history)
        rendered = prompts["user_prompt"]
        self.assertNotIn("MARKER-000-END", rendered)
        kept = sum(1 for i in range(20) if f"MARKER-{i:03d}-END" in rendered)
        self.assertEqual(kept, _MAX_HISTORY_TURNS)

    @patch("apps.chatbot.response_llm.synthesize_clinic_reply")
    def test_generate_response_passes_full_recent_turns_not_a_2_turn_slice(self, mock_synth):
        """engine.py::_generate_response used to re-truncate to
        recent_turns[-2:] before this fix -- must now forward the full
        (already-bounded-at-6) recent_turns list through untouched."""
        mock_synth.return_value = "ok"
        recent_turns = [
            {"role": "user" if i % 2 == 0 else "assistant", "content": f"turn-{i}"}
            for i in range(6)
        ]
        clinic = type("C", (), {"name": "Acme", "phone": "555"})()
        ChatEngine()._generate_response(
            clinic=clinic,
            message="hi",
            nlu=None,
            sql_rows=[],
            vector_rows=[{"score": 0.9, "heading": "x", "text": "y"}],
            session=None,
            recent_turns=recent_turns,
        )
        self.assertEqual(mock_synth.call_args.kwargs["history"], recent_turns)
