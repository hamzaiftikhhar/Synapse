"""Twilio Verify — the official Verify lifecycle, not a hand-rolled OTP store.

Deliberately thin: no local state, no re-implementation of expiry/attempt
tracking (the Verify Service already enforces those, configured on the Twilio
side). This provider's only job is translating Twilio's status vocabulary
into ours and keeping every Twilio-specific detail — client construction,
exception types, the Verify Service SID — inside this one module.

Uses API Key + Secret (`TWILIO_API_KEY`/`TWILIO_API_SECRET`), not the main
Account Auth Token — Twilio's recommended production credential shape, and
what this project's own local secrets are already provisioned as. Separate
from `TWILIO_AUTH_TOKEN`/`TWILIO_FROM_NUMBER`, which belong to the existing,
untouched raw-SMS sender in `apps.chatbot.integrations.twilio_sms`.
"""

from __future__ import annotations

import logging

from django.conf import settings

from apps.verification.outcomes import (
    RecipientNormalizationError,
    VerificationOutcome,
    VerificationStatus,
    normalize_recipient,
)
from apps.verification.providers.base import OTPProvider

logger = logging.getLogger(__name__)

_STATUS_MAP = {
    "pending": VerificationStatus.PENDING,
    "approved": VerificationStatus.APPROVED,
    "canceled": VerificationStatus.CANCELED,
    "max_attempts_reached": VerificationStatus.MAX_ATTEMPTS_REACHED,
    "expired": VerificationStatus.EXPIRED,
    "failed": VerificationStatus.FAILED,
    # Twilio deletes the verification SID on approval, expiry, or max
    # attempts alike — by the time it's gone there is no way to tell these
    # apart from here, so this is reported as NOT_FOUND rather than guessing.
    "deleted": VerificationStatus.NOT_FOUND,
}


def _map_status(raw: str | None) -> VerificationStatus:
    # An unrecognized status must never resolve to APPROVED — silently
    # defaulting toward "verified" is the one direction that can't be undone.
    return _STATUS_MAP.get((raw or "").lower(), VerificationStatus.FAILED)


class TwilioVerifyProvider(OTPProvider):
    name = "twilio"

    def is_configured(self) -> bool:
        return bool(
            settings.TWILIO_ACCOUNT_SID
            and settings.TWILIO_API_KEY
            and settings.TWILIO_API_SECRET
            and settings.TWILIO_VERIFY_SERVICE_SID
        )

    def _client(self):
        from twilio.rest import Client

        return Client(
            settings.TWILIO_API_KEY,
            settings.TWILIO_API_SECRET,
            settings.TWILIO_ACCOUNT_SID,
        )

    def _service(self):
        return self._client().verify.v2.services(settings.TWILIO_VERIFY_SERVICE_SID)

    def send_verification(self, *, to: str, channel: str = "sms") -> VerificationOutcome:
        try:
            normalized = normalize_recipient(to, channel)
        except RecipientNormalizationError as exc:
            return self._invalid_recipient(to, channel, exc)

        if not self.is_configured():
            logger.error("TwilioVerifyProvider used without full configuration")
            return self._failed(normalized, channel, "Verification is not configured.")

        from twilio.base.exceptions import TwilioRestException

        try:
            verification = self._service().verifications.create(
                to=normalized, channel=channel
            )
        except TwilioRestException as exc:
            # Log Twilio's error code only — never the recipient's code, our
            # API secret, or the raw exception (which can echo request params).
            logger.warning("twilio verify send failed code=%s", exc.code)
            return self._failed(normalized, channel, "We couldn't send a verification code right now.")

        return VerificationOutcome(
            status=_map_status(verification.status),
            to=normalized,
            channel=channel,
            provider=self.name,
            provider_ref=verification.sid or "",
            message="Verification code sent.",
        )

    def resend_verification(self, *, to: str, channel: str = "sms") -> VerificationOutcome:
        # Twilio Verify has no separate resend endpoint — the documented
        # mechanism is calling Create Verification again for the same `to`.
        # Cooldown/rate limiting is enforced by the Verify Service's own
        # configuration, not application code.
        return self.send_verification(to=to, channel=channel)

    def check_verification(self, *, to: str, code: str) -> VerificationOutcome:
        channel = "email" if "@" in (to or "") else "sms"
        try:
            normalized = normalize_recipient(to, channel)
        except RecipientNormalizationError as exc:
            return self._invalid_recipient(to, "", exc)

        if not self.is_configured():
            logger.error("TwilioVerifyProvider used without full configuration")
            return self._failed(normalized, "", "We couldn't verify that code right now.")

        from twilio.base.exceptions import TwilioRestException

        try:
            check = self._service().verification_checks.create(to=normalized, code=code)
        except TwilioRestException as exc:
            if exc.status == 404:
                return VerificationOutcome(
                    status=VerificationStatus.NOT_FOUND,
                    to=normalized,
                    channel="",
                    provider=self.name,
                    message="No pending verification found. Request a new code.",
                )
            logger.warning("twilio verify check failed code=%s", exc.code)
            return self._failed(normalized, "", "We couldn't verify that code right now.")

        status = _map_status(check.status)
        return VerificationOutcome(
            status=status,
            to=normalized,
            channel="",
            provider=self.name,
            provider_ref=check.sid or "",
            valid=status is VerificationStatus.APPROVED,
            message="Verified." if status is VerificationStatus.APPROVED else "Incorrect or expired code.",
        )

    def _failed(self, to: str, channel: str, message: str) -> VerificationOutcome:
        return VerificationOutcome(
            status=VerificationStatus.FAILED,
            to=to,
            channel=channel,
            provider=self.name,
            message=message,
        )

    def _invalid_recipient(
        self, to: str, channel: str, exc: RecipientNormalizationError
    ) -> VerificationOutcome:
        return VerificationOutcome(
            status=VerificationStatus.INVALID_RECIPIENT,
            to=to,
            channel=channel,
            provider=self.name,
            message=str(exc),
        )
