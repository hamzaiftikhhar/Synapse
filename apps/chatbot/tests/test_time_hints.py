"""Minimal relative date/time parsing added for slot-filling ("Botox Friday after 5")."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

from apps.chatbot.nlu.entity_extract import extract_entities
from apps.chatbot.sql_tool.utils import (
    format_clinic_when,
    is_asap_request,
    is_same_day_request,
    parse_natural_date,
    parse_time_floor,
)


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

    def test_clock_times(self):
        self.assertEqual(parse_time_floor(["9 pm"]), time(21, 0))
        self.assertEqual(parse_time_floor(["10:30"]), time(10, 30))
        self.assertEqual(parse_time_floor(["3 pm"]), time(15, 0))
        # Clock wins over vague period when both present
        self.assertEqual(parse_time_floor(["evening", "12 pm"]), time(12, 0))

    def test_time_of_day_ceiling(self):
        from apps.chatbot.sql_tool.utils import parse_time_ceiling

        self.assertEqual(parse_time_ceiling(["morning"]), time(12, 0))
        self.assertEqual(parse_time_ceiling(["afternoon"]), time(17, 0))
        self.assertIsNone(parse_time_ceiling(["9 pm"]))

    def test_empty_returns_none(self):
        self.assertIsNone(parse_time_floor([]))
        self.assertIsNone(parse_time_floor(None))


class AsapSameDayTests(SimpleTestCase):
    def test_is_asap_request(self):
        self.assertTrue(is_asap_request("can you squeeze me in ASAP"))
        self.assertTrue(is_asap_request("what's the next available slot"))
        self.assertFalse(is_asap_request("I want to book Friday"))
        for message in (
            "book with Dr Maya instantly",
            "can she take me immediately",
            "get me in right away if there's a gap",
        ):
            self.assertTrue(is_asap_request(message), msg=message)

    def test_friday_is_not_asap(self):
        self.assertFalse(is_asap_request("I want to book Friday"))

    def test_is_same_day_request(self):
        self.assertTrue(is_same_day_request("do you have same day appointments"))
        self.assertFalse(is_same_day_request("do you have appointments tomorrow"))

    def test_yesterday_is_the_previous_calendar_day(self):
        tz = ZoneInfo("America/Los_Angeles")
        today = datetime.now(tz).date()
        self.assertEqual(parse_natural_date("yesterday", tz=tz), today - timedelta(days=1))

    def test_today_and_tomorrow_are_unchanged(self):
        tz = ZoneInfo("America/Los_Angeles")
        today = datetime.now(tz).date()
        self.assertEqual(parse_natural_date("today", tz=tz), today)
        self.assertEqual(parse_natural_date("tomorrow", tz=tz), today + timedelta(days=1))


class EntityExtractDateTimePatternsTests(SimpleTestCase):
    def test_extracts_after_time_phrase(self):
        entities = extract_entities("I want to book Botox Friday after 5")
        self.assertIn("friday", entities["date"])
        self.assertTrue(any("after 5" in t for t in entities["time"]))

    def test_extracts_clock_times(self):
        entities = extract_entities(
            "can you please help me to book a slot of doctor for 9 pm wednesday"
        )
        self.assertIn("wednesday", entities["date"])
        self.assertTrue(any("9" in t and "pm" in t for t in entities["time"]))

    def test_extracts_after_work(self):
        entities = extract_entities("can I come in after work tomorrow")
        self.assertIn("tomorrow", entities["date"])
        self.assertIn("after work", entities["time"])

    def test_extracts_same_day_and_asap(self):
        same_day = extract_entities("do you have same day availability")
        self.assertIn("same day", same_day["date"])
        asap = extract_entities("need an appointment asap")
        self.assertIn("asap", asap["date"])


class ParseNaturalDateWeekdayTests(SimpleTestCase):
    TZ = ZoneInfo("America/Los_Angeles")

    def _next(self, weekday: int) -> date:
        today = datetime.now(self.TZ).date()
        return today + timedelta(days=(weekday - today.weekday()) % 7 or 7)

    def test_weekday_abbreviations(self):
        for raw, weekday in (
            ("thursday", 3),
            ("thurs", 3),
            ("thur", 3),
            ("thu", 3),
            ("tuesday", 1),
            ("tues", 1),
            ("tue", 1),
            ("weds", 2),
            ("wed", 2),
            ("fri", 4),
            ("sun", 6),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(parse_natural_date(raw, tz=self.TZ), self._next(weekday))

    def test_day_survives_a_trailing_time_of_day(self):
        self.assertEqual(parse_natural_date("thurs afternoon", tz=self.TZ), self._next(3))
        self.assertEqual(parse_natural_date("Sunday afternoon", tz=self.TZ), self._next(6))

    def test_words_merely_containing_a_day_are_not_dates(self):
        for raw in ("sunscreen", "sun damage treatment", "wedding", "monsoon"):
            with self.subTest(raw=raw):
                self.assertIsNone(parse_natural_date(raw, tz=self.TZ))


class FormatClinicWhenTests(SimpleTestCase):
    def test_midnight_is_12_am_not_0_00(self):
        dt = datetime(2026, 8, 13, 19, 0, tzinfo=dt_timezone.utc)
        label = format_clinic_when(dt, ZoneInfo("Asia/Karachi"))
        self.assertEqual(label, "Fri 14 Aug, 12:00 AM")
        self.assertNotIn("0:00", label)

    def test_afternoon_is_12_hour(self):
        dt = datetime(2026, 8, 20, 12, 0, tzinfo=dt_timezone.utc)
        label = format_clinic_when(dt, ZoneInfo("Asia/Karachi"))
        self.assertEqual(label, "Thu 20 Aug, 5:00 PM")
