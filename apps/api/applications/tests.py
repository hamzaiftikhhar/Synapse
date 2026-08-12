"""POST /applications — public clinic application intake."""

from __future__ import annotations

from django.test import TestCase

from apps.billing.models import Plan
from apps.clinics.models import ClinicApplication, ClinicApplicationStatus

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
