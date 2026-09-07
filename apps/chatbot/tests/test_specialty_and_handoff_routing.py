"""Two live-reproduced production gaps, both confirmed deterministic (not
LLM non-determinism, unlike most of the other issues raised in the same
review — see ROADMAP.md for the honest breakdown of which is which):

1. "What are your specialties" and close variants ("what are you
   specialities", "do you have any specility") fell through to the
   vector-search FAQ lane, which has no document listing specialties, and
   always dead-ended in the generic "couldn't find clinic-specific
   information" apology — because `_SPECIALTY_LIST_RE` required "what"/
   "which" to sit immediately next to "special..." with no words between,
   and had no verb-first ("do you have...") alternative at all.

2. `Intent.HANDOFF_HUMAN` existed end-to-end (schema value, response
   template, planner direct-response gate) but the NLU prompt never told
   the model when to use it, so "are you a real person"/"can I talk to a
   human" always fell through to the generic clarify fallback instead of
   the friendly HANDOFF_HUMAN template. Fixed the prompt gap and also
   moved the intent into the unconditional _DIRECT_INTENTS set (like
   EMERGENCY already is) rather than leaving it dependent on the model
   separately setting can_respond_directly correctly for a brand-new
   instruction it had never been taught before.
"""

from __future__ import annotations

from django.test import SimpleTestCase, TestCase

from apps.chatbot.nlu.schemas import parse_nlu_payload
from apps.chatbot.planner import build_execution_plan, build_planner_facts
from apps.chatbot.response_templates import get_response, resolve_direct_template
from apps.chatbot.routing.signals import is_specialty_list_query
from apps.clinics.models import Clinic
from apps.specialties.models import Specialty


class SpecialtyListQueryPhrasingTests(SimpleTestCase):
    def test_filler_words_between_what_and_specialty(self):
        """Live-reproduced: "what are you specialities" (typo: "you" for
        "your") did not match at all."""
        self.assertTrue(is_specialty_list_query("what are you specialities"))
        self.assertTrue(is_specialty_list_query("what is your specialty"))

    def test_verb_first_phrasing(self):
        """Live-reproduced: "do you have any specility" -- verb-first word
        order was never covered by any of the original 4 alternatives."""
        self.assertTrue(is_specialty_list_query("do you have any specility"))
        self.assertTrue(is_specialty_list_query("do you have any specialty"))
        self.assertTrue(
            is_specialty_list_query("does the clinic have a specialty in cardiology")
        )

    def test_original_phrasings_still_match(self):
        self.assertTrue(is_specialty_list_query("what specialties do you offer"))
        self.assertTrue(is_specialty_list_query("which specialties do you have"))
        self.assertTrue(is_specialty_list_query("list of specialties"))

    def test_unrelated_special_phrases_do_not_match(self):
        """"Special" alone is a common enough word that this must stay
        scoped to the specialty-listing shape specifically."""
        self.assertFalse(is_specialty_list_query("what special offers do you have"))
        self.assertFalse(is_specialty_list_query("we have a special needs program"))
        self.assertFalse(
            is_specialty_list_query("is there a specialist for cardiac issues")
        )


class SpecialtyListEndToEndTests(TestCase):
    """The full path from a live-reported phrasing to real SQL rows, not
    just the regex in isolation."""

    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="specialty-routing-clinic",
            name="Specialty Routing Clinic",
            email="specialtyrouting@clinic.com",
            phone="+12125550017",
            timezone="America/New_York",
        )
        Specialty.objects.create(
            clinic=self.clinic, name="Cardiology", slug="cardiology"
        )

    def test_typo_phrasing_lists_real_specialties_not_generic_apology(self):
        from apps.chatbot.sql_tool import SQLTool

        nlu = parse_nlu_payload({"intent": "faq", "entities": {}})
        result = SQLTool.run(
            clinic=self.clinic, nlu=nlu, message="do you have any specility"
        )
        handlers = [r.handler for r in result]
        self.assertIn("list_specialties", handlers)


class HandoffHumanRoutingTests(SimpleTestCase):
    def test_prompt_teaches_the_model_when_to_use_it(self):
        from apps.chatbot.nlu.prompts import get_system_prompt

        prompt = get_system_prompt()
        self.assertIn("handoff_human", prompt.lower())
        self.assertIn("real person", prompt.lower())

    def test_resolves_to_the_friendly_template(self):
        template_id = resolve_direct_template("handoff_human", "are you a real person")
        self.assertEqual(template_id, "HANDOFF_HUMAN")
        self.assertIn("connect you with a team member", get_response(template_id, clinic_phone="555"))

    def test_direct_even_when_can_respond_directly_is_false(self):
        """The exact fragility this fix removes: previously, handoff_human
        only became a direct response if the model ALSO separately set
        can_respond_directly=True for an instruction it had never been
        taught before this phase — nothing verified that actually
        happened. Now unconditional, like EMERGENCY already is."""
        nlu = parse_nlu_payload(
            {
                "intent": "handoff_human",
                "confidence": 0.9,
                "can_respond_directly": False,
            }
        )
        facts = build_planner_facts(
            nlu=nlu,
            message="are you a real person",
            is_booking_intent=False,
            soft_medical=False,
            knowledge_q=False,
            has_catalog=False,
            doc_match=False,
            degraded=False,
            doctor_ranking_request=False,
            instruction_injection=False,
            unknown_doctor_requested=False,
        )
        plan = build_execution_plan(nlu=nlu, facts=facts)
        self.assertTrue(plan.direct)
        self.assertEqual(plan.direct_mode, "template")
