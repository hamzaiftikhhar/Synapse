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
