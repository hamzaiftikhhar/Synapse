"""POST /applications — public clinic application intake."""

from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase, override_settings

from apps.billing.models import Plan
from apps.clinics.models import ClinicApplication, ClinicApplicationSource, ClinicApplicationStatus

URL = "/api/v1/applications"


class ApplicationSubmissionTests(TestCase):
    def setUp(self):
        Plan.objects.create(slug="starter", name="Starter", is_active=True)
        Plan.objects.create(slug="growth", name="Growth", is_active=True)
        Plan.objects.create(slug="retired", name="Retired Plan", is_active=False)

    def _payload(self, **overrides):
        data = dict(
            clinic_name="Beula Medical Family Clinic",
            owner_name="Ali Hamza",
            work_email="ali@beula.example.com",
            phone="+15550001111",
            website="https://beula.example.com",
            num_doctors=3,
            current_scheduling_system="Spreadsheet",
            plan_slug="growth",
            notes="Interested in launching next month.",
        )
        data.update(overrides)
        return data

    def test_submission_creates_pending_application_with_plan(self):
        resp = self.client.post(URL, data=self._payload(), content_type="application/json")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["status"], "pending")
        app = ClinicApplication.objects.get(id=body["id"])
        self.assertEqual(app.plan_slug, "growth")
        self.assertEqual(app.status, ClinicApplicationStatus.PENDING)
        self.assertEqual(app.work_email, "ali@beula.example.com")

    def test_resubmission_from_same_email_updates_pending_application(self):
        self.client.post(URL, data=self._payload(), content_type="application/json")
        self.assertEqual(ClinicApplication.objects.count(), 1)

        self.client.post(
            URL, data=self._payload(clinic_name="Beula Medical — updated", plan_slug="starter"),
            content_type="application/json",
        )
        self.assertEqual(ClinicApplication.objects.count(), 1)
        app = ClinicApplication.objects.get()
        self.assertEqual(app.clinic_name, "Beula Medical — updated")
        self.assertEqual(app.plan_slug, "starter")

    def test_missing_clinic_name_rejected(self):
        resp = self.client.post(
            URL, data=self._payload(clinic_name=""), content_type="application/json"
        )
        self.assertEqual(resp.status_code, 400)

    def test_invalid_email_rejected(self):
        resp = self.client.post(
            URL, data=self._payload(work_email="not-an-email"), content_type="application/json"
        )
        self.assertEqual(resp.status_code, 400)

    def test_inactive_plan_rejected(self):
        resp = self.client.post(
            URL, data=self._payload(plan_slug="retired"), content_type="application/json"
        )
        self.assertEqual(resp.status_code, 400)

    def test_unknown_plan_rejected(self):
        resp = self.client.post(
            URL, data=self._payload(plan_slug="does-not-exist"), content_type="application/json"
        )
        self.assertEqual(resp.status_code, 400)

    def test_source_defaults_to_get_started(self):
        resp = self.client.post(URL, data=self._payload(), content_type="application/json")
        app = ClinicApplication.objects.get(id=resp.json()["id"])
        self.assertEqual(app.source, ClinicApplicationSource.GET_STARTED)

    def test_unrecognized_source_falls_back_to_get_started_not_rejected(self):
        resp = self.client.post(
            URL, data=self._payload(source="totally-made-up"), content_type="application/json"
        )
        self.assertEqual(resp.status_code, 200)
        app = ClinicApplication.objects.get(id=resp.json()["id"])
        self.assertEqual(app.source, ClinicApplicationSource.GET_STARTED)


class DemoRequestSubmissionTests(TestCase):
    """The marketing site's "Book a Demo" form — same model, same review
    queue as Get Started, but no plan is chosen at submission time."""

    def _payload(self, **overrides):
        data = dict(
            clinic_name="Riverside Dental",
            owner_name="Sam Rivera",
            work_email="sam@riverside.example.com",
            phone="+15550009999",
            notes="Interested in the AI chatbot for booking.",
            source="demo_request",
        )
        data.update(overrides)
        return data

    def test_demo_request_needs_no_plan(self):
        resp = self.client.post(URL, data=self._payload(), content_type="application/json")
        self.assertEqual(resp.status_code, 200)
        app = ClinicApplication.objects.get(id=resp.json()["id"])
        self.assertEqual(app.source, ClinicApplicationSource.DEMO_REQUEST)
        self.assertEqual(app.plan_slug, "")
        self.assertEqual(app.status, ClinicApplicationStatus.PENDING)

    def test_plan_slug_is_ignored_and_cleared_for_a_demo_request(self):
        """Even if a stray plan_slug is sent, a demo request never actually
        commits the visitor to a plan — approval still requires one."""
        resp = self.client.post(
            URL, data=self._payload(plan_slug="starter"), content_type="application/json"
        )
        app = ClinicApplication.objects.get(id=resp.json()["id"])
        self.assertEqual(app.plan_slug, "")

    def test_demo_request_sends_lighter_confirmation_email_not_application_copy(self):
        with patch(
            "apps.notifications.service.NotificationService.send_email"
        ) as mock_send:
            self.client.post(URL, data=self._payload(), content_type="application/json")
        applicant_calls = [c for c in mock_send.call_args_list if c.kwargs["to"] == self._payload()["work_email"]]
        self.assertEqual(len(applicant_calls), 1)
        self.assertIn("demo request", applicant_calls[0].kwargs["subject"].lower())

    @override_settings(PLATFORM_NOTIFICATION_EMAIL="team@synapse.example.com")
    def test_internal_notification_sent_when_recipient_configured(self):
        with patch(
            "apps.notifications.service.NotificationService.send_email"
        ) as mock_send:
            self.client.post(URL, data=self._payload(), content_type="application/json")
        internal_calls = [
            c for c in mock_send.call_args_list if c.kwargs["to"] == "team@synapse.example.com"
        ]
        self.assertEqual(len(internal_calls), 1)
        body = internal_calls[0].kwargs["body"]
        self.assertIn("Riverside Dental", body)
        self.assertIn("sam@riverside.example.com", body)
        self.assertIn("/dashboard/platform/applications", body)

    def test_no_internal_notification_sent_when_recipient_unconfigured(self):
        """PLATFORM_NOTIFICATION_EMAIL unset in settings/base.py by default
        — this must degrade silently, not raise, matching every other
        optional integration in this codebase (Twilio/Paddle unset in dev)."""
        with patch(
            "apps.notifications.service.NotificationService.send_email"
        ) as mock_send:
            resp = self.client.post(URL, data=self._payload(), content_type="application/json")
        self.assertEqual(resp.status_code, 200)
        # Only the applicant-facing confirmation, no internal one.
        self.assertEqual(mock_send.call_count, 1)

    def test_resubmission_does_not_resend_internal_notification(self):
        with override_settings(PLATFORM_NOTIFICATION_EMAIL="team@synapse.example.com"):
            with patch(
                "apps.notifications.service.NotificationService.send_email"
            ) as mock_send:
                self.client.post(URL, data=self._payload(), content_type="application/json")
                self.client.post(
                    URL, data=self._payload(notes="updated notes"),
                    content_type="application/json",
                )
        internal_calls = [
            c for c in mock_send.call_args_list if c.kwargs["to"] == "team@synapse.example.com"
        ]
        self.assertEqual(len(internal_calls), 1)
