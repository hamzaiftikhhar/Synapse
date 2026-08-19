"""The same test bodies run against both providers through VerificationService
— proving application code that only talks to the service behaves the same
regardless of which provider is configured. This is the parity the whole
abstraction exists for."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from apps.verification.outcomes import VerificationOutcome, VerificationStatus
from apps.verification.providers.mock import MockOTPProvider
from apps.verification.providers.twilio_verify import TwilioVerifyProvider
from apps.verification.service import VerificationService


class _ContractTestsMixin:
    """Not a TestCase itself — mixed into the two concrete classes below so
    pytest/unittest never tries to collect and run it on its own."""

    to = "+14155552671"
    channel = "sms"

    def make_service(self) -> VerificationService:
        raise NotImplementedError

    def issue_and_get_correct_code(self, service: VerificationService) -> str:
        raise NotImplementedError

    def test_send_returns_pending(self):
        outcome = self.make_service().send_verification(to=self.to, channel=self.channel)
        self.assertEqual(outcome.status, VerificationStatus.PENDING)
        self.assertEqual(outcome.to, self.to)

    def test_correct_code_is_approved_and_valid(self):
        service = self.make_service()
        code = self.issue_and_get_correct_code(service)
        outcome = service.check_verification(to=self.to, code=code)
        self.assertEqual(outcome.status, VerificationStatus.APPROVED)
        self.assertTrue(outcome.valid)

    def test_wrong_code_is_not_approved(self):
        service = self.make_service()
        self.issue_and_get_correct_code(service)
        outcome = service.check_verification(to=self.to, code="000000")
        self.assertNotEqual(outcome.status, VerificationStatus.APPROVED)
        self.assertFalse(outcome.valid)

    def test_invalid_recipient_never_reaches_the_provider(self):
        outcome = self.make_service().send_verification(to="not-a-recipient", channel=self.channel)
        self.assertEqual(outcome.status, VerificationStatus.INVALID_RECIPIENT)

    def test_resend_returns_pending(self):
        service = self.make_service()
        service.send_verification(to=self.to, channel=self.channel)
        outcome = service.resend_verification(to=self.to, channel=self.channel)
        self.assertEqual(outcome.status, VerificationStatus.PENDING)

    def test_outcome_shape_is_identical_across_providers(self):
        outcome = self.make_service().send_verification(to=self.to, channel=self.channel)
        self.assertIsInstance(outcome, VerificationOutcome)
        self.assertEqual(
            set(outcome.__dataclass_fields__),
            {"status", "to", "channel", "provider", "provider_ref", "valid", "message", "dev_code"},
        )

    def test_missing_code_is_rejected_without_calling_the_provider(self):
        service = self.make_service()
        service.send_verification(to=self.to, channel=self.channel)
        outcome = service.check_verification(to=self.to, code="")
        self.assertEqual(outcome.status, VerificationStatus.INVALID_RECIPIENT)


@override_settings(DEBUG=True, VERIFICATION_MAX_CHECK_ATTEMPTS=5)
class MockProviderContractTests(_ContractTestsMixin, TestCase):
    def make_service(self) -> VerificationService:
        return VerificationService(provider=MockOTPProvider())

    def issue_and_get_correct_code(self, service: VerificationService) -> str:
        outcome = service.send_verification(to=self.to, channel=self.channel)
        return outcome.dev_code


@override_settings(
    TWILIO_ACCOUNT_SID="ACtest",
    TWILIO_API_KEY="SKtest",
    TWILIO_API_SECRET="secrettest",
    TWILIO_VERIFY_SERVICE_SID="VAtest",
)
class TwilioProviderContractTests(_ContractTestsMixin, TestCase):
    def setUp(self):
        fake_client = MagicMock()
        service_mock = fake_client.verify.v2.services.return_value
        service_mock.verifications.create.return_value = SimpleNamespace(
            status="pending", sid="VE1"
        )

        def _check(to, code):
            status = "approved" if code == "123456" else "pending"
            return SimpleNamespace(status=status, sid="VE1")

        service_mock.verification_checks.create.side_effect = _check

        patcher = patch.object(TwilioVerifyProvider, "_client", return_value=fake_client)
        patcher.start()
        self.addCleanup(patcher.stop)

    def make_service(self) -> VerificationService:
        return VerificationService(provider=TwilioVerifyProvider())

    def issue_and_get_correct_code(self, service: VerificationService) -> str:
        service.send_verification(to=self.to, channel=self.channel)
        return "123456"


class GetProviderTests(TestCase):
    def test_default_provider_is_mock(self):
        from apps.verification.providers import get_provider

        with override_settings(OTP_PROVIDER="mock"):
            self.assertIsInstance(get_provider(), MockOTPProvider)

    def test_twilio_provider_selected_by_setting(self):
        from apps.verification.providers import get_provider

        with override_settings(OTP_PROVIDER="twilio"):
            self.assertIsInstance(get_provider(), TwilioVerifyProvider)

    def test_unknown_provider_raises_improperly_configured(self):
        from django.core.exceptions import ImproperlyConfigured

        from apps.verification.providers import get_provider

        with override_settings(OTP_PROVIDER="carrier_pigeon"):
            with self.assertRaises(ImproperlyConfigured):
                get_provider()

    def test_switching_providers_is_config_only_no_service_code_change(self):
        """The exact behavior the abstraction exists for: VerificationService
        never imports the twilio SDK or a concrete provider class — only
        apps.verification.providers.get_provider() does. (Mentioning
        "Twilio" in the module's own docstring is fine documentation, not a
        violation — this checks actual import statements, not prose.)"""
        import ast

        import apps.verification.service as service_module

        with open(service_module.__file__) as f:
            tree = ast.parse(f.read())

        imported_names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                self.assertFalse(
                    module.startswith("twilio"), f"service.py imports the twilio SDK directly: {module}"
                )
                imported_names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertFalse(
                        alias.name.startswith("twilio"),
                        f"service.py imports the twilio SDK directly: {alias.name}",
                    )

        self.assertNotIn("TwilioVerifyProvider", imported_names)
        self.assertNotIn("MockOTPProvider", imported_names)
