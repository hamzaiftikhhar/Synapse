"""NotificationService — single entry for email / SMS outbound messages."""

from __future__ import annotations

import logging
from typing import Any

from django.conf import settings

from apps.notifications.providers import get_email_provider, get_sms_provider

logger = logging.getLogger(__name__)


class NotificationService:
    @staticmethod
    def send_email(*, to: str, subject: str, body: str, html_body: str | None = None) -> None:
        provider = get_email_provider()
        provider.send(to=to, subject=subject, body=body, html_body=html_body)

    @staticmethod
    def send_sms(*, to: str, body: str) -> str | None:
        provider = get_sms_provider()
        return provider.send(to=to, body=body)

    @classmethod
    def send_staff_verify_email(cls, *, to: str, token: str, first_name: str = "") -> None:
        base = getattr(settings, "FRONTEND_URL", "http://localhost:3000").rstrip("/")
        link = f"{base}/verify-email?token={token}"
        name = first_name or "there"
        cls.send_email(
            to=to,
            subject="Verify your Synapse email",
            body=(
                f"Hi {name},\n\n"
                f"Verify your email to continue setting up Synapse:\n\n{link}\n\n"
                f"This link expires in 24 hours.\n"
            ),
        )

    @classmethod
    def send_password_reset_email(cls, *, to: str, token: str) -> None:
        base = getattr(settings, "FRONTEND_URL", "http://localhost:3000").rstrip("/")
        link = f"{base}/reset-password?token={token}"
        cls.send_email(
            to=to,
            subject="Reset your Synapse password",
            body=(
                f"Reset your password using this link:\n\n{link}\n\n"
                f"If you did not request this, you can ignore this email.\n"
                f"This link expires in 2 hours.\n"
            ),
        )

    @classmethod
    def send_patient_otp_email(cls, *, to: str, code: str, clinic_name: str = "the clinic") -> None:
        cls.send_email(
            to=to,
            subject=f"Your verification code for {clinic_name}",
            body=f"Your Synapse verification code is {code}\n\nIt expires shortly.\n",
        )

    @classmethod
    def send_patient_otp_sms(cls, *, to: str, code: str) -> str | None | Any:
        return cls.send_sms(to=to, body=f"Your Synapse verification code is {code}")
