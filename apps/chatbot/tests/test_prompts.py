"""NLU system prompt — guards against silently losing scoping rules."""

from __future__ import annotations

from django.test import SimpleTestCase

from apps.chatbot.nlu.prompts import get_system_prompt


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
