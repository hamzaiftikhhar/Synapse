"""Paddle webhook: signature verification, idempotency, ordering."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.billing.models import (
    BillingEvent,
    BillingEventStatus,
    Plan,
    Subscription,
    SubscriptionStatus,
)
from apps.clinics.models import Clinic, ClinicStatus

WEBHOOK_URL = "/api/v1/billing/paddle/webhook"
TEST_SECRET = "test-webhook-secret"


def _sign(body: bytes, secret: str = TEST_SECRET, ts: int | None = None) -> str:
    ts = ts if ts is not None else int(time.time())
    signed_payload = f"{ts}:".encode() + body
    h1 = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return f"ts={ts};h1={h1}"


def _event_body(
    *,
    event_id: str,
    event_type: str,
    customer_id: str,
    status: str = "active",
    occurred_at: str | None = None,
    subscription_id: str = "sub_123",
) -> bytes:
    occurred_at = occurred_at or timezone.now().isoformat()
    payload = {
        "event_id": event_id,
        "event_type": event_type,
        "occurred_at": occurred_at,
        "notification_id": f"ntf_{event_id}",
        "data": {
            "id": subscription_id,
            "customer_id": customer_id,
            "status": status,
            "current_billing_period": {
                "starts_at": timezone.now().isoformat(),
                "ends_at": (timezone.now() + timedelta(days=30)).isoformat(),
            },
            "items": [],
        },
    }
    return json.dumps(payload).encode("utf-8")


@override_settings(PADDLE_WEBHOOK_SECRET=TEST_SECRET)
class WebhookSignatureTests(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="webhook-clinic", name="Webhook Clinic", email="w@example.com",
            status=ClinicStatus.ACTIVE,
        )
        self.plan = Plan.objects.create(slug="starter", name="Starter")
        self.sub = Subscription.objects.create(
            clinic=self.clinic, plan=self.plan, paddle_customer_id="ctm_1"
        )

    def test_valid_signature_processed(self):
        body = _event_body(event_id="evt_1", event_type="subscription.created", customer_id="ctm_1")
        resp = self.client.post(
            WEBHOOK_URL, data=body, content_type="application/json",
            HTTP_PADDLE_SIGNATURE=_sign(body),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(BillingEvent.objects.filter(paddle_event_id="evt_1").count(), 1)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, SubscriptionStatus.ACTIVE)

    def test_missing_signature_rejected_no_db_mutation(self):
        body = _event_body(event_id="evt_2", event_type="subscription.created", customer_id="ctm_1")
        resp = self.client.post(WEBHOOK_URL, data=body, content_type="application/json")
        self.assertEqual(resp.status_code, 401)
        self.assertFalse(BillingEvent.objects.filter(paddle_event_id="evt_2").exists())

    def test_invalid_signature_rejected_no_db_mutation(self):
        body = _event_body(event_id="evt_3", event_type="subscription.created", customer_id="ctm_1")
        bad_sig = _sign(body, secret="wrong-secret")
        resp = self.client.post(
            WEBHOOK_URL, data=body, content_type="application/json", HTTP_PADDLE_SIGNATURE=bad_sig
        )
        self.assertEqual(resp.status_code, 401)
        self.assertFalse(BillingEvent.objects.filter(paddle_event_id="evt_3").exists())

    def test_malformed_signature_header_rejected(self):
        body = _event_body(event_id="evt_4", event_type="subscription.created", customer_id="ctm_1")
        resp = self.client.post(
            WEBHOOK_URL, data=body, content_type="application/json",
            HTTP_PADDLE_SIGNATURE="not-a-valid-header",
        )
        self.assertEqual(resp.status_code, 401)
        self.assertFalse(BillingEvent.objects.filter(paddle_event_id="evt_4").exists())

    def test_stale_timestamp_rejected(self):
        body = _event_body(event_id="evt_5", event_type="subscription.created", customer_id="ctm_1")
        old_ts = int(time.time()) - 3600
        resp = self.client.post(
            WEBHOOK_URL, data=body, content_type="application/json",
            HTTP_PADDLE_SIGNATURE=_sign(body, ts=old_ts),
        )
        self.assertEqual(resp.status_code, 401)


@override_settings(PADDLE_WEBHOOK_SECRET=TEST_SECRET)
class WebhookIdempotencyTests(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="idem-clinic", name="Idem Clinic", email="i@example.com",
            status=ClinicStatus.ACTIVE,
        )
        self.plan = Plan.objects.create(slug="starter", name="Starter")
        self.sub = Subscription.objects.create(
            clinic=self.clinic, plan=self.plan, paddle_customer_id="ctm_2"
        )

    def test_duplicate_event_not_applied_twice(self):
        body = _event_body(event_id="evt_dup", event_type="subscription.created", customer_id="ctm_2")
        sig = _sign(body)

        resp1 = self.client.post(
            WEBHOOK_URL, data=body, content_type="application/json", HTTP_PADDLE_SIGNATURE=sig
        )
        resp2 = self.client.post(
            WEBHOOK_URL, data=body, content_type="application/json", HTTP_PADDLE_SIGNATURE=sig
        )
        self.assertEqual(resp1.status_code, 200)
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(BillingEvent.objects.filter(paddle_event_id="evt_dup").count(), 1)
        event = BillingEvent.objects.get(paddle_event_id="evt_dup")
        self.assertEqual(event.status, BillingEventStatus.PROCESSED)


@override_settings(PADDLE_WEBHOOK_SECRET=TEST_SECRET)
class WebhookOrderingTests(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="order-clinic", name="Order Clinic", email="o@example.com",
            status=ClinicStatus.ACTIVE,
        )
        self.plan = Plan.objects.create(slug="starter", name="Starter")
        self.sub = Subscription.objects.create(
            clinic=self.clinic, plan=self.plan, paddle_customer_id="ctm_3"
        )

    def test_stale_event_does_not_overwrite_newer_state(self):
        now = timezone.now()
        newer = now.isoformat()
        older = (now - timedelta(minutes=5)).isoformat()

        newer_body = _event_body(
            event_id="evt_newer", event_type="subscription.updated",
            customer_id="ctm_3", status="active", occurred_at=newer,
        )
        self.client.post(
            WEBHOOK_URL, data=newer_body, content_type="application/json",
            HTTP_PADDLE_SIGNATURE=_sign(newer_body),
        )
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, SubscriptionStatus.ACTIVE)

        # A delayed, older event arrives after — must not downgrade state.
        older_body = _event_body(
            event_id="evt_older", event_type="subscription.updated",
            customer_id="ctm_3", status="past_due", occurred_at=older,
        )
        resp = self.client.post(
            WEBHOOK_URL, data=older_body, content_type="application/json",
            HTTP_PADDLE_SIGNATURE=_sign(older_body),
        )
        self.assertEqual(resp.status_code, 200)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, SubscriptionStatus.ACTIVE)


@override_settings(PADDLE_WEBHOOK_SECRET=TEST_SECRET)
class WebhookDrivenClinicActivationTests(TestCase):
    """End-to-end: a verified subscription.created webhook is what actually
    flips an onboarding clinic to active — not the checkout call, not the
    frontend's success callback."""

    def setUp(self):
        from apps.clinics.models import ClinicBusinessHours
        from apps.doctors.models import Doctor, DoctorSchedule
        from apps.services.models import Service

        self.clinic = Clinic.objects.create(
            slug="e2e-activation-clinic", name="E2E Activation Clinic",
            email="owner@e2e.example.com", status=ClinicStatus.ONBOARDING,
            clinic_type="dermatology", phone="555-0100",
            address={
                "line1": "1 Main St", "city": "New York", "state": "NY",
                "postal_code": "10001", "country": "US",
            },
        )
        doctor = Doctor.objects.create(clinic=self.clinic, full_name="Dr. Ready")
        Service.objects.create(clinic=self.clinic, name="Consultation", duration_min=30)
        ClinicBusinessHours.objects.create(
            clinic=self.clinic, day_of_week=0, open_time="09:00", close_time="17:00"
        )
        DoctorSchedule.objects.create(
            clinic=self.clinic, doctor=doctor, day_of_week=0,
            start_time="09:00", end_time="17:00",
        )
        self.plan = Plan.objects.create(slug="growth", name="Growth")
        self.sub = Subscription.objects.create(
            clinic=self.clinic, plan=self.plan, paddle_customer_id="ctm_e2e"
        )

    def test_active_webhook_activates_ready_clinic(self):
        body = _event_body(
            event_id="evt_activate", event_type="subscription.created",
            customer_id="ctm_e2e", status="active",
        )
        resp = self.client.post(
            WEBHOOK_URL, data=body, content_type="application/json",
            HTTP_PADDLE_SIGNATURE=_sign(body),
        )
        self.assertEqual(resp.status_code, 200)
        self.clinic.refresh_from_db()
        self.assertEqual(self.clinic.status, ClinicStatus.ACTIVE)

    def test_failed_payment_never_activates_clinic(self):
        """A subscription that never reaches active (e.g. checkout abandoned,
        card declined before Paddle ever creates it) leaves no webhook to
        process at all — the clinic simply stays in onboarding indefinitely,
        which is the correct default with no explicit action needed."""
        self.clinic.refresh_from_db()
        self.assertEqual(self.clinic.status, ClinicStatus.ONBOARDING)
        self.sub.refresh_from_db()
        self.assertFalse(self.sub.has_access)

    def test_orphaned_paddle_customer_attaches_to_incomplete_checkout(self):
        """Paddle.js can mint a new customer at pay time. The webhook must
        still land on the clinic that started checkout, not 200-and-ignore."""
        self.sub.paddle_customer_id = "ctm_01luminacheckout"
        self.sub.save(update_fields=["paddle_customer_id"])
        body = _event_body(
            event_id="evt_orphan_ctm",
            event_type="subscription.activated",
            customer_id="ctm_01brandnewfrompaddle",
            status="active",
        )
        resp = self.client.post(
            WEBHOOK_URL, data=body, content_type="application/json",
            HTTP_PADDLE_SIGNATURE=_sign(body),
        )
        self.assertEqual(resp.status_code, 200)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, SubscriptionStatus.ACTIVE)
        self.assertEqual(self.sub.paddle_customer_id, "ctm_01brandnewfrompaddle")
        self.assertEqual(self.sub.paddle_subscription_id, "sub_123")

    def test_subscription_custom_data_clinic_id_matches(self):
        other = Clinic.objects.create(
            slug="other-clinic", name="Other", email="o2@example.com",
            status=ClinicStatus.ACTIVE,
        )
        other_plan = self.plan
        Subscription.objects.create(
            clinic=other, plan=other_plan, paddle_customer_id="ctm_01other",
            status=SubscriptionStatus.INCOMPLETE,
        )
        payload = json.loads(
            _event_body(
                event_id="evt_custom_clinic",
                event_type="subscription.activated",
                customer_id="ctm_01overlaynew",
                status="active",
            )
        )
        payload["data"]["custom_data"] = {"clinic_id": str(self.clinic.id)}
        body = json.dumps(payload).encode("utf-8")
        resp = self.client.post(
            WEBHOOK_URL, data=body, content_type="application/json",
            HTTP_PADDLE_SIGNATURE=_sign(body),
        )
        self.assertEqual(resp.status_code, 200)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, SubscriptionStatus.ACTIVE)
        self.assertEqual(self.sub.paddle_customer_id, "ctm_01overlaynew")

    def test_past_due_webhook_does_not_activate_clinic(self):
        body = _event_body(
            event_id="evt_past_due", event_type="subscription.updated",
            customer_id="ctm_e2e", status="past_due",
        )
        resp = self.client.post(
            WEBHOOK_URL, data=body, content_type="application/json",
            HTTP_PADDLE_SIGNATURE=_sign(body),
        )
        self.assertEqual(resp.status_code, 200)
        self.clinic.refresh_from_db()
        self.assertEqual(self.clinic.status, ClinicStatus.ONBOARDING)
