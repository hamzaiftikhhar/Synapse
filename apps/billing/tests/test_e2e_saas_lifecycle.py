"""End-to-end journey test for the SaaS lifecycle built across SaaS-Phases
1-7: demo request -> Super Admin approval -> invite -> activation ->
onboarding -> knowledge-base upload -> phone verification -> billing
lifecycle (activation, payment, past_due/grace period, recovery,
cancellation/suspension).

Deliberately does not extend into a real patient booking flow — that is a
separate, pre-existing, already-stable subsystem (see ROADMAP.md's
chatbot-pipeline phases) with its own extensive test coverage; re-deriving
it here would test something this initiative didn't touch, not something
it did. Onboarding prerequisites (doctor/service/hours/availability) are
created directly rather than through their own CRUD endpoints — those are
themselves separately, pre-existing well-tested; what this test verifies is
that `_compute_onboarding_status()` and `complete_onboarding()` correctly
read live state regardless of how it got there, which is the actual
contract this journey depends on.

One TestCase, one long test method, told in chronological order — the
value of an E2E test is in the story it tells, not in fragmenting it into
unrelated-looking pieces.
"""

from __future__ import annotations

import json
from datetime import time as time_
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import AuditAction, AuditLog, StaffAuthToken, StaffAuthTokenPurpose
from apps.billing.models import AccessStatus, Plan, Subscription, SubscriptionStatus
from apps.billing.tests.test_webhooks import _sign
from apps.clinics.models import Clinic, ClinicApplicationStatus, ClinicStatus, ClinicType
from apps.doctors.models import Doctor, DoctorSchedule
from apps.services.models import Service
from apps.clinics.models import ClinicBusinessHours

APPLICATIONS_URL = "/api/v1/applications"
WEBHOOK_URL = "/api/v1/billing/paddle/webhook"
WEBHOOK_SECRET = "e2e-test-webhook-secret"


def _webhook_body(
    *, event_id: str, event_type: str, customer_id: str, clinic_id: str = "", **data_overrides
) -> bytes:
    data = {"id": "sub_e2e", "customer_id": customer_id, "status": "active", "items": []}
    if clinic_id:
        # Mirrors real Paddle.js checkout: the customer_id isn't known to
        # our side until the first webhook, so _find_subscription resolves
        # via custom_data.clinic_id and backfills paddle_customer_id itself
        # — see webhook_processor.py::_find_subscription's own docstring.
        data["custom_data"] = {"clinic_id": clinic_id}
    data.update(data_overrides)
    payload = {
        "event_id": event_id,
        "event_type": event_type,
        "occurred_at": timezone.now().isoformat(),
        "notification_id": f"ntf_{event_id}",
        "data": data,
    }
    return json.dumps(payload).encode("utf-8")


@override_settings(
    PADDLE_WEBHOOK_SECRET=WEBHOOK_SECRET,
    OTP_PROVIDER="mock",
    DEBUG=True,
    PLATFORM_NOTIFICATION_EMAIL="team@synapse.example.com",
    BILLING_GRACE_PERIOD_DAYS=7,
)
class SaasLifecycleEndToEndTest(TestCase):
    def _post_webhook(self, body: bytes):
        return self.client.post(
            WEBHOOK_URL, data=body, content_type="application/json",
            HTTP_PADDLE_SIGNATURE=_sign(body, secret=WEBHOOK_SECRET),
        )

    def test_full_journey(self):
        with patch("apps.notifications.service.NotificationService.send_email") as mock_email:
            # ── 1. Demo request submitted from the marketing site ──────
            plan = Plan.objects.create(slug="e2e-growth", name="Growth")
            submit_resp = self.client.post(
                APPLICATIONS_URL,
                data={
                    "clinic_name": "Journey Dental",
                    "owner_name": "Jamie Rivera",
                    "work_email": "jamie@journey-dental.example.com",
                    "phone": "+15551234000",
                    "notes": "Interested in the AI front desk.",
                    "source": "demo_request",
                },
                content_type="application/json",
            )
            self.assertEqual(submit_resp.status_code, 200)
            application_id = submit_resp.json()["id"]
            self.assertEqual(submit_resp.json()["status"], "pending")

            # Applicant confirmation + internal team notification both fired.
            recipients = {c.kwargs["to"] for c in mock_email.call_args_list}
            self.assertIn("jamie@journey-dental.example.com", recipients)
            self.assertIn("team@synapse.example.com", recipients)
        mock_email.reset_mock()

        # ── 2. Super Admin approves, provisioning Clinic + Subscription
        #      + owner (inactive) + invite token ──────────────────────
        from apps.api.platform.tests import make_super_admin

        _, admin_headers = make_super_admin(email="root@journey-e2e.test")
        with patch("apps.notifications.service.NotificationService.send_email") as mock_email:
            approve_resp = self.client.post(
                f"/api/v1/platform/applications/{application_id}/approve",
                data={"plan_slug": plan.slug}, content_type="application/json",
                headers=admin_headers,
            )
        self.assertEqual(approve_resp.status_code, 200)
        approve_body = approve_resp.json()
        self.assertEqual(approve_body["application"]["status"], "converted")
        clinic_id = approve_body["clinic"]["id"]
        clinic = Clinic.objects.get(id=clinic_id)
        self.assertEqual(clinic.status, ClinicStatus.ONBOARDING)

        subscription = Subscription.objects.get(clinic=clinic)
        self.assertEqual(subscription.status, SubscriptionStatus.INCOMPLETE)
        self.assertEqual(subscription.access_status, AccessStatus.ACTIVE)  # not suspended pre-payment

        self.assertTrue(
            AuditLog.objects.filter(action=AuditAction.APPLICATION_APPROVED, clinic=clinic).exists()
        )
        invite_email_sent = any(
            c.kwargs["to"] == "jamie@journey-dental.example.com" for c in mock_email.call_args_list
        )
        self.assertTrue(invite_email_sent)

        invite_token_row = StaffAuthToken.objects.get(
            purpose=StaffAuthTokenPurpose.INVITE, user__email="jamie@journey-dental.example.com"
        )
        # The raw token is never stored — only its hash — so it has to be
        # captured from where it was minted, mirroring what a real email
        # link would carry. Reissue here since the original raw value
        # wasn't captured above (only NotificationService.send_email's
        # rendered body would have had it, and asserting against rendered
        # copy is brittle) — this models "the owner clicks the link".
        _, raw_token = StaffAuthToken.issue(
            user=invite_token_row.user, purpose=StaffAuthTokenPurpose.INVITE
        )

        # ── 3. Owner accepts the invite — account activates ────────────
        accept_resp = self.client.post(
            "/api/v1/auth/accept-invite",
            data={"token": raw_token, "password": "JourneyStrongPass1!"},
            content_type="application/json",
        )
        self.assertEqual(accept_resp.status_code, 200)
        owner_headers = {"Authorization": f"Bearer {accept_resp.json()['access_token']}"}
        owner = invite_token_row.user
        owner.refresh_from_db()
        self.assertTrue(owner.is_active)

        # ── 4. Onboarding: fill in the operational checklist ────────────
        clinic.clinic_type = ClinicType.DENTAL
        clinic.address = {
            "line1": "1 Journey Way", "city": "Springfield", "state": "IL",
            "postal_code": "62701", "country": "US",
        }
        clinic.phone = "+15551234000"
        clinic.save(update_fields=["clinic_type", "address", "phone", "updated_at"])

        doctor = Doctor.objects.create(clinic=clinic, full_name="Dr. Jamie Rivera")
        Service.objects.create(clinic=clinic, name="Cleaning", duration_min=30)
        ClinicBusinessHours.objects.create(
            clinic=clinic, day_of_week=0, open_time=time_(9, 0), close_time=time_(17, 0),
        )
        DoctorSchedule.objects.create(
            clinic=clinic, doctor=doctor, day_of_week=0,
            start_time=time_(9, 0), end_time=time_(17, 0),
        )

        status_resp = self.client.get("/api/v1/clinics/me/onboarding-status", headers=owner_headers)
        self.assertEqual(status_resp.status_code, 200)
        self.assertTrue(status_resp.json()["ready"])

        # Checklist ready, but there's a real (unpaid) Subscription — the
        # clinic must NOT activate yet, and must be routed to the billing
        # step instead (apps/api/clinics/router.py::complete_onboarding).
        complete_resp = self.client.post(
            "/api/v1/clinics/me/onboarding/complete", headers=owner_headers
        )
        self.assertEqual(complete_resp.status_code, 200)
        self.assertEqual(complete_resp.json()["status"], "onboarding")
        clinic.refresh_from_db()
        self.assertEqual(clinic.onboarding_step, "billing")

        # ── 5. Knowledge-base upload (CSV — SaaS-Phase 6) ───────────────
        upload_resp = self.client.post(
            "/api/v1/documents",
            data={
                "title": "FAQ",
                "file": SimpleUploadedFile(
                    "faq.csv", b"Question,Answer\nDo you take walk-ins?,Yes\n", content_type="text/csv"
                ),
            },
            headers=owner_headers,
        )
        self.assertEqual(upload_resp.status_code, 201)
        self.assertEqual(upload_resp.json()["file_type"], "csv")
        self.assertTrue(
            AuditLog.objects.filter(action=AuditAction.DOCUMENT_UPLOAD, clinic=clinic).exists()
        )

        # ── 6. Phone verification (SaaS-Phase 1/2, mock provider) ───────
        send_resp = self.client.post(
            "/api/v1/verification/send",
            data={"to": "+15559998888", "channel": "sms"},
            content_type="application/json", headers=owner_headers,
        )
        self.assertEqual(send_resp.status_code, 200)
        dev_code = send_resp.json()["dev_code"]
        self.assertIsNotNone(dev_code)

        check_resp = self.client.post(
            "/api/v1/verification/check",
            data={"to": "+15559998888", "code": dev_code},
            content_type="application/json", headers=owner_headers,
        )
        self.assertEqual(check_resp.status_code, 200)
        self.assertEqual(check_resp.json()["status"], "approved")
        self.assertTrue(
            AuditLog.objects.filter(action=AuditAction.PHONE_VERIFY_APPROVED, clinic=clinic).exists()
        )

        # ── 7. Paddle confirms the subscription — clinic activates ──────
        # First delivery resolves via custom_data.clinic_id (paddle_customer_id
        # isn't known to us yet) and backfills it — every later event in
        # this test resolves by paddle_customer_id alone, as it would in
        # production once the first webhook has landed.
        with patch("apps.notifications.service.NotificationService.send_email"):
            active_resp = self._post_webhook(
                _webhook_body(
                    event_id="e2e_evt_active", event_type="subscription.created",
                    customer_id="ctm_e2e", status="active", clinic_id=str(clinic.id),
                )
            )
        self.assertEqual(active_resp.status_code, 200)
        subscription.refresh_from_db()
        self.assertEqual(subscription.paddle_customer_id, "ctm_e2e")
        self.assertEqual(subscription.status, SubscriptionStatus.ACTIVE)
        clinic.refresh_from_db()
        self.assertEqual(clinic.status, ClinicStatus.ACTIVE)  # maybe_activate_clinic fired

        # ── 8. Successful payment ────────────────────────────────────
        with patch(
            "apps.notifications.service.NotificationService.send_payment_successful_email"
        ) as mock_paid:
            self._post_webhook(
                _webhook_body(
                    event_id="e2e_evt_paid", event_type="transaction.completed",
                    customer_id="ctm_e2e",
                )
            )
        mock_paid.assert_called_once()

        # ── 9. Payment fails — grace period, access still granted ───────
        with patch("apps.notifications.service.NotificationService.send_email"):
            self._post_webhook(
                _webhook_body(
                    event_id="e2e_evt_pastdue", event_type="subscription.updated",
                    customer_id="ctm_e2e", status="past_due",
                )
            )
        subscription.refresh_from_db()
        self.assertEqual(subscription.access_status, AccessStatus.GRACE_PERIOD)
        still_ok = self.client.get("/api/v1/auth/me", headers=owner_headers)
        self.assertEqual(still_ok.status_code, 200)  # grace period — not locked out

        # ── 10. Payment recovers ─────────────────────────────────────
        with patch(
            "apps.notifications.service.NotificationService.send_payment_recovered_email"
        ) as mock_recovered:
            self._post_webhook(
                _webhook_body(
                    event_id="e2e_evt_recovered", event_type="subscription.updated",
                    customer_id="ctm_e2e", status="active",
                )
            )
        mock_recovered.assert_called_once()
        subscription.refresh_from_db()
        self.assertEqual(subscription.access_status, AccessStatus.ACTIVE)
        self.assertIsNone(subscription.grace_period_started_at)

        # ── 11. Subscription canceled — access suspended ────────────────
        with patch(
            "apps.notifications.service.NotificationService.send_subscription_canceled_email"
        ) as mock_canceled:
            self._post_webhook(
                _webhook_body(
                    event_id="e2e_evt_canceled", event_type="subscription.updated",
                    customer_id="ctm_e2e", status="canceled",
                )
            )
        mock_canceled.assert_called_once()
        subscription.refresh_from_db()
        self.assertEqual(subscription.access_status, AccessStatus.SUSPENDED)

        locked_out = self.client.get("/api/v1/auth/me", headers=owner_headers)
        self.assertEqual(locked_out.status_code, 401)
