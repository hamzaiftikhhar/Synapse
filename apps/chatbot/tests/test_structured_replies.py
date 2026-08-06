"""Structured SQL formatter — grouped hours and concise availability."""

from __future__ import annotations

from django.test import SimpleTestCase

from apps.chatbot.sql_tool.formatter import format_sql_results


class StructuredRepliesTests(SimpleTestCase):
    def test_hours_grouped_not_semicolon_dump(self):
        rows = [
            {"handler": "clinic_hours", "found": True, "rows": [
                {"day": "Monday", "open_time": "08:00 AM", "close_time": "05:00 PM", "is_closed": False},
                {"day": "Tuesday", "open_time": "08:00 AM", "close_time": "05:00 PM", "is_closed": False},
                {"day": "Wednesday", "open_time": "08:00 AM", "close_time": "05:00 PM", "is_closed": False},
                {"day": "Saturday", "open_time": "", "close_time": "", "is_closed": True},
            ]},
        ]
        text = format_sql_results(rows)
        self.assertIn("Monday–Wednesday", text)
        self.assertNotIn("Monday 08:00 AM–05:00 PM; Tuesday", text)

    def test_availability_concise(self):
        rows = [
            {"handler": "doctor_availability", "found": True, "rows": [
                {"doctor": "Dr. Aris Thorne", "time": "9:00 AM", "start": "2026-08-07T09:00:00"},
                {"doctor": "Dr. Aris Thorne", "time": "10:00 AM", "start": "2026-08-07T10:00:00"},
            ]},
        ]
        text = format_sql_results(rows)
        self.assertIn("Earliest opening", text)
        self.assertNotIn("- Dr.", text)
