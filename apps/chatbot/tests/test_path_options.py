"""Minimal path step payload — three options only."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.chatbot.booking.modes import PATH_OPTIONS
from apps.chatbot.booking.serializers import _path_options
from apps.chatbot.booking.state import BookingSession


class PathOptionsTests(SimpleTestCase):
    def test_path_options_three_choices_no_hero(self):
        session = BookingSession.create(clinic_id="c1", mode="general", reason="")
        clinic = SimpleNamespace(id="c1")
        with patch(
            "apps.chatbot.booking.serializers.get_booking_config",
            return_value={"hero_horizon_days": 3},
        ):
            opts = _path_options(clinic, session, {"hero_horizon_days": 3})
        self.assertEqual(len(opts["paths"]), 3)
        self.assertNotIn("hero", opts)
        self.assertNotIn("suggested", opts)
        self.assertNotIn("subtitle", opts)
        self.assertEqual(opts["title"], "How would you like to book?")

    def test_path_options_titles_are_short(self):
        titles = {p["id"]: p["title"] for p in PATH_OPTIONS}
        self.assertEqual(titles["first_available"], "First available")
        self.assertEqual(titles["help_choose"], "Choose specialty")
        self.assertEqual(titles["know_doctor"], "I know my doctor")
        for p in PATH_OPTIONS:
            self.assertNotIn("description", p)
            self.assertNotIn("emoji", p)
