"""Minimal relative date/time parsing added for slot-filling ("Botox Friday after 5")."""

from __future__ import annotations

from datetime import time

from django.test import SimpleTestCase

from apps.chatbot.nlu.entity_extract import extract_entities
from apps.chatbot.sql_tool.utils import is_asap_request, is_same_day_request, parse_time_floor


class ParseTimeFloorTests(SimpleTestCase):
    def test_after_n_no_meridiem_assumes_evening(self):
        self.assertEqual(parse_time_floor(["after 5"]), time(17, 0))

    def test_after_n_am(self):
        self.assertEqual(parse_time_floor(["after 9am"]), time(9, 0))

    def test_after_n_pm(self):
        self.assertEqual(parse_time_floor(["after 2pm"]), time(14, 0))

    def test_after_n_in_am_window_stays_am(self):
        self.assertEqual(parse_time_floor(["after 9"]), time(9, 0))

    def test_after_work(self):
        self.assertEqual(parse_time_floor(["after work"]), time(17, 0))

    def test_time_of_day_words(self):
        self.assertEqual(parse_time_floor(["morning"]), time(8, 0))
        self.assertEqual(parse_time_floor(["evening"]), time(17, 0))

    def test_empty_returns_none(self):
        self.assertIsNone(parse_time_floor([]))
        self.assertIsNone(parse_time_floor(None))


class AsapSameDayTests(SimpleTestCase):
    def test_is_asap_request(self):
        self.assertTrue(is_asap_request("can you squeeze me in ASAP"))
        self.assertTrue(is_asap_request("what's the next available slot"))
        self.assertFalse(is_asap_request("I want to book Friday"))

    def test_is_same_day_request(self):
        self.assertTrue(is_same_day_request("do you have same day appointments"))
        self.assertFalse(is_same_day_request("do you have appointments tomorrow"))


class EntityExtractDateTimePatternsTests(SimpleTestCase):
    def test_extracts_after_time_phrase(self):
        entities = extract_entities("I want to book Botox Friday after 5")
        self.assertIn("friday", entities["date"])
        self.assertTrue(any("after 5" in t for t in entities["time"]))

    def test_extracts_after_work(self):
        entities = extract_entities("can I come in after work tomorrow")
        self.assertIn("tomorrow", entities["date"])
        self.assertIn("after work", entities["time"])

    def test_extracts_same_day_and_asap(self):
        same_day = extract_entities("do you have same day availability")
        self.assertIn("same day", same_day["date"])
        asap = extract_entities("need an appointment asap")
        self.assertIn("asap", asap["date"])
