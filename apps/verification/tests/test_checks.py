"""The system check that makes OTP_PROVIDER=twilio fail at startup/config
time (python manage.py check, runserver, migrate, ...) rather than silently
degrading every verification request to FAILED when credentials are missing
or incomplete."""

from __future__ import annotations

from django.test import TestCase, override_settings

from apps.verification.checks import check_twilio_verify_configured

_FULL_CONFIG = dict(
    OTP_PROVIDER="twilio",
    TWILIO_ACCOUNT_SID="ACtest",
    TWILIO_API_KEY="SKtest",
    TWILIO_API_SECRET="secrettest",
    TWILIO_VERIFY_SERVICE_SID="VAtest",
)


class TwilioConfigCheckTests(TestCase):
    def test_mock_provider_never_triggers_the_check(self):
        with override_settings(
            OTP_PROVIDER="mock",
            TWILIO_ACCOUNT_SID="",
            TWILIO_API_KEY="",
            TWILIO_API_SECRET="",
            TWILIO_VERIFY_SERVICE_SID="",
        ):
            self.assertEqual(check_twilio_verify_configured(None), [])

    def test_twilio_provider_fully_configured_passes(self):
        with override_settings(**_FULL_CONFIG):
            self.assertEqual(check_twilio_verify_configured(None), [])

    def test_twilio_provider_with_all_settings_missing_fails(self):
        with override_settings(
            OTP_PROVIDER="twilio",
            TWILIO_ACCOUNT_SID="",
            TWILIO_API_KEY="",
            TWILIO_API_SECRET="",
            TWILIO_VERIFY_SERVICE_SID="",
        ):
            errors = check_twilio_verify_configured(None)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].id, "verification.E001")
        for name in (
            "TWILIO_ACCOUNT_SID",
            "TWILIO_API_KEY",
            "TWILIO_API_SECRET",
            "TWILIO_VERIFY_SERVICE_SID",
        ):
            self.assertIn(name, errors[0].msg)

    def test_twilio_provider_with_one_setting_missing_still_fails(self):
        config = dict(_FULL_CONFIG, TWILIO_VERIFY_SERVICE_SID="")
        with override_settings(**config):
            errors = check_twilio_verify_configured(None)
        self.assertEqual(len(errors), 1)
        self.assertIn("TWILIO_VERIFY_SERVICE_SID", errors[0].msg)
        self.assertNotIn("TWILIO_ACCOUNT_SID,", errors[0].msg)
