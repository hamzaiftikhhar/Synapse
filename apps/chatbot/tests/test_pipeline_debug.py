"""Chat pipeline traces must print on runserver and stay silent under tests."""

from __future__ import annotations

from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from apps.chatbot.pipeline_debug import pipeline_debug_enabled


class PipelineDebugEnabledTests(SimpleTestCase):
    @override_settings(DEBUG_CHAT_PIPELINE=True)
    def test_disabled_under_the_real_test_runner(self):
        # Unpatched argv — this file is loaded by `manage.py test`, which is
        # the command that must never dump a full chat trace per case.
        self.assertFalse(pipeline_debug_enabled())

    @override_settings(DEBUG_CHAT_PIPELINE=True)
    def test_enabled_on_runserver(self):
        with patch("apps.chatbot.pipeline_debug.sys.argv", ["manage.py", "runserver"]):
            self.assertTrue(pipeline_debug_enabled())

    @override_settings(DEBUG_CHAT_PIPELINE=True)
    def test_disabled_under_eval_even_when_setting_is_on(self):
        with patch("apps.chatbot.pipeline_debug.sys.argv", ["manage.py", "run_chat_eval"]):
            self.assertFalse(pipeline_debug_enabled())

    @override_settings(DEBUG_CHAT_PIPELINE=False)
    def test_respects_explicit_off(self):
        with patch("apps.chatbot.pipeline_debug.sys.argv", ["manage.py", "runserver"]):
            self.assertFalse(pipeline_debug_enabled())
