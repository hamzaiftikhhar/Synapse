"""Notification providers — pluggable email / SMS backends."""

from __future__ import annotations

import html
import json
import logging
import sys
import urllib.error
import urllib.request
from abc import ABC, abstractmethod

from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)

_RESEND_URL = "https://api.resend.com/emails"


def _log_email_sent(*, provider: str, to: str, subject: str, body: str) -> None:
    """Always dump outbound mail to the runserver console.

    ConsoleEmailProvider used to be the only backend that printed, so
    switching to Resend made successful sends silently disappear from
    the terminal even though they hit the API.
    """
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "")
    logger.info("EMAIL provider=%s from=%s to=%s subject=%s", provider, from_email, to, subject)
    print(
        f"\n=== EMAIL ({provider}) ===\n"
        f"From: {from_email}\n"
        f"To: {to}\n"
        f"Subject: {subject}\n\n"
        f"{body}\n"
        f"=== END EMAIL ===\n",
        flush=True,
    )


# urllib's default User-Agent is `Python-urllib/3.x`. Resend's Cloudflare
# returns 403 "error code: 1010" for that signature (reproduced 2026-08-21:
# GET /domains with a custom UA succeeded; the same POST without one failed).
_RESEND_USER_AGENT = "Synapse/1.0"


class EmailProvider(ABC):
    @abstractmethod
    def send(self, *, to: str, subject: str, body: str, html_body: str | None = None) -> None:
        ...


class ConsoleEmailProvider(EmailProvider):
    def send(self, *, to: str, subject: str, body: str, html_body: str | None = None) -> None:
        _log_email_sent(provider="console", to=to, subject=subject, body=body)


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
        _log_email_sent(provider="smtp", to=to, subject=subject, body=body)


class ResendEmailProvider(EmailProvider):
    """Resend REST API — raw HTTP, no SDK dependency (same choice as
    GeminiNLUProvider: the API is a single POST, not worth a new pip
    dependency for)."""

    def send(self, *, to: str, subject: str, body: str, html_body: str | None = None) -> None:
        api_key = getattr(settings, "RESEND_API_KEY", "")
        if not api_key:
            raise RuntimeError("RESEND_API_KEY is not configured")

        payload = {
            "from": getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@synapse.local"),
            "to": [to],
            "subject": subject,
            "html": html_body or f"<pre style='font-family:inherit'>{html.escape(body)}</pre>",
            "text": body,
        }
        request = urllib.request.Request(
            _RESEND_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "User-Agent": _RESEND_USER_AGENT,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            logger.error("Resend send failed HTTP %s to=%s: %s", exc.code, to, detail[:500])
            raise RuntimeError(f"Resend API error {exc.code}: {detail[:300]}") from exc
        except urllib.error.URLError as exc:
            logger.error("Resend send failed to=%s: %s", to, exc)
            raise RuntimeError(f"Resend request failed: {exc}") from exc
        _log_email_sent(provider="resend", to=to, subject=subject, body=body)


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


def _running_management_test_command() -> bool:
    # Same reasoning and same argv[1] check as
    # apps.knowledge.apps.should_warm_up_embeddings — `manage.py test` loads
    # the same .env as the dev server (no separate test settings module in
    # this repo), so RESEND_API_KEY is present there too. Many existing
    # tests exercise real invite/notification code paths without mocking
    # NotificationService.send_email, relying on the old always-safe
    # console default — a real provider must never be reachable from an
    # automated test run.
    return len(sys.argv) > 1 and sys.argv[1] == "test"


def get_email_provider() -> EmailProvider:
    # Same precedence style as get_sms_provider() below: a configured real
    # provider wins regardless of DEBUG, so setting the key is enough to
    # make every email in the app start sending for real — no other flag
    # to flip.
    if getattr(settings, "RESEND_API_KEY", "") and not _running_management_test_command():
        return ResendEmailProvider()
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
