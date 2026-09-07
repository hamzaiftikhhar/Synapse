"""Pre-production safety review: live-reproduced gaps in suicide/self-harm
crisis handling.

Two confirmed bugs, both P0:

1. `EMERGENCY_RE` (nlu/emergency_patterns.py, the deterministic fail-closed
   safety net documented as "never wait for the Small LLM") did not match
   the plain word "suicide" at all -- only the adjective "suicidal" and
   "kill myself". A real user's "i want to do sucide" (a common typo) also
   didn't match. Confirmed live: with the LLM classifying correctly, this
   was masked; a live OpenAI timeout during this same review caused the
   *identical* symptom-shaped message to fall through the rules-fallback
   tier to a generic, non-emergency clarify response instead -- i.e. under
   real production failure conditions (the exact scenario the deterministic
   layer exists for), a suicide disclosure could be missed entirely.

2. Even when correctly classified as an emergency, the response was always
   the generic 911/physical-emergency message. `response_templates.py`
   already had a proper `EMERGENCY_MENTAL_HEALTH` template (988 Suicide &
   Crisis Lifeline), but `engine.py`'s fast paths always returned
   `EMERGENCY_SAFETY_MESSAGE` first, before `resolve_direct_template`'s
   mental-health branch was ever reached -- structurally unreachable dead
   code, confirmed by reading the two call sites, not assumed.

A third, related gap (not a hard safety bug, but confirmed live): once a
self-harm disclosure occurs, a later turn with no self-harm language of
its own ("what are your business hours") got zero further acknowledgment
of the crisis -- a real multi-turn transcript showed the bot fully
reverting to ordinary clinic-FAQ/marketing copy 2-3 turns later with no
safety net at all. `ConversationTimeline.medical_flags` already existed
for exactly this kind of session-scoped signal but had no writer anywhere
in engine.py. Fixed by setting it whenever a turn's safety message is the
988 one, and appending a short reminder to later replies in the same
session that don't already mention 988 (never doubles up on a turn that's
itself re-classified as emergency again, which the live LLM sometimes
does given recent crisis context in the conversation history -- that's
its own semantic judgment call, not something this fix tries to control).
"""

from __future__ import annotations

from django.test import SimpleTestCase, TestCase

from apps.chatbot.conversation_state import ConversationTimeline
from apps.chatbot.nlu.decision import (
    DecisionEngine,
    EMERGENCY_SAFETY_MESSAGE,
    emergency_safety_message,
)
from apps.chatbot.nlu.emergency_patterns import EMERGENCY_RE, is_self_harm_mention
from apps.chatbot.nlu.schemas import ExtractedEntities, Intent, NLUResult, Route
from apps.chatbot.response_templates import get_response, resolve_direct_template
from apps.clinics.models import Clinic


class EmergencyRegexSelfHarmTests(SimpleTestCase):
    """The deterministic, pre-LLM safety net must catch plain self-harm
    language, not just the adjective form -- confirmed broken before this
    fix (see module docstring)."""

    def test_plain_suicide_word_is_a_hard_emergency_trigger(self):
        self.assertTrue(EMERGENCY_RE.search("i want to commit suicide"))
        self.assertTrue(EMERGENCY_RE.search("suicide"))

    def test_suicidal_adjective_still_matches(self):
        self.assertTrue(EMERGENCY_RE.search("i am suicidal"))

    def test_kill_myself_still_matches(self):
        self.assertTrue(EMERGENCY_RE.search("i want to kill myself"))

    def test_common_suicide_typos_match(self):
        """Live-reproduced: a real user typed "sucide" -- one transposed
        letter is enough that `suicid\\w*` alone would still miss it."""
        for typo in ("i want to do sucide", "thinking about suicde", "suiside thoughts"):
            with self.subTest(typo=typo):
                self.assertTrue(EMERGENCY_RE.search(typo))

    def test_additional_self_harm_phrases_match(self):
        for phrase in (
            "i want to end my life",
            "i don't want to live anymore",
            "i want to hurt myself",
            "i took an overdose",
        ):
            with self.subTest(phrase=phrase):
                self.assertTrue(EMERGENCY_RE.search(phrase))

    def test_slit_lamp_exam_is_not_a_false_positive(self):
        """"Slit" alone is a real ophthalmology term (slit lamp exam) --
        must not fire a suicide-crisis response for a routine eye-exam
        question."""
        self.assertFalse(EMERGENCY_RE.search("what is a slit lamp exam"))
        self.assertFalse(is_self_harm_mention("what is a slit lamp exam"))

    def test_jump_the_queue_is_not_a_false_positive(self):
        self.assertFalse(EMERGENCY_RE.search("can i jump the queue"))
        self.assertFalse(is_self_harm_mention("can i jump the queue"))

    def test_ordinary_messages_do_not_match(self):
        for msg in ("can you help me find a doctor", "is dr vance available monday"):
            with self.subTest(msg=msg):
                self.assertFalse(EMERGENCY_RE.search(msg))
                self.assertFalse(is_self_harm_mention(msg))

    def test_physical_emergency_is_not_flagged_as_self_harm(self):
        self.assertTrue(EMERGENCY_RE.search("chest pain radiating to my arm"))
        self.assertFalse(is_self_harm_mention("chest pain radiating to my arm"))


class EmergencySafetyMessageSelectionTests(SimpleTestCase):
    """emergency_safety_message() is the one shared place both the live
    engine and the offline eval battery pick between the two safety
    messages -- this locks in that it actually picks correctly."""

    def test_self_harm_message_gets_988_crisis_line(self):
        msg = emergency_safety_message("i want to commit suicide")
        self.assertIn("988", msg)
        self.assertEqual(msg, get_response("EMERGENCY_MENTAL_HEALTH"))

    def test_typo_self_harm_message_gets_988_crisis_line(self):
        msg = emergency_safety_message("i want to do sucide")
        self.assertIn("988", msg)

    def test_physical_emergency_gets_generic_911_message(self):
        msg = emergency_safety_message("chest pain radiating to my arm")
        self.assertNotIn("988", msg)
        self.assertEqual(msg, EMERGENCY_SAFETY_MESSAGE)

    def test_symptom_hint_alone_can_trigger_988(self):
        """Some call sites (DecisionEngine) may only have the NLU's
        entities.symptom, not the raw message -- must still work."""
        msg = emergency_safety_message("", symptom_hint="suicide")
        self.assertIn("988", msg)


class ResolveDirectTemplateEmergencyTests(SimpleTestCase):
    def test_suicide_message_resolves_to_mental_health_template(self):
        template_id = resolve_direct_template("emergency", "i want to commit suicide")
        self.assertEqual(template_id, "EMERGENCY_MENTAL_HEALTH")

    def test_physical_emergency_resolves_to_generic_template(self):
        template_id = resolve_direct_template("emergency", "severe bleeding")
        self.assertEqual(template_id, "EMERGENCY")


class DecisionEngineEmergencySafetyMessageTests(SimpleTestCase):
    """DecisionEngine.decide() (used by the offline eval battery) must
    make the same mental-health-vs-physical choice the live engine does."""

    def _nlu(self, *, symptom=None) -> NLUResult:
        return NLUResult(
            intent=Intent.EMERGENCY,
            confidence=0.99,
            entities=ExtractedEntities(symptom=symptom),
            is_emergency=True,
            needs_sql=False,
            needs_vector=False,
            needs_llm=False,
        )

    def test_message_drives_the_choice(self):
        decision = DecisionEngine.decide(self._nlu(), message="i want to commit suicide")
        self.assertEqual(decision.route, Route.EMERGENCY)
        self.assertIn("988", decision.safety_message)

    def test_symptom_entity_alone_drives_the_choice_without_message(self):
        decision = DecisionEngine.decide(self._nlu(symptom=["suicide"]))
        self.assertIn("988", decision.safety_message)

    def test_physical_emergency_without_self_harm_signal(self):
        decision = DecisionEngine.decide(
            self._nlu(symptom=["chest pain"]), message="chest pain radiating to my arm"
        )
        self.assertNotIn("988", decision.safety_message)


class ChatEngineEmergencyResponseTests(TestCase):
    """End-to-end through the real ChatEngine.process() -- no LLM mocking
    needed: a genuine self-harm/emergency message is caught by the
    deterministic pre-LLM safety-rule tier (nlu/rules.py::_match_safety),
    which never makes a network call, so this is a fully real, fully
    deterministic test of production behavior."""

    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="emergency-safety-clinic",
            name="Emergency Safety Clinic",
            email="emergencysafety@clinic.com",
            phone="+12125550015",
            timezone="America/New_York",
        )

    def test_suicide_disclosure_gets_988_crisis_line_not_generic_911(self):
        from apps.chatbot.engine import ChatEngine

        result = ChatEngine().process(clinic=self.clinic, message="i want to commit suicide")
        self.assertEqual(result.route, "emergency")
        self.assertIn("988", result.response)

    def test_common_suicide_typo_still_gets_988_crisis_line(self):
        """The exact live-reproduced case: a real user typed this and, at
        the time, the deterministic layer missed it entirely."""
        from apps.chatbot.engine import ChatEngine

        result = ChatEngine().process(clinic=self.clinic, message="i want to do sucide")
        self.assertEqual(result.route, "emergency")
        self.assertIn("988", result.response)

    def test_kill_myself_gets_988_crisis_line(self):
        from apps.chatbot.engine import ChatEngine

        result = ChatEngine().process(clinic=self.clinic, message="i want to kill myself")
        self.assertEqual(result.route, "emergency")
        self.assertIn("988", result.response)

    def test_physical_emergency_gets_generic_911_message_not_988(self):
        from apps.chatbot.engine import ChatEngine

        result = ChatEngine().process(
            clinic=self.clinic, message="i have severe bleeding and can't stop it"
        )
        self.assertEqual(result.route, "emergency")
        self.assertNotIn("988", result.response)
        self.assertIn("911", result.response)

    def test_slit_lamp_question_is_not_treated_as_an_emergency(self):
        from apps.chatbot.engine import ChatEngine

        result = ChatEngine().process(
            clinic=self.clinic, message="do you offer a slit lamp exam"
        )
        self.assertNotEqual(result.route, "emergency")


class CrisisPersistenceAcrossTurnsTests(TestCase):
    """A self-harm disclosure earlier in the session must not go silently
    unacknowledged just because a later turn's own message isn't itself
    emergency-shaped — live-reproduced gap, see module docstring."""

    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="crisis-persistence-clinic",
            name="Crisis Persistence Clinic",
            email="crisispersistence@clinic.com",
            phone="+12125550016",
            timezone="America/New_York",
        )

    def _session(self, medical_flags=None):
        from apps.chatbot.models import ChatSession, ChatSessionStatus

        return ChatSession.objects.create(
            clinic=self.clinic,
            session_token="crisis-persistence-token",
            status=ChatSessionStatus.ACTIVE,
            conversation_context={"timeline": {"medical_flags": medical_flags or []}},
        )

    def test_medical_flags_set_after_a_self_harm_turn(self):
        from apps.chatbot.engine import ChatEngine

        session = self._session()
        ChatEngine().process(
            clinic=self.clinic, message="i want to commit suicide", session=session
        )
        session.refresh_from_db()
        timeline = (session.conversation_context or {}).get("timeline") or {}
        self.assertIn("self_harm", timeline.get("medical_flags") or [])

    def test_later_unrelated_turn_gets_crisis_reminder_appended(self):
        """"What are your business hours" is answered by a deterministic
        pre-LLM rule (no network call), so this is fully deterministic."""
        from apps.chatbot.engine import ChatEngine

        session = self._session(medical_flags=["self_harm"])
        result = ChatEngine().process(
            clinic=self.clinic, message="what are your business hours", session=session
        )
        self.assertNotEqual(result.route, "emergency")
        self.assertIn("988", result.response)

    def test_no_reminder_without_a_prior_crisis_flag(self):
        """Regression guard: an ordinary session must not get the
        reminder — this isn't a permanent footer on every reply."""
        from apps.chatbot.engine import ChatEngine

        session = self._session(medical_flags=[])
        result = ChatEngine().process(
            clinic=self.clinic, message="what are your business hours", session=session
        )
        self.assertNotIn("988", result.response)

    def test_no_double_reminder_when_turn_is_reclassified_as_emergency(self):
        """If a later turn is itself (re-)classified as an emergency, its
        own response already carries the crisis line — must not also
        append a second, redundant reminder."""
        from apps.chatbot.engine import ChatEngine

        session = self._session(medical_flags=["self_harm"])
        result = ChatEngine().process(
            clinic=self.clinic, message="i want to kill myself", session=session
        )
        self.assertEqual(result.route, "emergency")
        self.assertEqual(result.response.count("988"), 1)

    def test_timeline_from_dict_round_trips_medical_flags(self):
        """Direct unit check on the persistence mechanism itself, isolated
        from the full engine — ConversationTimeline already had this field
        but nothing ever exercised its round trip."""
        timeline = ConversationTimeline.from_dict({"medical_flags": ["self_harm"]})
        self.assertEqual(timeline.medical_flags, ["self_harm"])
        self.assertEqual(
            ConversationTimeline.from_dict(timeline.to_dict()).medical_flags,
            ["self_harm"],
        )
