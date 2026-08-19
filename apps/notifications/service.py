"""NotificationService — single entry for email / SMS outbound messages."""

from __future__ import annotations

import logging
from typing import Any

from django.conf import settings

from apps.notifications.providers import get_email_provider, get_sms_provider
from apps.notifications.templating import render_email

logger = logging.getLogger(__name__)


class NotificationService:
    @staticmethod
    def send_email(*, to: str, subject: str, body: str, html_body: str | None = None) -> None:
        provider = get_email_provider()
        provider.send(to=to, subject=subject, body=body, html_body=html_body)

    @classmethod
    def send_templated_email(
        cls, *, to: str, subject: str, template: str, context: dict
    ) -> None:
        """Render `templates/emails/{template}.html` for both parts and send
        through the same provider path as every other email — the HTML
        layer is additive, not a second delivery mechanism."""
        html_body, body = render_email(template, context)
        cls.send_email(to=to, subject=subject, body=body, html_body=html_body)

    # ── Billing lifecycle (apps.billing.services.webhook_processor) ──────

    @classmethod
    def _billing_context(cls, *, clinic_name: str) -> dict:
        base = getattr(settings, "FRONTEND_URL", "http://localhost:3000").rstrip("/")
        return {"clinic_name": clinic_name, "cta_url": f"{base}/dashboard/billing"}

    @classmethod
    def send_payment_successful_email(cls, *, to: str, clinic_name: str, plan_name: str = "") -> None:
        cls.send_templated_email(
            to=to,
            subject="Payment successful",
            template="billing/payment_successful",
            context={**cls._billing_context(clinic_name=clinic_name), "plan_name": plan_name},
        )

    @classmethod
    def send_payment_failed_email(cls, *, to: str, clinic_name: str) -> None:
        cls.send_templated_email(
            to=to,
            subject="We couldn't process your payment",
            template="billing/payment_failed",
            context=cls._billing_context(clinic_name=clinic_name),
        )

    @classmethod
    def send_payment_past_due_email(cls, *, to: str, clinic_name: str) -> None:
        cls.send_templated_email(
            to=to,
            subject="Your payment is past due",
            template="billing/payment_past_due",
            context=cls._billing_context(clinic_name=clinic_name),
        )

    @classmethod
    def send_payment_recovered_email(cls, *, to: str, clinic_name: str) -> None:
        cls.send_templated_email(
            to=to,
            subject="Payment recovered — you're all set",
            template="billing/payment_recovered",
            context=cls._billing_context(clinic_name=clinic_name),
        )

    @classmethod
    def send_subscription_paused_email(cls, *, to: str, clinic_name: str) -> None:
        cls.send_templated_email(
            to=to,
            subject="Your subscription is paused",
            template="billing/subscription_paused",
            context=cls._billing_context(clinic_name=clinic_name),
        )

    @classmethod
    def send_subscription_canceled_email(cls, *, to: str, clinic_name: str) -> None:
        cls.send_templated_email(
            to=to,
            subject="Your subscription has been canceled",
            template="billing/subscription_canceled",
            context=cls._billing_context(clinic_name=clinic_name),
        )

    @classmethod
    def send_account_reactivated_email(cls, *, to: str, clinic_name: str) -> None:
        cls.send_templated_email(
            to=to,
            subject="Welcome back — your subscription is active",
            template="billing/account_reactivated",
            context=cls._billing_context(clinic_name=clinic_name),
        )

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
    def send_clinic_owner_invite_email(
        cls, *, to: str, token: str, clinic_name: str, first_name: str = ""
    ) -> None:
        base = getattr(settings, "FRONTEND_URL", "http://localhost:3000").rstrip("/")
        link = f"{base}/accept-invite?token={token}"
        name = first_name or "there"
        cls.send_email(
            to=to,
            subject=f"Your Synapse workspace for {clinic_name} is ready",
            body=(
                f"Hi {name},\n\n"
                f"Your Synapse clinic workspace for {clinic_name} is ready. "
                f"Set up your account to get started:\n\n{link}\n\n"
                f"This link expires in 7 days and can only be used once.\n"
            ),
        )

    @classmethod
    def send_application_received_email(cls, *, to: str, clinic_name: str) -> None:
        cls.send_email(
            to=to,
            subject="We received your Synapse application",
            body=(
                f"Thanks for applying for Synapse on behalf of {clinic_name}.\n\n"
                f"Our team will review your details and reach out shortly to "
                f"prepare your workspace.\n"
            ),
        )

    @classmethod
    def send_demo_request_received_email(cls, *, to: str, clinic_name: str) -> None:
        """Lighter-weight confirmation for the marketing site's "Book a
        Demo" form — the visitor hasn't chosen a plan or applied for
        anything yet, so this doesn't use "application" language."""
        cls.send_email(
            to=to,
            subject="We received your demo request",
            body=(
                f"Thanks for your interest in Synapse for {clinic_name}.\n\n"
                f"Our team will reach out shortly to schedule your demo.\n"
            ),
        )

    @classmethod
    def send_demo_request_notification_email(
        cls,
        *,
        application_id: str,
        clinic_name: str,
        requester_name: str,
        work_email: str,
        phone: str,
        source: str,
    ) -> None:
        """Internal notification to the platform team — distinct from the
        applicant-facing confirmations above. Silently skipped if no
        internal recipient is configured, matching this codebase's pattern
        for optional integrations (e.g. Twilio/Paddle unset in local dev)."""
        recipient = getattr(settings, "PLATFORM_NOTIFICATION_EMAIL", "")
        if not recipient:
            logger.info(
                "PLATFORM_NOTIFICATION_EMAIL not set — skipping internal "
                "notification for application %s",
                application_id,
            )
            return
        base = getattr(settings, "FRONTEND_URL", "http://localhost:3000").rstrip("/")
        link = f"{base}/dashboard/platform/applications"
        label = "Demo request" if source == "demo_request" else "New application"
        cls.send_email(
            to=recipient,
            subject=f"{label}: {clinic_name}",
            body=(
                f"{label}\n\n"
                f"Company: {clinic_name}\n"
                f"Name: {requester_name}\n"
                f"Email: {work_email}\n"
                f"Phone: {phone or '—'}\n\n"
                f"Open in Super Admin: {link}\n"
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
