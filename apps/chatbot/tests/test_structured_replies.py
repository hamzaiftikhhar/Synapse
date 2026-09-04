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

    def test_rejected_insurance_uses_handler_summary_not_search_prompt(self):
        text = format_sql_results(
            [
                {
                    "handler": "insurance_accepted",
                    "found": True,
                    "summary": "No — we currently don't accept Aetna.",
                    "rows": [
                        {
                            "provider_name": "Aetna",
                            "plan_name": "Gold",
                            "is_accepted": False,
                        }
                    ],
                }
            ]
        )
        self.assertIn("No — we currently don't accept Aetna", text)
        self.assertNotIn("Search your plan below", text)

    def test_mixed_insurance_uses_summary(self):
        text = format_sql_results(
            [
                {
                    "handler": "insurance_accepted",
                    "found": True,
                    "summary": "Yes — we accept Aetna (PPO). We currently don't accept Aetna (HMO).",
                    "rows": [
                        {"provider_name": "Aetna", "plan_name": "PPO", "is_accepted": True},
                        {"provider_name": "Aetna", "plan_name": "HMO", "is_accepted": False},
                    ],
                }
            ]
        )
        self.assertIn("Yes — we accept Aetna (PPO)", text)
        self.assertIn("We currently don't accept Aetna (HMO)", text)
        self.assertNotIn("Search your plan below", text)

    def test_single_accepted_insurance_match_uses_summary_not_search_prompt(self):
        """A single named-provider match that IS accepted is a direct "Yes"
        answer worth stating, not a content-free search prompt — distinct
        from the genuine multi-provider browse case just below, which
        deliberately keeps the search prompt (test_accepted_insurance_
        browse_keeps_search_prompt)."""
        text = format_sql_results(
            [
                {
                    "handler": "insurance_accepted",
                    "found": True,
                    "summary": "Yes — we accept Aetna.",
                    "rows": [
                        {"provider_name": "Aetna", "is_accepted": True},
                    ],
                }
            ]
        )
        self.assertEqual(text, "Yes — we accept Aetna.")

    def test_accepted_insurance_browse_keeps_search_prompt(self):
        text = format_sql_results(
            [
                {
                    "handler": "insurance_accepted",
                    "found": True,
                    "summary": "We accept plans including: Aetna, Cigna.",
                    "rows": [
                        {"provider_name": "Aetna", "is_accepted": True},
                        {"provider_name": "Cigna", "is_accepted": True},
                    ],
                }
            ]
        )
        self.assertEqual(text, "Search your plan below.")

    def test_patient_appointments_uses_when_not_iso(self):
        text = format_sql_results(
            [
                {
                    "handler": "patient_appointments",
                    "found": True,
                    "rows": [
                        {
                            "doctor": "Dr. Chloe Bennett",
                            "start_time": "2026-08-13T19:00:00+00:00",
                            "when": "Fri 14 Aug, 12:00 AM",
                            "status": "confirmed",
                        }
                    ],
                }
            ]
        )
        self.assertIn("Fri 14 Aug, 12:00 AM", text)
        self.assertNotIn("T19:00:00", text)
        self.assertNotIn("+00:00", text)

    def test_search_doctors_authoritative_not_found_summary_survives_formatting(self):
        """Live-confirmed regression: search_doctors' honest "we don't have
        a specialist for that" (meta.authoritative_summary, added when a
        symptom matches no clinic specialty) used to be unconditionally
        replaced by the generic EMPTY_DOCTORS constant here -- the same
        rule doctor_availability already followed just above in this same
        formatter function, search_doctors simply never had it."""
        text = format_sql_results(
            [
                {
                    "handler": "search_doctors",
                    "found": False,
                    "rows": [],
                    "summary": "We don't have a specialist for that here.",
                    "meta": {"authoritative_summary": True},
                }
            ]
        )
        self.assertEqual(text, "We don't have a specialist for that here.")

    def test_search_doctors_non_authoritative_not_found_keeps_generic_copy(self):
        """Without the flag, existing behavior (e.g. a name/language filter
        that matched nothing) is unchanged -- generic EMPTY_DOCTORS copy."""
        text = format_sql_results(
            [
                {
                    "handler": "search_doctors",
                    "found": False,
                    "rows": [],
                    "summary": "No matching doctors found.",
                }
            ]
        )
        self.assertIn("I couldn't find matching doctors for that", text)
