"""Regression tests for response_templates.resolve_direct_template."""

from __future__ import annotations

from django.test import SimpleTestCase

from apps.chatbot.response_templates import get_response, resolve_direct_template


class OffTopicSubtypeTests(SimpleTestCase):
    def test_strip_does_not_match_travel_trip_keyword(self):
        """Phase 40: a real eHealthForum off-topic message about medical
        exam consent contains "...asked to strip down..." — naive substring
        containment matched "trip" inside "strip", routing an angry
        consent complaint to "Sounds like a great trip idea!"."""
        text = (
            "why is it that the medical profession is so behind the times "
            "when it comes to considering the feelings of husbands. i just "
            "learned my wife has been asked to strip down every time she "
            "sees him. what is your take on this?"
        )
        template_id = resolve_direct_template("off_topic", text)
        self.assertEqual(template_id, "OFF_TOPIC")

    def test_genuine_trip_still_routes_to_travel(self):
        template_id = resolve_direct_template(
            "off_topic", "any tips for planning a trip to Europe?"
        )
        self.assertEqual(template_id, "OFF_TOPIC_TRAVEL")

    def test_genuine_booking_word_still_routes_to_travel(self):
        template_id = resolve_direct_template(
            "off_topic", "any advice on booking a flight for cheap?"
        )
        self.assertEqual(template_id, "OFF_TOPIC_TRAVEL")

    def test_eating_does_not_match_bare_eat_keyword(self):
        template_id = resolve_direct_template(
            "off_topic", "why is everyone eating so late these days"
        )
        self.assertEqual(template_id, "OFF_TOPIC")

    def test_genuine_eat_keyword_still_routes_to_food(self):
        template_id = resolve_direct_template(
            "off_topic", "where should I eat tonight"
        )
        self.assertEqual(template_id, "OFF_TOPIC_FOOD")


class OffTopicAndClarifyWordingTests(SimpleTestCase):
    """Real production complaint: a garbled-but-clinic-relevant message
    ("i want to book and boone fracture thing" — a likely typo for "bone
    fracture") classified off_topic (correctly, given the confidence band —
    this is NOT a routing bug) got a flat "I'm here to assist with
    clinic-related questions" — asserting the topic itself is unrelated,
    which is simply false for a garbled clinical term. The fix is wording
    only: never claim the topic is unrelated, always invite a rephrase
    toward what's actually supported."""

    def test_off_topic_does_not_assert_the_topic_is_unrelated(self):
        text = get_response("OFF_TOPIC")
        for phrase in ("clinic-related questions", "only able to help", "I can only help"):
            self.assertNotIn(phrase, text)

    def test_off_topic_invites_a_rephrase(self):
        text = get_response("OFF_TOPIC").lower()
        self.assertIn("rephrase", text)

    def test_clarify_generic_gives_concrete_categories_not_bare_tell_me_more(self):
        text = get_response("CLARIFY_GENERIC")
        self.assertNotIn("a bit more about what you're looking for", text)
        for word in ("booking", "doctor", "service", "clinic"):
            self.assertIn(word, text.lower())
