"""ChatEngine._general_knowledge_reply / response_llm.generate_general_knowledge_reply

Part of the "Separate 'explain a concept' / 'personal symptom' / 'risk
question' inside medical_question" plan (ROADMAP.md) -- the new,
ungrounded response path for a purely definitional medical question
("What is hypothyroidism?"), as distinct from the existing grounded-RAG
(response_llm.py's `_system_prompt`/`synthesize_clinic_reply`) and
soft_medical (engine.py's `_soft_medical_reply`) paths.
"""

from __future__ import annotations

from unittest.mock import patch

from django.test import SimpleTestCase

from apps.chatbot.engine import ChatEngine
from apps.chatbot.response_llm import build_general_knowledge_prompts


class BuildGeneralKnowledgePromptsTests(SimpleTestCase):
    def test_system_prompt_allows_general_knowledge(self):
        prompts = build_general_knowledge_prompts("What is hypothyroidism?")
        self.assertIn("general medical knowledge", prompts["system_prompt"])

    def test_system_prompt_forbids_diagnosis_and_personal_advice(self):
        prompts = build_general_knowledge_prompts("What is hypothyroidism?")
        self.assertIn("Never diagnose the user", prompts["system_prompt"])
        self.assertIn("never recommend a specific treatment", prompts["system_prompt"])

    def test_system_prompt_does_not_force_a_booking_pitch(self):
        """Corrected per review: a purely educational answer should not
        be forced to end with an appointment pitch every time."""
        prompts = build_general_knowledge_prompts("What is hypothyroidism?")
        self.assertIn("do not pad it with an appointment pitch by default", prompts["system_prompt"])

    def test_user_prompt_is_the_raw_message(self):
        prompts = build_general_knowledge_prompts("  What is a crown?  ")
        self.assertEqual(prompts["user_prompt"], "What is a crown?")

    def test_never_reuses_the_rag_grounded_system_prompt(self):
        """Must be a genuinely separate prompt from the RAG-grounded one
        -- that one explicitly forbids answering from general knowledge
        ("use ONLY the provided knowledge excerpts... never invent one"),
        which is the opposite of what this path needs to do."""
        prompts = build_general_knowledge_prompts("What is hypothyroidism?")
        self.assertNotIn("RAG lane only", prompts["system_prompt"])
        self.assertNotIn("never invent one", prompts["system_prompt"])


class GeneralKnowledgeReplyEngineTests(SimpleTestCase):
    @patch("apps.chatbot.response_llm.generate_general_knowledge_reply")
    def test_returns_the_llm_generated_text(self, mock_generate):
        mock_generate.return_value = "Hypothyroidism is a condition where..."
        result = ChatEngine()._general_knowledge_reply("What is hypothyroidism?")
        self.assertEqual(result, "Hypothyroidism is a condition where...")
        mock_generate.assert_called_once_with("What is hypothyroidism?")

    @patch("apps.chatbot.response_llm.generate_general_knowledge_reply")
    def test_falls_back_to_static_line_on_provider_failure(self, mock_generate):
        """Never let an LLM outage produce no reply at all -- same
        fail-safe posture as the rest of this pipeline."""
        mock_generate.side_effect = Exception("provider timeout")
        result = ChatEngine()._general_knowledge_reply("What is hypothyroidism?")
        self.assertIn("find a doctor", result.lower())
