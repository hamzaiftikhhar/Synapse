"""Simulates a real OTP backend, statefully, without ever calling one.

Every property a real backend has is modeled: codes are random (never a
hardcoded value like 123456), hashed at rest, expire, have a bounded number
of check attempts, and enforce a resend cooldown. The plaintext code is only
ever exposed via `VerificationOutcome.dev_code`, and only when
`settings.DEBUG` is True — this is the one deliberate difference from
`TwilioVerifyProvider`, which never has a plaintext code to expose at all.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from apps.verification.models import MockVerificationRecord
from apps.verification.outcomes import (
    RecipientNormalizationError,
    VerificationOutcome,
    VerificationStatus,
    normalize_recipient,
)
from apps.verification.providers.base import OTPProvider

logger = logging.getLogger(__name__)


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _generate_code() -> str:
    length = getattr(settings, "VERIFICATION_CODE_LENGTH", 6)
    return str(secrets.randbelow(10**length)).zfill(length)


class MockOTPProvider(OTPProvider):
    name = "mock"

    def send_verification(self, *, to: str, channel: str = "sms") -> VerificationOutcome:
        try:
            normalized = normalize_recipient(to, channel)
        except RecipientNormalizationError as exc:
            return self._invalid_recipient(to, channel, exc)
        return self._issue_or_refresh(normalized, channel)

    def resend_verification(self, *, to: str, channel: str = "sms") -> VerificationOutcome:
        try:
            normalized = normalize_recipient(to, channel)
        except RecipientNormalizationError as exc:
            return self._invalid_recipient(to, channel, exc)
        return self._issue_or_refresh(normalized, channel)

    def check_verification(self, *, to: str, code: str) -> VerificationOutcome:
        # `check` intentionally does not raise on a bad recipient the way
        # send/resend do — an unparseable `to` here just means "no record",
        # which is already a defined, honest outcome (NOT_FOUND).
        try:
            normalized = normalize_recipient(to, channel="sms" if "@" not in to else "email")
        except RecipientNormalizationError:
            normalized = (to or "").strip().lower()

        record = (
            MockVerificationRecord.objects.filter(to=normalized)
            .order_by("-created_at")
            .first()
        )
        if record is None:
            return VerificationOutcome(
                status=VerificationStatus.NOT_FOUND,
                to=normalized,
                channel="",
                provider=self.name,
                message="No pending verification found. Request a new code.",
            )

        channel = record.channel
        now = timezone.now()

        if record.verified_at is not None:
            return VerificationOutcome(
                status=VerificationStatus.ALREADY_VERIFIED,
                to=normalized,
                channel=channel,
                provider=self.name,
                provider_ref=str(record.id),
                valid=True,
                message="This contact is already verified.",
            )

        if record.expires_at <= now:
            return VerificationOutcome(
                status=VerificationStatus.EXPIRED,
                to=normalized,
                channel=channel,
                provider=self.name,
                provider_ref=str(record.id),
                message="This code has expired. Request a new one.",
            )

        if record.attempts >= record.max_attempts:
            return VerificationOutcome(
                status=VerificationStatus.MAX_ATTEMPTS_REACHED,
                to=normalized,
                channel=channel,
                provider=self.name,
                provider_ref=str(record.id),
                message="Too many incorrect attempts. Request a new code.",
            )

        if record.code_hash != _hash_code(code or ""):
            record.attempts += 1
            record.save(update_fields=["attempts"])
            if record.attempts >= record.max_attempts:
                return VerificationOutcome(
                    status=VerificationStatus.MAX_ATTEMPTS_REACHED,
                    to=normalized,
                    channel=channel,
                    provider=self.name,
                    provider_ref=str(record.id),
                    message="Too many incorrect attempts. Request a new code.",
                )
            return VerificationOutcome(
                status=VerificationStatus.PENDING,
                to=normalized,
                channel=channel,
                provider=self.name,
                provider_ref=str(record.id),
                message="Incorrect code. Please try again.",
            )

        record.verified_at = now
        record.save(update_fields=["verified_at"])
        return VerificationOutcome(
            status=VerificationStatus.APPROVED,
            to=normalized,
            channel=channel,
            provider=self.name,
            provider_ref=str(record.id),
            valid=True,
            message="Verified.",
        )

    def _issue_or_refresh(self, to: str, channel: str) -> VerificationOutcome:
        now = timezone.now()
        cooldown = timedelta(
            seconds=getattr(settings, "VERIFICATION_RESEND_COOLDOWN_SECONDS", 30)
        )
        ttl = timedelta(seconds=getattr(settings, "VERIFICATION_CODE_TTL_SECONDS", 600))
        max_attempts = getattr(settings, "VERIFICATION_MAX_CHECK_ATTEMPTS", 5)

        pending = (
            MockVerificationRecord.objects.filter(
                to=to, channel=channel, verified_at__isnull=True
            )
            .order_by("-created_at")
            .first()
        )
        if pending is not None and pending.expires_at > now:
            cooldown_until = pending.last_sent_at + cooldown
            if now < cooldown_until:
                wait_seconds = int((cooldown_until - now).total_seconds())
                return VerificationOutcome(
                    status=VerificationStatus.PENDING,
                    to=to,
                    channel=channel,
                    provider=self.name,
                    provider_ref=str(pending.id),
                    message=f"A code was already sent. Please wait {wait_seconds}s before requesting another.",
                )

        code = _generate_code()
        code_hash = _hash_code(code)
        expires_at = now + ttl

        if pending is not None and pending.expires_at > now:
            pending.code_hash = code_hash
            pending.expires_at = expires_at
            pending.attempts = 0
            pending.last_sent_at = now
            pending.max_attempts = max_attempts
            pending.save(
                update_fields=[
                    "code_hash",
                    "expires_at",
                    "attempts",
                    "last_sent_at",
                    "max_attempts",
                ]
            )
            record = pending
        else:
            record = MockVerificationRecord.objects.create(
                to=to,
                channel=channel,
                code_hash=code_hash,
                max_attempts=max_attempts,
                expires_at=expires_at,
                last_sent_at=now,
            )

        # Never log the code itself — only that one was issued.
        logger.info("mock verification code issued to=%s channel=%s", to, channel)

        return VerificationOutcome(
            status=VerificationStatus.PENDING,
            to=to,
            channel=channel,
            provider=self.name,
            provider_ref=str(record.id),
            message="Verification code sent.",
            dev_code=code if settings.DEBUG else None,
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
