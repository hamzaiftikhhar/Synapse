"""TwilioVerifyProvider against a mocked Twilio client — no real HTTP calls,
matching the project's trial-account constraint (Verify SMS can't be relied
on for real testing locally). Every test configures the client's return
value or raises TwilioRestException; the assertions are on how this provider
translates that into our own VerificationOutcome vocabulary."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings
from twilio.base.exceptions import TwilioRestException

from apps.verification.outcomes import VerificationStatus
from apps.verification.providers.twilio_verify import TwilioVerifyProvider

_CONFIGURED = dict(
    TWILIO_ACCOUNT_SID="ACtest",
    TWILIO_API_KEY="SKtest",
    TWILIO_API_SECRET="secrettest",
    TWILIO_VERIFY_SERVICE_SID="VAtest",
)


def _fake_client(verifications_return=None, verifications_raise=None, checks_return=None, checks_raise=None):
    client = MagicMock()
    service = client.verify.v2.services.return_value
    if verifications_raise is not None:
        service.verifications.create.side_effect = verifications_raise
    else:
        service.verifications.create.return_value = verifications_return
    if checks_raise is not None:
        service.verification_checks.create.side_effect = checks_raise
    else:
        service.verification_checks.create.return_value = checks_return
    return client


@override_settings(**_CONFIGURED)
class TwilioVerifyProviderTests(TestCase):
    def setUp(self):
        self.provider = TwilioVerifyProvider()

    def test_not_configured_returns_failed_without_raising(self):
        with override_settings(TWILIO_VERIFY_SERVICE_SID=""):
            outcome = TwilioVerifyProvider().send_verification(to="+14155552671", channel="sms")
        self.assertEqual(outcome.status, VerificationStatus.FAILED)

    def test_send_maps_pending_status_and_carries_sid(self):
        fake = _fake_client(
            verifications_return=SimpleNamespace(status="pending", sid="VE123")
        )
        with patch.object(TwilioVerifyProvider, "_client", return_value=fake):
            outcome = self.provider.send_verification(to="+14155552671", channel="sms")
        self.assertEqual(outcome.status, VerificationStatus.PENDING)
        self.assertEqual(outcome.provider, "twilio")
        self.assertEqual(outcome.provider_ref, "VE123")
        self.assertIsNone(outcome.dev_code)  # Twilio never exposes a plaintext code

    def test_send_api_error_is_translated_to_failed_not_raised(self):
        fake = _fake_client(
            verifications_raise=TwilioRestException(500, "uri", msg="boom", code=20500)
        )
        with patch.object(TwilioVerifyProvider, "_client", return_value=fake):
            outcome = self.provider.send_verification(to="+14155552671", channel="sms")
        self.assertEqual(outcome.status, VerificationStatus.FAILED)

    def test_check_approved_maps_to_approved_and_valid(self):
        fake = _fake_client(checks_return=SimpleNamespace(status="approved", sid="VE123"))
        with patch.object(TwilioVerifyProvider, "_client", return_value=fake):
            outcome = self.provider.check_verification(to="+14155552671", code="123456")
        self.assertEqual(outcome.status, VerificationStatus.APPROVED)
        self.assertTrue(outcome.valid)

    def test_check_wrong_code_stays_pending_not_valid(self):
        fake = _fake_client(checks_return=SimpleNamespace(status="pending", sid="VE123"))
        with patch.object(TwilioVerifyProvider, "_client", return_value=fake):
            outcome = self.provider.check_verification(to="+14155552671", code="000000")
        self.assertEqual(outcome.status, VerificationStatus.PENDING)
        self.assertFalse(outcome.valid)

    def test_check_max_attempts_reached(self):
        fake = _fake_client(
            checks_return=SimpleNamespace(status="max_attempts_reached", sid="VE123")
        )
        with patch.object(TwilioVerifyProvider, "_client", return_value=fake):
            outcome = self.provider.check_verification(to="+14155552671", code="000000")
        self.assertEqual(outcome.status, VerificationStatus.MAX_ATTEMPTS_REACHED)

    def test_check_404_is_not_found_not_failed(self):
        fake = _fake_client(
            checks_raise=TwilioRestException(404, "uri", msg="not found", code=20404)
        )
        with patch.object(TwilioVerifyProvider, "_client", return_value=fake):
            outcome = self.provider.check_verification(to="+14155552671", code="123456")
        self.assertEqual(outcome.status, VerificationStatus.NOT_FOUND)

    def test_check_other_api_error_is_failed(self):
        fake = _fake_client(
            checks_raise=TwilioRestException(500, "uri", msg="boom", code=20500)
        )
        with patch.object(TwilioVerifyProvider, "_client", return_value=fake):
            outcome = self.provider.check_verification(to="+14155552671", code="123456")
        self.assertEqual(outcome.status, VerificationStatus.FAILED)

    def test_unrecognized_status_never_defaults_to_approved(self):
        fake = _fake_client(checks_return=SimpleNamespace(status="some_future_status", sid="VE1"))
        with patch.object(TwilioVerifyProvider, "_client", return_value=fake):
            outcome = self.provider.check_verification(to="+14155552671", code="123456")
        self.assertEqual(outcome.status, VerificationStatus.FAILED)
        self.assertFalse(outcome.valid)

    def test_resend_delegates_to_send_verification(self):
        fake = _fake_client(verifications_return=SimpleNamespace(status="pending", sid="VE9"))
        with patch.object(TwilioVerifyProvider, "_client", return_value=fake):
            outcome = self.provider.resend_verification(to="+14155552671", channel="sms")
        self.assertEqual(outcome.status, VerificationStatus.PENDING)
        fake.verify.v2.services.return_value.verifications.create.assert_called_once()

    def test_invalid_recipient_never_reaches_the_client(self):
        fake = _fake_client()
        with patch.object(TwilioVerifyProvider, "_client", return_value=fake):
            outcome = self.provider.send_verification(to="not-a-number", channel="sms")
        self.assertEqual(outcome.status, VerificationStatus.INVALID_RECIPIENT)
        fake.verify.v2.services.assert_not_called()

    def test_never_logs_api_secret_on_failure(self):
        fake = _fake_client(
            verifications_raise=TwilioRestException(
                401, "uri", msg=f"Authenticate using {_CONFIGURED['TWILIO_API_SECRET']}", code=20003
            )
        )
        with patch.object(TwilioVerifyProvider, "_client", return_value=fake):
            with self.assertLogs("apps.verification.providers.twilio_verify", level="WARNING") as captured:
                self.provider.send_verification(to="+14155552671", channel="sms")
        joined = " ".join(captured.output)
        self.assertNotIn(_CONFIGURED["TWILIO_API_SECRET"], joined)
