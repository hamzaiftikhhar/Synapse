"""Email templating layer: every billing template renders valid HTML with
a sane derived plain-text fallback, and NotificationService's billing
methods route through send_email exactly once with both parts populated."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from apps.notifications.providers import (
    ResendEmailProvider,
    _RESEND_USER_AGENT,
    get_email_provider,
)
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

# name -> context with every key the template needs, per the corresponding
# NotificationService.send_*_email method's actual call.
_NON_BILLING_TEMPLATES = {
    "patient_otp": {"code": "482913", "clinic_name": "Apex Dental"},
    "staff_verify": {"name": "Ali", "link": "https://x.test/verify-email?token=abc"},
    "password_reset": {"link": "https://x.test/reset-password?token=abc"},
    "clinic_invite": {
        "name": "Ali",
        "clinic_name": "Apex Dental",
        "link": "https://x.test/accept-invite?token=abc",
    },
    "application_received": {"clinic_name": "Apex Dental"},
    "demo_request_received": {"clinic_name": "Apex Dental"},
    "demo_request_notification": {
        "label": "New application",
        "clinic_name": "Apex Dental",
        "requester_name": "Ali",
        "work_email": "ali@apex.test",
        "phone": "+15551234567",
        "link": "https://x.test/dashboard/platform/applications",
    },
}


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

    def test_every_non_billing_template_renders_with_its_dynamic_value(self):
        # Each template must actually surface the one value that makes the
        # email useful — "renders without error" alone wouldn't catch a
        # template that silently dropped it. The HTML must always carry it.
        # The derived *text* fallback is a different story for link-based
        # templates: strip_tags() drops the <a>'s href along with the tag,
        # so a link's URL never survives into text — only its visible label
        # does (same limitation the existing billing CTA test already only
        # checks html_body for, never the derived text, for this reason).
        expected_html_needle = {
            "patient_otp": "482913",
            "staff_verify": "token=abc",
            "password_reset": "token=abc",
            "clinic_invite": "token=abc",
            "application_received": "Apex Dental",
            "demo_request_received": "Apex Dental",
            "demo_request_notification": "ali@apex.test",
        }
        expected_text_needle = {
            "patient_otp": "482913",
            "staff_verify": "Ali",
            "clinic_invite": "Ali",
            "application_received": "Apex Dental",
            "demo_request_received": "Apex Dental",
            "demo_request_notification": "ali@apex.test",
        }
        for name, context in _NON_BILLING_TEMPLATES.items():
            with self.subTest(template=name):
                html, text = render_email(name, context)
                self.assertIn("<html", html)
                self.assertIn(expected_html_needle[name], html)
                if name in expected_text_needle:
                    self.assertIn(expected_text_needle[name], text)
                self.assertNotIn("<", text)
                self.assertTrue(text.strip())


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


@override_settings(FRONTEND_URL="https://app.synapse.test", PLATFORM_NOTIFICATION_EMAIL="team@synapse.test")
class NotificationServiceTemplatedEmailTests(SimpleTestCase):
    """The 7 email types that were plain-text-only before this phase — each
    must now route through send_email with both html_body and body
    populated, exactly like the billing methods already do, and every
    caller's public signature/kwargs must be unchanged."""

    def test_patient_otp_email(self):
        with patch.object(NotificationService, "send_email") as mock_send:
            NotificationService.send_patient_otp_email(
                to="patient@test.com", code="482913", clinic_name="Apex Dental"
            )
        kwargs = mock_send.call_args.kwargs
        self.assertIn("<html", kwargs["html_body"])
        self.assertIn("482913", kwargs["html_body"])
        self.assertIn("482913", kwargs["body"])
        self.assertNotIn("<", kwargs["body"])

    def test_staff_verify_email(self):
        with patch.object(NotificationService, "send_email") as mock_send:
            NotificationService.send_staff_verify_email(to="ali@test.com", token="tok123", first_name="Ali")
        kwargs = mock_send.call_args.kwargs
        self.assertIn("<html", kwargs["html_body"])
        self.assertIn("https://app.synapse.test/verify-email?token=tok123", kwargs["html_body"])
        self.assertIn("Ali", kwargs["html_body"])

    def test_password_reset_email(self):
        with patch.object(NotificationService, "send_email") as mock_send:
            NotificationService.send_password_reset_email(to="ali@test.com", token="tok123")
        kwargs = mock_send.call_args.kwargs
        self.assertIn("https://app.synapse.test/reset-password?token=tok123", kwargs["html_body"])

    def test_clinic_owner_invite_email(self):
        with patch.object(NotificationService, "send_email") as mock_send:
            NotificationService.send_clinic_owner_invite_email(
                to="owner@test.com", token="tok123", clinic_name="Apex Dental", first_name="Ali"
            )
        kwargs = mock_send.call_args.kwargs
        self.assertIn("https://app.synapse.test/accept-invite?token=tok123", kwargs["html_body"])
        self.assertIn("Apex Dental", kwargs["html_body"])

    def test_application_received_email(self):
        with patch.object(NotificationService, "send_email") as mock_send:
            NotificationService.send_application_received_email(to="ali@test.com", clinic_name="Apex Dental")
        kwargs = mock_send.call_args.kwargs
        self.assertIn("<html", kwargs["html_body"])
        self.assertIn("Apex Dental", kwargs["html_body"])

    def test_demo_request_received_email(self):
        with patch.object(NotificationService, "send_email") as mock_send:
            NotificationService.send_demo_request_received_email(to="ali@test.com", clinic_name="Apex Dental")
        kwargs = mock_send.call_args.kwargs
        self.assertIn("<html", kwargs["html_body"])
        self.assertIn("Apex Dental", kwargs["html_body"])

    def test_demo_request_notification_email(self):
        with patch.object(NotificationService, "send_email") as mock_send:
            NotificationService.send_demo_request_notification_email(
                application_id="app-1",
                clinic_name="Apex Dental",
                requester_name="Ali",
                work_email="ali@apex.test",
                phone="+15551234567",
                source="demo_request",
            )
        kwargs = mock_send.call_args.kwargs
        self.assertEqual(kwargs["to"], "team@synapse.test")
        self.assertIn("ali@apex.test", kwargs["html_body"])
        self.assertIn("Demo request", kwargs["subject"])

    def test_demo_request_notification_still_skips_when_recipient_unset(self):
        # Same guard as before this phase — must survive the templating
        # change unchanged.
        with override_settings(PLATFORM_NOTIFICATION_EMAIL=""):
            with patch.object(NotificationService, "send_email") as mock_send:
                NotificationService.send_demo_request_notification_email(
                    application_id="app-1",
                    clinic_name="Apex Dental",
                    requester_name="Ali",
                    work_email="ali@apex.test",
                    phone="",
                    source="get_started",
                )
        mock_send.assert_not_called()


class ResendEmailProviderTests(SimpleTestCase):
    @override_settings(RESEND_API_KEY="re_test_key", DEFAULT_FROM_EMAIL="Synapse <onboarding@resend.dev>")
    def test_send_posts_expected_request_shape(self):
        fake_response = MagicMock()
        fake_response.read.return_value = b'{"id": "abc"}'
        fake_response.__enter__.return_value = fake_response
        with patch("apps.notifications.providers.urllib.request.urlopen", return_value=fake_response) as mock_open:
            ResendEmailProvider().send(
                to="patient@test.com", subject="Hi", body="plain", html_body="<p>hi</p>"
            )
        request = mock_open.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.resend.com/emails")
        self.assertEqual(request.get_header("Authorization"), "Bearer re_test_key")
        self.assertEqual(request.get_header("User-agent"), _RESEND_USER_AGENT)
        payload = json.loads(request.data)
        self.assertEqual(payload["to"], ["patient@test.com"])
        self.assertEqual(payload["from"], "Synapse <onboarding@resend.dev>")
        self.assertEqual(payload["html"], "<p>hi</p>")
        self.assertEqual(payload["text"], "plain")

    @override_settings(RESEND_API_KEY="re_test_key", DEFAULT_FROM_EMAIL="Synapse <onboarding@resend.dev>")
    def test_send_does_not_use_python_urllib_user_agent(self):
        """Resend's Cloudflare 403s `Python-urllib/*` (error 1010). A live
        send on 2026-08-21 failed through this provider until a custom UA
        was set; the same POST with User-Agent: Synapse/1.0 returned 200.
        urllib injects `Python-urllib/3.x` when this header is missing, so
        the header must be present *and* not that default."""
        fake_response = MagicMock()
        fake_response.read.return_value = b'{"id": "abc"}'
        fake_response.__enter__.return_value = fake_response
        with patch("apps.notifications.providers.urllib.request.urlopen", return_value=fake_response) as mock_open:
            ResendEmailProvider().send(
                to="delivered@resend.dev", subject="Hi", body="plain"
            )
        ua = mock_open.call_args.args[0].get_header("User-agent") or ""
        self.assertTrue(ua, "User-Agent must be set so urllib does not inject Python-urllib")
        self.assertFalse(
            ua.startswith("Python-urllib"),
            f"Resend Cloudflare 1010-bans the urllib default; got {ua!r}",
        )

    @override_settings(RESEND_API_KEY="re_test_key", DEFAULT_FROM_EMAIL="Synapse <onboarding@resend.dev>")
    def test_successful_send_prints_to_console(self):
        """Resend used to succeed silently; ConsoleEmailProvider was the only
        backend that dumped to= / subject / body. A live switch to Resend
        made outbound mail invisible in the runserver terminal."""
        fake_response = MagicMock()
        fake_response.read.return_value = b'{"id": "abc"}'
        fake_response.__enter__.return_value = fake_response
        with patch("apps.notifications.providers.urllib.request.urlopen", return_value=fake_response):
            with patch("apps.notifications.providers.print") as mock_print:
                ResendEmailProvider().send(
                    to="patient@test.com",
                    subject="Verify your email",
                    body="Click this link to verify.",
                )
        mock_print.assert_called()
        dump = mock_print.call_args.args[0]
        self.assertIn("resend", dump)
        self.assertIn("patient@test.com", dump)
        self.assertIn("Verify your email", dump)
        self.assertIn("Click this link to verify.", dump)

    @override_settings(RESEND_API_KEY="re_test_key")
    def test_failed_send_does_not_print_success_dump(self):
        import urllib.error

        with patch(
            "apps.notifications.providers.urllib.request.urlopen",
            side_effect=urllib.error.HTTPError(
                "https://api.resend.com/emails", 422, "Unprocessable", {}, None
            ),
        ):
            with patch("apps.notifications.providers.print") as mock_print:
                with self.assertRaises(RuntimeError):
                    ResendEmailProvider().send(to="x@test.com", subject="Hi", body="plain")
        mock_print.assert_not_called()

    @override_settings(RESEND_API_KEY="")
    def test_send_without_api_key_raises(self):
        with self.assertRaises(RuntimeError):
            ResendEmailProvider().send(to="x@test.com", subject="Hi", body="plain")

    @override_settings(RESEND_API_KEY="re_test_key")
    def test_non_2xx_response_raises_not_swallowed(self):
        import urllib.error

        with patch(
            "apps.notifications.providers.urllib.request.urlopen",
            side_effect=urllib.error.HTTPError(
                "https://api.resend.com/emails", 422, "Unprocessable", {}, None
            ),
        ):
            with self.assertRaises(RuntimeError):
                ResendEmailProvider().send(to="x@test.com", subject="Hi", body="plain")


class GetEmailProviderTests(SimpleTestCase):
    """`manage.py test` loads the same .env as the dev server, so
    RESEND_API_KEY is present during real test runs too — get_email_provider
    deliberately never selects Resend under `manage.py test` (see
    _running_management_test_command), which the "outside a test run"
    cases below patch around to test the selection logic in isolation.
    test_resend_is_never_selected_under_the_real_test_runner exercises the
    actual, unpatched guard — the thing that matters in practice."""

    @override_settings(RESEND_API_KEY="re_test_key", DEBUG=False)
    def test_resend_wins_when_configured_regardless_of_debug(self):
        with patch("apps.notifications.providers._running_management_test_command", return_value=False):
            self.assertIsInstance(get_email_provider(), ResendEmailProvider)

    @override_settings(RESEND_API_KEY="re_test_key", DEBUG=True)
    def test_resend_wins_over_debug_console_fallback(self):
        # Configuring the key is meant to be enough on its own — DEBUG=True
        # in local dev must not silently mask a real, working provider.
        with patch("apps.notifications.providers._running_management_test_command", return_value=False):
            self.assertIsInstance(get_email_provider(), ResendEmailProvider)

    @override_settings(RESEND_API_KEY="", DEBUG=True)
    def test_falls_back_to_console_when_unset(self):
        from apps.notifications.providers import ConsoleEmailProvider

        self.assertIsInstance(get_email_provider(), ConsoleEmailProvider)

    @override_settings(RESEND_API_KEY="re_test_key", DEBUG=False)
    def test_resend_is_never_selected_under_the_real_test_runner(self):
        # No patching here — this is the actual guard as every other test
        # in this suite (and every other app's tests) really sees it.
        from apps.notifications.providers import ConsoleEmailProvider

        self.assertIsInstance(get_email_provider(), ConsoleEmailProvider)
