"""Twilio SMS delivery — send only; verification logic lives in otp_service."""

from __future__ import annotations

import logging

from django.conf import settings

logger = logging.getLogger(__name__)


class TwilioNotConfiguredError(RuntimeError):
    """Twilio env vars are missing."""


class TwilioSendError(RuntimeError):
    """Twilio API call failed."""


def is_configured() -> bool:
    return bool(
        settings.TWILIO_ACCOUNT_SID
        and settings.TWILIO_AUTH_TOKEN
        and settings.TWILIO_FROM_NUMBER
    )


def send_sms(*, to: str, body: str) -> str | None:
    """
    Send an SMS via Twilio.

    Returns Twilio message SID on success.
    Raises TwilioNotConfiguredError if credentials are unset.
    """
    if not is_configured():
        raise TwilioNotConfiguredError("Twilio is not configured")

    try:
        from twilio.rest import Client
    except ImportError as exc:
        raise TwilioSendError(
            "twilio package not installed — add to requirements"
        ) from exc

    client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
    try:
        message = client.messages.create(
            body=body,
            from_=settings.TWILIO_FROM_NUMBER,
            to=to,
        )
    except Exception as exc:
        logger.exception("Twilio SMS failed to %s", to)
        raise TwilioSendError(str(exc)) from exc

    return message.sid
