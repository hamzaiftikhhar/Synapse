"""MockOTPProvider's full lifecycle — this is the provider development and
CI actually exercise, so its behavior matrix needs to be complete."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.verification.models import MockVerificationRecord
from apps.verification.outcomes import VerificationStatus
from apps.verification.providers.mock import MockOTPProvider


@override_settings(
    DEBUG=True,
    VERIFICATION_CODE_LENGTH=6,
    VERIFICATION_CODE_TTL_SECONDS=600,
    VERIFICATION_RESEND_COOLDOWN_SECONDS=30,
    VERIFICATION_MAX_CHECK_ATTEMPTS=3,
)
class MockOTPProviderTests(TestCase):
    def setUp(self):
        self.provider = MockOTPProvider()

    def test_send_returns_pending_with_dev_code_when_debug(self):
        outcome = self.provider.send_verification(to="+14155552671", channel="sms")
        self.assertEqual(outcome.status, VerificationStatus.PENDING)
        self.assertEqual(outcome.provider, "mock")
        self.assertIsNotNone(outcome.dev_code)
        self.assertEqual(len(outcome.dev_code), 6)
        self.assertTrue(outcome.dev_code.isdigit())

    @override_settings(DEBUG=False)
    def test_dev_code_hidden_when_debug_false(self):
        outcome = self.provider.send_verification(to="+14155552671", channel="sms")
        self.assertIsNone(outcome.dev_code)

    def test_dev_code_is_never_a_fixed_universal_value(self):
        codes = set()
        for _ in range(5):
            outcome = self.provider.send_verification(
                to=f"+1415555{2670 + len(codes):04d}", channel="sms"
            )
            codes.add(outcome.dev_code)
        # Randomness isn't provable in 5 draws, but a fixed 123456-style
        # constant would collapse this set to size 1 — that's what we guard.
        self.assertGreater(len(codes), 1)

    def test_correct_code_approves(self):
        sent = self.provider.send_verification(to="+14155552671", channel="sms")
        result = self.provider.check_verification(to="+14155552671", code=sent.dev_code)
        self.assertEqual(result.status, VerificationStatus.APPROVED)
        self.assertTrue(result.valid)

    def test_wrong_code_stays_pending_with_attempts_remaining(self):
        self.provider.send_verification(to="+14155552671", channel="sms")
        result = self.provider.check_verification(to="+14155552671", code="000000")
        self.assertEqual(result.status, VerificationStatus.PENDING)
        self.assertFalse(result.valid)

    def test_wrong_code_repeated_reaches_max_attempts(self):
        self.provider.send_verification(to="+14155552671", channel="sms")
        for _ in range(3):
            result = self.provider.check_verification(to="+14155552671", code="000000")
        self.assertEqual(result.status, VerificationStatus.MAX_ATTEMPTS_REACHED)

    def test_correct_code_after_max_attempts_still_rejected(self):
        sent = self.provider.send_verification(to="+14155552671", channel="sms")
        for _ in range(3):
            self.provider.check_verification(to="+14155552671", code="000000")
        result = self.provider.check_verification(to="+14155552671", code=sent.dev_code)
        self.assertEqual(result.status, VerificationStatus.MAX_ATTEMPTS_REACHED)
        self.assertFalse(result.valid)

    def test_expired_code_is_reported_as_expired_not_invalid(self):
        sent = self.provider.send_verification(to="+14155552671", channel="sms")
        record = MockVerificationRecord.objects.get(id=sent.provider_ref)
        record.expires_at = timezone.now() - timedelta(seconds=1)
        record.save(update_fields=["expires_at"])
        result = self.provider.check_verification(to="+14155552671", code=sent.dev_code)
        self.assertEqual(result.status, VerificationStatus.EXPIRED)

    def test_already_verified_is_reported_distinctly_and_still_valid(self):
        sent = self.provider.send_verification(to="+14155552671", channel="sms")
        first = self.provider.check_verification(to="+14155552671", code=sent.dev_code)
        self.assertEqual(first.status, VerificationStatus.APPROVED)
        second = self.provider.check_verification(to="+14155552671", code=sent.dev_code)
        self.assertEqual(second.status, VerificationStatus.ALREADY_VERIFIED)
        self.assertTrue(second.valid)

    def test_check_with_no_prior_send_is_not_found(self):
        result = self.provider.check_verification(to="+19995550000", code="123456")
        self.assertEqual(result.status, VerificationStatus.NOT_FOUND)

    def test_resend_within_cooldown_is_rejected(self):
        self.provider.send_verification(to="+14155552671", channel="sms")
        result = self.provider.resend_verification(to="+14155552671", channel="sms")
        self.assertEqual(result.status, VerificationStatus.PENDING)
        self.assertIn("wait", result.message.lower())
        self.assertIsNone(result.dev_code)

    def test_resend_after_cooldown_issues_a_new_code_and_resets_attempts(self):
        first = self.provider.send_verification(to="+14155552671", channel="sms")
        self.provider.check_verification(to="+14155552671", code="000000")  # burn one attempt

        record = MockVerificationRecord.objects.get(id=first.provider_ref)
        record.last_sent_at = timezone.now() - timedelta(seconds=31)
        record.save(update_fields=["last_sent_at"])

        second = self.provider.resend_verification(to="+14155552671", channel="sms")
        self.assertEqual(second.status, VerificationStatus.PENDING)
        self.assertIsNotNone(second.dev_code)
        self.assertNotEqual(second.dev_code, first.dev_code)

        record.refresh_from_db()
        self.assertEqual(record.attempts, 0)

        # The old code must no longer work — resend issued a new one.
        stale = self.provider.check_verification(to="+14155552671", code=first.dev_code)
        self.assertEqual(stale.status, VerificationStatus.PENDING)
        self.assertFalse(stale.valid)

    def test_invalid_recipient_is_rejected_before_any_record_is_created(self):
        outcome = self.provider.send_verification(to="not-a-phone-number", channel="sms")
        self.assertEqual(outcome.status, VerificationStatus.INVALID_RECIPIENT)
        self.assertEqual(MockVerificationRecord.objects.count(), 0)

    def test_email_channel_lifecycle(self):
        sent = self.provider.send_verification(to="Patient@Example.com", channel="email")
        self.assertEqual(sent.status, VerificationStatus.PENDING)
        self.assertEqual(sent.to, "patient@example.com")
        result = self.provider.check_verification(to="patient@example.com", code=sent.dev_code)
        self.assertEqual(result.status, VerificationStatus.APPROVED)

    def test_code_is_hashed_at_rest_never_stored_plaintext(self):
        sent = self.provider.send_verification(to="+14155552671", channel="sms")
        record = MockVerificationRecord.objects.get(id=sent.provider_ref)
        self.assertNotEqual(record.code_hash, sent.dev_code)
        self.assertEqual(len(record.code_hash), 64)  # sha256 hex digest

    def test_send_never_logs_the_plaintext_code(self):
        with self.assertLogs("apps.verification.providers.mock", level="INFO") as captured:
            outcome = self.provider.send_verification(to="+14155552671", channel="sms")
        joined = " ".join(captured.output)
        self.assertNotIn(outcome.dev_code, joined)
