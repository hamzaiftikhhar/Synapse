"""Conversation timeline and recovery helpers."""

from __future__ import annotations

from django.test import SimpleTestCase

from apps.chatbot.conversation_state import (
    ConversationTimeline,
    apply_recovery,
    classify_pin_amendment,
    classify_preview_only,
    classify_session_recall,
    classify_uptake,
    compose_session_recall,
    detect_recovery,
    load_timeline,
    merge_turn_context,
    pending_offer_from_turn,
    recovery_reply,
    resolve_ordinal_doctor_ref,
    save_timeline,
)
from apps.chatbot.nlu.schemas import ExtractedEntities, Intent, NLUResult, ResolvedIds


class ConversationStateTests(SimpleTestCase):
    def test_change_mind_recovery(self):
        tl = ConversationTimeline(intent_thread="insurance", insurance={"name": "Delta"})
        action = detect_recovery("nah i changed my mind", tl)
        self.assertEqual(action.kind, "reverse")
        text = recovery_reply(action, tl)
        self.assertIn("insurance", text.lower())

    def test_same_doctor_again(self):
        tl = ConversationTimeline(doctor={"id": "1", "name": "Dr. Aris Thorne"})
        action = detect_recovery("book same doctor again", tl)
        self.assertEqual(action.kind, "same_doctor")

    def test_timeline_roundtrip(self):
        tl = merge_turn_context(
            ConversationTimeline(),
            doctor={"id": "d1", "name": "Dr. A"},
            service={"id": "s1", "name": "Cleaning"},
            intent="book_appointment",
        )
        ctx = save_timeline({}, tl)
        loaded = load_timeline(ctx)
        self.assertEqual(loaded.doctor["name"], "Dr. A")
        self.assertEqual(loaded.service["name"], "Cleaning")

    def test_apply_recovery_clears_insurance(self):
        tl = ConversationTimeline(insurance={"name": "Aetna"}, intent_thread="insurance")
        action = detect_recovery("never mind", tl)
        tl = apply_recovery(action, tl)
        self.assertIsNone(tl.insurance)

    def test_nah_fr_not_recovery_on_empty_timeline(self):
        action = detect_recovery("nah fr who are ur doctors rn", ConversationTimeline())
        self.assertEqual(action.kind, "none")

    def test_or_nah_rhetorical_not_recovery(self):
        action = detect_recovery("do you have dr hamza or nah", ConversationTimeline())
        self.assertEqual(action.kind, "none")

    def test_nah_forget_it_is_strong_cancel(self):
        action = detect_recovery("nah forget it", ConversationTimeline())
        self.assertEqual(action.kind, "reverse")
        self.assertTrue(action.strong_cancel)


class PendingUptakeTests(SimpleTestCase):
    def test_varied_affirmations_are_uptake(self):
        from apps.chatbot.conversation_state import classify_uptake

        for text in ("Yep.", "Sure", "Please do", "Go ahead", "sounds good", "ok"):
            self.assertEqual(classify_uptake(text), "affirm", msg=text)

    def test_varied_declines_are_uptake(self):
        from apps.chatbot.conversation_state import classify_uptake

        for text in ("No thanks", "Not now", "maybe later", "nope"):
            self.assertEqual(classify_uptake(text), "decline", msg=text)

    def test_a_new_request_is_not_uptake(self):
        from apps.chatbot.conversation_state import classify_uptake

        for text in (
            "yes, Thursday morning if she's free",
            "is Cigna on the accepted list here",
            "what time do you close on Saturdays",
        ):
            self.assertIsNone(classify_uptake(text), msg=text)

    def test_without_a_pending_offer_uptake_does_not_matter(self):
        from apps.chatbot.conversation_state import classify_uptake

        self.assertEqual(classify_uptake("Yep."), "affirm")

    def test_affirm_rewrites_insurance_hallucination_to_availability(self):
        from apps.chatbot.conversation_state import apply_pending_uptake
        from apps.chatbot.nlu.schemas import ExtractedEntities, Intent, NLUResult

        nlu = NLUResult(
            intent=Intent.INSURANCE_VERIFICATION,
            confidence=0.95,
            entities=ExtractedEntities(),
        )
        pending = {
            "type": "availability_alternative",
            "doctor_id": "doc-1",
            "doctor_name": "Dr. Maya Lin",
        }
        bound = apply_pending_uptake(nlu, pending)
        self.assertEqual(bound.intent, Intent.DOCTOR_AVAILABILITY)
        self.assertEqual(bound.resolved_ids.doctor_id, "doc-1")
        self.assertIsNone(bound.entities.date)

    def test_empty_availability_records_an_alternative_offer(self):
        from apps.chatbot.conversation_state import pending_offer_from_turn
        from apps.chatbot.nlu.schemas import Intent, NLUResult

        offer = pending_offer_from_turn(
            sql_rows=[
                {
                    "handler": "doctor_availability",
                    "found": False,
                    "rows": [],
                    "meta": {"temporal_searchable": True},
                }
            ],
            nlu=NLUResult(intent=Intent.DOCTOR_AVAILABILITY, confidence=0.9),
            last_doctor={"id": "maya", "name": "Dr. Maya Lin"},
            matched_services=None,
        )
        self.assertEqual(offer["type"], "availability_alternative")
        self.assertEqual(offer["doctor_id"], "maya")

    def test_service_answer_records_a_followup_offer(self):
        from apps.chatbot.conversation_state import pending_offer_from_turn
        from apps.chatbot.nlu.schemas import Intent, NLUResult

        offer = pending_offer_from_turn(
            sql_rows=[],
            nlu=NLUResult(intent=Intent.MEDICAL_QUESTION, confidence=0.85),
            last_doctor=None,
            matched_services=[{"id": "rc-1", "name": "Root Canal"}],
        )
        self.assertEqual(offer["type"], "service_followup")
        self.assertEqual(offer["service_id"], "rc-1")


class SlotConfirmationTests(SimpleTestCase):
    """A *found* availability slot ("Earliest opening: Dr Priya at 12 PM")
    is the most common confirmation moment in the system and, until this
    phase, the one case pending_offer_from_turn didn't cover at all — only
    the empty-day "check another day?" case was tracked. Root-caused
    against a real transcript where "yes i want her" fell through to a
    from-scratch NLU guess and reached an empty vector search. See
    ROADMAP.md."""

    def test_found_slot_records_a_slot_confirmation_offer(self):
        offer = pending_offer_from_turn(
            sql_rows=[
                {
                    "handler": "doctor_availability",
                    "found": True,
                    "meta": {"temporal_searchable": True},
                    "rows": [
                        {
                            "doctor_id": "priya-1",
                            "doctor": "Dr. Priya Chandrasekaran",
                            "start": "2026-08-31T12:00:00-05:00",
                            "date": "2026-08-31",
                            "time": "12:00 PM",
                        }
                    ],
                }
            ],
            nlu=NLUResult(intent=Intent.BOOK_APPOINTMENT, confidence=0.85),
            last_doctor=None,
            matched_services=None,
        )
        self.assertEqual(offer["type"], "slot_confirmation")
        self.assertEqual(offer["doctor_id"], "priya-1")
        self.assertEqual(offer["doctor_name"], "Dr. Priya Chandrasekaran")
        self.assertEqual(offer["date"], "2026-08-31")

    def test_no_rows_records_nothing(self):
        offer = pending_offer_from_turn(
            sql_rows=[{"handler": "doctor_availability", "found": False, "rows": []}],
            nlu=NLUResult(intent=Intent.BOOK_APPOINTMENT, confidence=0.5),
            last_doctor=None,
            matched_services=None,
        )
        self.assertIsNone(offer)

    def test_classify_uptake_recognizes_the_reviewers_test_phrases(self):
        for phrase in ["yes i want her", "yes sure", "book it", "that doctor", "this one"]:
            with self.subTest(phrase=phrase):
                self.assertEqual(classify_uptake(phrase), "affirm", phrase)

    def test_classify_uptake_still_rejects_new_information(self):
        """The exact boundary this feature must never cross — unchanged
        from the pre-existing "yes, Thursday morning" rule, verified here
        against the new pattern's own near-miss cases: a message that
        *contains* an affirm word but also states something new (a
        different doctor, a specific day) is a fresh request, not uptake,
        and must be judged on its own NLU classification."""
        for phrase in [
            "yes, Thursday morning",
            "yes book me with Dr. Omar instead",
            "yes I want Dr. Omar",
            "book Dr. Omar",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIsNone(classify_uptake(phrase), phrase)

    def test_apply_pending_uptake_resolves_booking_with_the_offered_doctor(self):
        from apps.chatbot.conversation_state import apply_pending_uptake

        nlu = NLUResult(intent=Intent.FAQ, confidence=0.95, entities=ExtractedEntities())
        pending = {
            "type": "slot_confirmation",
            "doctor_id": "priya-1",
            "doctor_name": "Dr. Priya Chandrasekaran",
            "date": "2026-08-31",
            "time": "12:00 PM",
        }
        bound = apply_pending_uptake(nlu, pending)
        self.assertEqual(bound.intent, Intent.BOOK_APPOINTMENT)
        self.assertEqual(bound.resolved_ids.doctor_id, "priya-1")
        self.assertEqual(bound.raw.get("_pending_type"), "slot_confirmation")

    def test_planner_treats_a_resolved_slot_confirmation_as_a_real_booking_intent(self):
        """This is the second half of the fix, in planner.py — without it,
        apply_pending_uptake's correctly-rewritten intent=BOOK_APPOINTMENT
        still fell through to "clarify" because is_booking_intent
        re-derives its answer from the *raw message text* ("yes i want
        her" contains no transactional booking language), ignoring that
        the intent was already resolved. "book it" happened to work before
        this fix purely because it contains the literal word "book" —
        proving the gap was in the text-based re-derivation, not the
        uptake binder itself."""
        from apps.chatbot.planner import compute_message_sensors

        nlu = NLUResult(
            intent=Intent.BOOK_APPOINTMENT,
            confidence=0.95,
            entities=ExtractedEntities(),
            resolved_ids=ResolvedIds(doctor_id="priya-1"),
            raw={"_pending_uptake": "affirm", "_pending_type": "slot_confirmation"},
        )
        sensors = compute_message_sensors(
            message="yes i want her",
            nlu=nlu,
            document_catalog=[],
            service_catalog=[],
        )
        self.assertTrue(sensors.is_booking_intent)


class WorkingContextTests(SimpleTestCase):
    """Phase 39 — server-side working context. Root cause, reproduced
    against real trace logs (ROADMAP.md): "Based on what we already
    discussed, who did you recommend?" reached the Large LLM with only a
    thin recent-messages window to go on, and it invented "Dr. Omar
    Haddad" rather than admit it didn't know. These four classifiers keep
    that whole class of question — and a bare date/time retarget, and an
    ordinal doctor reference — out of the LLM/RAG lane, answered instead
    from ConversationTimeline facts this session actually produced."""

    def _timeline_with_pins(self, **kwargs) -> ConversationTimeline:
        return ConversationTimeline(**kwargs)

    # ── session_recall ────────────────────────────────────────────────
    def test_classify_session_recall_matches_the_transcript_phrases(self):
        cases = {
            "What insurance did I tell you I have?": "insurance",
            "Which doctor did you recommend?": "recommendation",
            "Who did you recommend?": "recommendation",
            "What were we just talking about?": "topic",
            "What was the appointment time you found?": "time",
            "I was asking you earlier about my child's fever. Based on "
            "what we already discussed, who did you recommend and what "
            "was the earliest appointment?": "recommendation",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(classify_session_recall(text), expected)

    def test_classify_session_recall_ignores_a_genuine_new_question(self):
        # Negative case from the plan: a clinic question, not recall.
        self.assertIsNone(classify_session_recall("What insurance do you accept?"))
        self.assertIsNone(classify_session_recall("Do you have a cardiologist?"))

    def test_compose_session_recall_insurance_present(self):
        tl = self._timeline_with_pins(insurance={"name": "Aetna PPO"})
        self.assertIn("Aetna PPO", compose_session_recall("insurance", tl))

    def test_compose_session_recall_insurance_absent_is_honest_not_invented(self):
        tl = self._timeline_with_pins()
        reply = compose_session_recall("insurance", tl)
        self.assertNotIn("Aetna", reply)
        self.assertIn("haven't told me", reply.lower())

    def test_compose_session_recall_recommendation_never_invents_a_doctor(self):
        """The exact hallucination this phase fixes: with no
        last_recommendation on the timeline, the template must say so
        plainly — never synthesize a doctor name from nothing."""
        tl = self._timeline_with_pins()
        reply = compose_session_recall("recommendation", tl)
        self.assertNotIn("Omar", reply)
        self.assertNotIn("Haddad", reply)
        self.assertIn("haven't recommended", reply.lower())

    def test_compose_session_recall_recommendation_present(self):
        tl = self._timeline_with_pins(
            last_recommendation={"id": "priya-1", "name": "Dr. Priya Chandrasekaran", "reason": "listed"}
        )
        self.assertIn("Dr. Priya Chandrasekaran", compose_session_recall("recommendation", tl))

    def test_compose_session_recall_time_present(self):
        tl = self._timeline_with_pins(
            last_slots=[
                {"doctor_id": "priya-1", "doctor_name": "Dr. Priya Chandrasekaran",
                 "date": "2026-08-31", "time": "12:00 PM"}
            ]
        )
        reply = compose_session_recall("time", tl)
        self.assertIn("12:00 PM", reply)
        self.assertIn("Dr. Priya Chandrasekaran", reply)

    # ── pin_amendment ─────────────────────────────────────────────────
    def test_pin_amendment_fires_only_with_an_open_doctor_or_availability_thread(self):
        tl_with_doctor = self._timeline_with_pins(doctor={"id": "priya-1", "name": "Dr. Priya"})
        tl_empty = self._timeline_with_pins()
        self.assertTrue(classify_pin_amendment("Actually Tuesday", tl_with_doctor))
        self.assertFalse(classify_pin_amendment("Actually Tuesday", tl_empty))

    def test_pin_amendment_recognizes_the_transcript_phrases(self):
        tl = self._timeline_with_pins(doctor={"id": "priya-1", "name": "Dr. Priya"})
        for text in [
            "Actually Tuesday",
            "No, Monday was better. Keep everything else the same",
            "make it tomorrow",
        ]:
            with self.subTest(text=text):
                self.assertTrue(classify_pin_amendment(text, tl), text)

    def test_pin_amendment_never_fires_on_a_confirmed_appointment(self):
        """Must never steal a real reschedule of an existing, confirmed
        appointment — that path requires identity verification and is
        deliberately left alone."""
        tl = self._timeline_with_pins(
            doctor={"id": "priya-1", "name": "Dr. Priya"}, booking_stage="confirmed"
        )
        self.assertFalse(classify_pin_amendment("Actually Tuesday", tl))

    # ── ordinal_doctor_ref ────────────────────────────────────────────
    def test_ordinal_doctor_ref_resolves_against_shown_doctors(self):
        tl = self._timeline_with_pins(
            shown_doctors=[
                {"id": "priya-1", "name": "Dr. Priya Chandrasekaran"},
                {"id": "whitaker-1", "name": "James Whitaker"},
            ]
        )
        ref = resolve_ordinal_doctor_ref(
            "The second doctor you mentioned, can she see my child?", tl
        )
        self.assertEqual(ref["id"], "whitaker-1")

    def test_ordinal_doctor_ref_out_of_range_returns_none(self):
        tl = self._timeline_with_pins(
            shown_doctors=[{"id": "priya-1", "name": "Dr. Priya Chandrasekaran"}]
        )
        self.assertIsNone(
            resolve_ordinal_doctor_ref("the second doctor you mentioned", tl)
        )

    def test_generic_pronoun_coreference_stays_deferred(self):
        """Negative case from the plan: "book with him" after a prose bio
        must still not resolve — that's general pronoun coreference,
        explicitly out of scope for this phase (see the "Deferred —
        Conversation state / coreference" entry in ROADMAP.md). Only
        ordinal list-index references ("the second doctor") are handled."""
        tl = self._timeline_with_pins(
            shown_doctors=[{"id": "chloe-1", "name": "Dr. Chloe Bennett"}]
        )
        self.assertIsNone(resolve_ordinal_doctor_ref("book with him", tl))

    # ── preview_only ──────────────────────────────────────────────────
    def test_classify_preview_only_recognizes_the_transcript_phrase(self):
        self.assertTrue(
            classify_preview_only("Wait, don't book it yet. Just show me the available times")
        )
        self.assertTrue(
            classify_preview_only(
                "don't book anything until you show me the doctor, price, insurance"
            )
        )

    def test_classify_preview_only_false_for_an_ordinary_booking_request(self):
        self.assertFalse(classify_preview_only("Book me with Dr Priya Monday afternoon"))

    # ── working-context writes (merge_turn_context) ──────────────────
    def test_shown_doctors_and_last_slots_are_capped(self):
        many_doctors = [{"id": f"d{i}", "name": f"Doctor {i}"} for i in range(10)]
        many_slots = [{"doctor_id": f"d{i}", "start": "x"} for i in range(10)]
        tl = ConversationTimeline()
        tl = merge_turn_context(tl, shown_doctors=many_doctors, last_slots=many_slots)
        self.assertEqual(len(tl.shown_doctors), 6)
        self.assertEqual(len(tl.last_slots), 8)

    def test_shown_doctors_overwrites_not_appends(self):
        tl = ConversationTimeline(shown_doctors=[{"id": "old-1", "name": "Old Doctor"}])
        tl = merge_turn_context(tl, shown_doctors=[{"id": "new-1", "name": "New Doctor"}])
        self.assertEqual([d["id"] for d in tl.shown_doctors], ["new-1"])
