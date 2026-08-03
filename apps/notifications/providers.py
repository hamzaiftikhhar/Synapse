"""Notification providers — pluggable email / SMS backends."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


class EmailProvider(ABC):
    @abstractmethod
    def send(self, *, to: str, subject: str, body: str, html_body: str | None = None) -> None:
        ...


class ConsoleEmailProvider(EmailProvider):
    def send(self, *, to: str, subject: str, body: str, html_body: str | None = None) -> None:
        logger.info("EMAIL to=%s subject=%s\n%s", to, subject, body)
        print(f"\n=== EMAIL to={to} ===\nSubject: {subject}\n\n{body}\n=== END EMAIL ===\n")


class SMTPEmailProvider(EmailProvider):
    def send(self, *, to: str, subject: str, body: str, html_body: str | None = None) -> None:
        send_mail(
            subject=subject,
            message=body,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@synapse.local"),
            recipient_list=[to],
            html_message=html_body or None,
            fail_silently=False,
        )


class SMSProvider(ABC):
    @abstractmethod
    def send(self, *, to: str, body: str) -> str | None:
        ...


class ConsoleSMSProvider(SMSProvider):
    def send(self, *, to: str, body: str) -> str | None:
        logger.info("SMS to=%s body=%s", to, body)
        print(f"\n=== SMS to={to} ===\n{body}\n=== END SMS ===\n")
        return "console"


class TwilioSMSProvider(SMSProvider):
    def send(self, *, to: str, body: str) -> str | None:
        from apps.chatbot.integrations.twilio_sms import send_sms

        return send_sms(to=to, body=body)


def get_email_provider() -> EmailProvider:
    backend = getattr(settings, "EMAIL_BACKEND", "")
    if "console" in backend or getattr(settings, "DEBUG", False):
        # Prefer console when Django console backend is set
        if "console" in backend:
            return ConsoleEmailProvider()
    if getattr(settings, "EMAIL_HOST", None):
        return SMTPEmailProvider()
    return ConsoleEmailProvider()


def get_sms_provider() -> SMSProvider:
    from apps.chatbot.integrations.twilio_sms import is_configured

    if is_configured():
        return TwilioSMSProvider()
    return ConsoleSMSProvider()
