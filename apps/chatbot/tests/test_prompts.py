"""NLU system prompt — guards against silently losing scoping rules."""

from __future__ import annotations

from django.test import SimpleTestCase

from apps.chatbot.nlu.prompts import build_user_prompt, get_system_prompt


class SystemPromptTests(SimpleTestCase):
    def test_entities_must_come_from_current_message_only(self):
        """Regression: live-verifying the "Clarification flow" found the
        classifier sometimes copied the clinic's accepted-insurance list
        straight out of the Docs/Services background context into
        entities.insurance_provider for messages that never mentioned
        insurance (e.g. "banana purple seven") — because the prompt never
        told it not to. The prompt must explicitly scope entity extraction
        to the current message only."""
        prompt = get_system_prompt()
        self.assertIn("only what the user's current message states", prompt)
        self.assertIn("never copy a name from them", prompt)

    def test_user_prompt_omits_booking_draft(self):
        prompt = build_user_prompt(
            "I would like to book an appointment",
            {
                "booking": {
                    "date": "2026-08-25",
                    "step": "confirmed",
                    "reason": "Reschedule with Dr. Mei-Ling Zhou",
                },
                "services": "Botox",
            },
        )
        self.assertNotIn("2026-08-25", prompt)
        self.assertNotIn("Mei-Ling", prompt)
        self.assertIn("I would like to book an appointment", prompt)

    def test_user_prompt_omits_stale_timeline_state(self):
        """Live-confirmed contamination bug: "I need to get my blood drawn"
        (a fresh message with no symptom of its own) came back with
        entities.symptom="cut that needs stitches" and
        specialty_category_hint="Surgery" -- both copied from a *prior*
        turn's ConversationTimeline.problem, which save_timeline() (see
        conversation_state.py) writes onto the session's persisted ctx dict
        forever (no expiry) as both a nested "timeline" key and flattened
        "last_doctor"/"last_specialty"/"last_service"/"last_insurance"/
        "current_intent" keys. None of those were in this function's
        exclusion set, so they reached the LLM raw inside the "Ctx:" JSON
        blob on every subsequent turn -- the exact same bug class the
        "booking" exclusion two lines below already exists to prevent
        (see that key's own comment), just never extended to this one.
        Doctor-pronoun resolution ("book him again") is confirmed handled
        entirely in Python (conversation_state.py's regex matching), not
        by the LLM reading this data, so excluding it costs nothing."""
        prompt = build_user_prompt(
            "I need to get my blood drawn",
            {
                "timeline": {
                    "problem": "cut that needs stitches",
                    "doctor": {"id": "doc-1", "name": "Dr. Omar Haddad"},
                },
                "last_doctor": {"id": "doc-1", "name": "Dr. Omar Haddad"},
                "last_specialty": {"id": "spec-1", "name": "Surgery"},
                "last_service": {"id": "svc-1", "name": "Simple Wound Laceration Repair"},
                "last_insurance": {"name": "Aetna"},
                "current_intent": "doctor_search",
                "services": "Routine Blood Draw (Venipuncture)",
            },
        )
        self.assertNotIn("cut that needs stitches", prompt)
        self.assertNotIn("Omar Haddad", prompt)
        self.assertNotIn("Surgery", prompt)
        self.assertNotIn("Laceration", prompt)
        self.assertNotIn("Aetna", prompt)
        self.assertNotIn("doctor_search", prompt)
        self.assertIn("I need to get my blood drawn", prompt)

    def test_recent_turns_render_as_compact_text_not_json(self):
        """Root cause of the "sure"/"Earliest" misclassification bug
        (ROADMAP.md): a bare, context-dependent reply reached the NLU with
        zero memory of what the assistant had just said, so it guessed a
        topic from nothing. Verifies the plain-text rendering this session's
        fix relies on — never JSON (cheaper, and nothing to copy fields
        out of, matching the entities-from-current-message-only rule
        above)."""
        prompt = build_user_prompt(
            "sure",
            {
                "recent_turns": [
                    {"role": "user", "content": "where are you doctor placed"},
                    {
                        "role": "assistant",
                        "content": "Our clinic is located at 1420 North Interstate 35.",
                    },
                ]
            },
        )
        self.assertIn("Recent:", prompt)
        self.assertIn("U: where are you doctor placed", prompt)
        self.assertIn("A: Our clinic is located at", prompt)
        self.assertNotIn("{", prompt)  # no JSON leaking through for this section
        self.assertIn("sure", prompt)

    def test_recent_turns_are_truncated_and_malformed_entries_skipped(self):
        prompt = build_user_prompt(
            "sure",
            {
                "recent_turns": [
                    {"role": "user", "content": "x" * 300},
                    {"role": "system", "content": "should never appear"},
                    "not a dict",
                    {"role": "assistant", "content": ""},
                ]
            },
        )
        self.assertNotIn("x" * 300, prompt)
        self.assertIn("x" * 90, prompt)
        self.assertNotIn("should never appear", prompt)

    def test_recent_turns_excluded_from_generic_ctx_dump(self):
        """recent_turns must render under its own "Recent:" section, not
        get double-counted (and JSON-mangled) inside the catch-all "Ctx:"
        blob alongside the timeline/pending-clarification state."""
        prompt = build_user_prompt(
            "sure",
            {
                "recent_turns": [{"role": "user", "content": "hi"}],
                "some_other_ctx_key": "value",
            },
        )
        self.assertIn("Recent:", prompt)
        ctx_line = next(line for line in prompt.split("\n") if line.startswith("Ctx:"))
        self.assertNotIn("recent_turns", ctx_line)
        self.assertIn("some_other_ctx_key", ctx_line)

    def test_system_prompt_scopes_recent_turns_to_disambiguation_only(self):
        """Same "don't let background context invent facts" principle as
        the booking-draft test above, applied to the new recent-turns
        context: guards against a future edit letting history override or
        supply entities instead of merely resolving what a short reply's
        target is."""
        prompt = get_system_prompt()
        self.assertIn("Recent turns", prompt)
        self.assertIn("Never let recent turns override or supply an entity", prompt)

    def test_system_prompt_routes_capability_questions_away_from_faq(self):
        """Regression: "What can you help me with" / "what do you have"
        classified as faq -> vector search against clinic documents, which
        always returns zero hits (no clinic writes a document describing
        its own chatbot) -> the generic "couldn't find clinic-specific
        information" fallback, even though a correct canned answer already
        exists on the off_topic lane. Reproduced against the live backend
        with real production data (see ROADMAP.md)."""
        prompt = get_system_prompt()
        self.assertIn("off_topic, not faq", prompt)

    def test_system_prompt_has_generic_language_entity_and_doctor_search_rule(self):
        """Regression: "do you have doctors who speak Spanish/Punjabi" was
        classified off_topic — there was no language entity slot at all.
        The rule must name entities.language and stay phrased as a general
        category (any language name), never a fixed list of languages."""
        prompt = get_system_prompt()
        self.assertIn("language", prompt)
        self.assertIn("entities.language", prompt)
        self.assertIn("generalizes to any language name", prompt)
        # The fix must not degrade into per-language hardcoding.
        self.assertNotIn('"spanish"', prompt.lower())
        self.assertNotIn('"punjabi"', prompt.lower())

    def test_system_prompt_routes_named_procedure_questions_to_catalog(self):
        """Regression: "do you offer botox" / "how much is botox" were
        classified faq/off_topic with is_off_topic=True even though the SQL
        services/pricing catalog is the authoritative source for whether the
        clinic performs a named procedure — including when the honest answer
        is "not offered". The rule must be phrased generally (any named
        procedure), not name Botox specifically."""
        prompt = get_system_prompt()
        self.assertIn("services_offered or pricing", prompt)
        self.assertIn("even when that exact service isn't in the Services list", prompt)

    def test_system_prompt_routes_need_statements_to_services_not_just_questions(self):
        """Live-confirmed gap (ROADMAP.md, "Family 1"): "I need stitches
        for a cut" / "I need wound repair" classified medical_question/faq
        instead of services_offered, even though the existing rule already
        covers the identical yes/no phrasing ("do you offer stitches").
        Once intent misses, sql_tasks=[] and the service resolver
        (including the already-correct catalog_match tier) never runs at
        all. The rule must also distinguish a procedure-naming need
        statement from a concern-describing care-navigation request
        ("I have a cut, who should I see") staying doctor_search."""
        prompt = get_system_prompt()
        self.assertIn("need/want statement naming that procedure directly", prompt)
        self.assertIn("I need stitches for a cut", prompt)
        self.assertIn("describing a personal concern and asking who to see", prompt)

    def test_system_prompt_does_not_default_service_filter_mode_to_none_for_a_named_ask(self):
        """"Family 2" gap (ROADMAP.md): the model's own reasoning_short
        for "Can you stitch a cut?" literally said "Yes, we can stitch a
        cut" -- correctly understanding the request -- yet
        service_filter_mode still came back "none" (unfiltered browse of
        all 6 services) instead of a mode that lets the catalog resolve
        the specific match. Root cause verified against services.py: only
        "category" mode's fallback chain ever consults catalog_match --
        "named" mode has no such fallback, so telling the model to use
        "named" here (as originally suggested) would have dead-ended
        worse than today for a paraphrased ask like "stitches" that
        doesn't literally substring-match the real service name."""
        prompt = get_system_prompt()
        self.assertIn('is only for a genuine browse', prompt)
        self.assertIn("do you...", prompt)
        self.assertIn("different, informal wording than a catalog name", prompt)

    def test_system_prompt_routes_doctor_capability_questions_away_from_off_topic(self):
        """Root cause of Bug B's clearest reproduction (ROADMAP.md,
        StackUp Technologies live trace): "Do you have any cardiology
        specialist?" and "Do you have any heart specialist?" at the same
        dental clinic both classified off_topic at confidence 0.2 --
        repeatedly, live-reproduced -- even though the model's own
        reasoning_short text showed it understood exactly what was being
        asked ("Cardiology is outside dental services"). The prompt
        already had this exact rule for services_offered/pricing (a named
        procedure question is never off_topic even when "not offered" is
        the honest answer) but no analogous rule for doctor_search -- this
        locks in the missing half."""
        prompt = get_system_prompt()
        self.assertIn("HAS a doctor/specialist", prompt)
        self.assertIn("is still doctor_search, not off_topic", prompt)

    def test_system_prompt_distinguishes_emergency_from_scheduling_urgency(self):
        """Regression: "asap, need someone today" was classified emergency
        at real confidence — the prompt had no boundary between a danger
        symptom and wanting the earliest appointment. Must not enumerate
        urgency words as a special case, only frame the distinction."""
        prompt = get_system_prompt()
        self.assertIn("is NOT emergency by itself", prompt)
        self.assertIn("danger symptom", prompt)

    def test_system_prompt_documents_catalog_match_field(self):
        """Phase 2 of the catalog-matching plan (ROADMAP.md): the model
        must be told the field exists, told it's current-message-only (no
        context contamination from recent turns), told never to invent an
        id, and told it's scoped to explicit capability requests -- never
        a symptom/condition narrative, which stays on the existing
        concern-map path instead."""
        prompt = get_system_prompt()
        self.assertIn("catalog_match", prompt)
        self.assertIn("never invented", prompt)
        self.assertIn("current-turn text only", prompt)
        self.assertIn("Never for a symptom/condition narrative", prompt)
        self.assertIn("not_applicable", prompt)

    def test_system_prompt_documents_medical_question_mode_field(self):
        """Root cause of the "What is hypothyroidism?"/"What is a crown?"
        bug (ROADMAP.md): medical_question was a single bucket with no
        way to distinguish a definitional question from a personal
        symptom disclosure from a personalized risk question. The model
        must be told the field exists, told the three values and how to
        pick between them, told a generic (non-personalized) risk/side-
        effect question stays definitional, and told the field never
        changes which intent to pick."""
        prompt = get_system_prompt()
        self.assertIn("medical_question_mode", prompt)
        self.assertIn('"definitional"', prompt)
        self.assertIn('"personal"', prompt)
        self.assertIn('"risk"', prompt)
        self.assertIn("What are the side effects of ibuprofen?", prompt)
        self.assertIn("never changes which intent to pick", prompt)

    def test_user_prompt_renders_capability_catalog_as_its_own_block(self):
        """The id-bearing Catalog: block must be distinct from the
        plain-name Services:/Doctors: blocks entity extraction reads for
        grounding -- never merged, since one carries ids meant to be
        copied verbatim and the other must never have its values copied
        into an entity field at all."""
        prompt = build_user_prompt(
            "Do you have a rheumatologist?",
            {
                "services": "Consultation",
                "capability_catalog": "[specialty] id=abc-123 name=Cardiology",
            },
        )
        self.assertIn("Catalog:", prompt)
        self.assertIn("[specialty] id=abc-123 name=Cardiology", prompt)
        self.assertIn("Services: Consultation", prompt)

    def test_capability_catalog_excluded_from_generic_ctx_dump(self):
        prompt = build_user_prompt(
            "Do you have a rheumatologist?",
            {
                "capability_catalog": "[specialty] id=abc-123 name=Cardiology",
                "some_other_ctx_key": "value",
            },
        )
        ctx_line = next(line for line in prompt.split("\n") if line.startswith("Ctx:"))
        self.assertNotIn("capability_catalog", ctx_line)
        self.assertNotIn("abc-123", ctx_line)

    def test_system_prompt_gives_a_compound_secondary_intents_example(self):
        """Regression: "do you accept aetna and can I see dr vance next
        tuesday" only answered the insurance half — secondary_intents was
        never populated. The existing "Compound->secondary_intents" rule had
        no example of what counts as compound; this locks in a concrete,
        category-level (not phrase-specific) example."""
        prompt = get_system_prompt()
        self.assertIn("secondary_intents so both get answered", prompt)
