"""Regression tests for response_templates.resolve_direct_template."""

from __future__ import annotations

from django.test import SimpleTestCase

from apps.chatbot.response_templates import resolve_direct_template


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
