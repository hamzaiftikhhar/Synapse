"""Email templating layer: every billing template renders valid HTML with
a sane derived plain-text fallback, and NotificationService's billing
methods route through send_email exactly once with both parts populated."""

from __future__ import annotations

from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from apps.notifications.service import NotificationService
from apps.notifications.templating import render_email

_BILLING_TEMPLATES = [
    "billing/payment_successful",
    "billing/payment_failed",
    "billing/payment_past_due",
    "billing/payment_recovered",
    "billing/subscription_paused",
    "billing/subscription_canceled",
]


class RenderEmailTests(SimpleTestCase):
    def test_every_billing_template_renders_valid_html_and_text(self):
        for name in _BILLING_TEMPLATES:
            with self.subTest(template=name):
                html, text = render_email(
                    name, {"clinic_name": "Apex Dental", "plan_name": "Growth", "cta_url": "https://x.test/billing"}
                )
                self.assertIn("<html", html)
                self.assertIn("Apex Dental", html)
                self.assertIn("Apex Dental", text)
                # The derived text must not contain raw HTML tags.
                self.assertNotIn("<", text)
                self.assertTrue(text.strip())

    def test_cta_button_omitted_when_no_cta_url(self):
        # The base layout's own footer legitimately has a mailto link, so
        # this checks for the CTA button specifically (its distinct
        # background-color styling), not "any anchor tag in the email".
        html, _ = render_email(
            "billing/payment_failed", {"clinic_name": "Apex Dental", "cta_url": ""}
        )
        self.assertNotIn("background-color:#5b21b6", html)

        html_with_cta, _ = render_email(
            "billing/payment_failed",
            {"clinic_name": "Apex Dental", "cta_url": "https://x.test", "cta_label": "Go"},
        )
        self.assertIn("background-color:#5b21b6", html_with_cta)

    def test_missing_context_key_does_not_crash(self):
        # Django templates render an unresolved variable as empty string by
        # default rather than raising — confirms no template assumes every
        # key is always supplied.
        html, text = render_email("billing/payment_successful", {"clinic_name": "Apex Dental"})
        self.assertIn("<html", html)


@override_settings(FRONTEND_URL="https://app.synapse.test")
class NotificationServiceBillingEmailTests(SimpleTestCase):
    def test_payment_successful_sends_through_send_email_once(self):
        with patch.object(NotificationService, "send_email") as mock_send:
            NotificationService.send_payment_successful_email(
                to="owner@clinic.test", clinic_name="Apex Dental", plan_name="Growth"
            )
        mock_send.assert_called_once()
        kwargs = mock_send.call_args.kwargs
        self.assertEqual(kwargs["to"], "owner@clinic.test")
        self.assertIn("<html", kwargs["html_body"])
        self.assertIn("Apex Dental", kwargs["body"])
        self.assertNotIn("<", kwargs["body"])

    def test_cta_url_is_derived_from_frontend_url_setting(self):
        with patch.object(NotificationService, "send_email") as mock_send:
            NotificationService.send_payment_failed_email(to="x@test.com", clinic_name="X")
        self.assertIn("https://app.synapse.test/dashboard/billing", mock_send.call_args.kwargs["html_body"])
