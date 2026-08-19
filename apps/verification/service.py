"""The one entry point application code should call.

Auth, booking, and any other sensitive-action flow depend only on this —
never on `MockOTPProvider`/`TwilioVerifyProvider` directly, and never on
`settings.OTP_PROVIDER`. Swapping providers is a config change, not a
code change.
"""

from __future__ import annotations

from apps.verification.outcomes import (
    RecipientNormalizationError,
    VerificationOutcome,
    VerificationStatus,
    normalize_recipient,
)
from apps.verification.providers import OTPProvider, get_provider


class VerificationService:
    def __init__(self, provider: OTPProvider | None = None) -> None:
        self._provider = provider or get_provider()

    def send_verification(self, *, to: str, channel: str = "sms") -> VerificationOutcome:
        invalid = self._reject_invalid_recipient(to, channel)
        if invalid is not None:
            return invalid
        return self._provider.send_verification(to=to, channel=channel)

    def resend_verification(self, *, to: str, channel: str = "sms") -> VerificationOutcome:
        invalid = self._reject_invalid_recipient(to, channel)
        if invalid is not None:
            return invalid
        return self._provider.resend_verification(to=to, channel=channel)

    def check_verification(self, *, to: str, code: str) -> VerificationOutcome:
        if not (code or "").strip():
            return VerificationOutcome(
                status=VerificationStatus.INVALID_RECIPIENT,
                to=to,
                channel="",
                provider=self._provider.name,
                message="A code is required.",
            )
        return self._provider.check_verification(to=to, code=code)

    def _reject_invalid_recipient(self, to: str, channel: str) -> VerificationOutcome | None:
        try:
            normalize_recipient(to, channel)
        except RecipientNormalizationError as exc:
            return VerificationOutcome(
                status=VerificationStatus.INVALID_RECIPIENT,
                to=to,
                channel=channel,
                provider=self._provider.name,
                message=str(exc),
            )
        return None
