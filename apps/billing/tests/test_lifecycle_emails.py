"""Billing lifecycle emails fired from Paddle webhooks.

transaction.* events (payment success/failure/past-due) and genuine
subscription.status transitions (→paused, →canceled, past_due→active
"recovered") each trigger exactly one NotificationService call — never on
a redundant/duplicate webhook delivery, never on a no-op status re-send.
"""

from __future__ import annotations

import json
import time
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.billing.models import Plan, Subscription, SubscriptionStatus
from apps.billing.tests.test_webhooks import _sign
from apps.clinics.models import Clinic, ClinicStatus

WEBHOOK_URL = "/api/v1/billing/paddle/webhook"
TEST_SECRET = "test-webhook-secret"


def _transaction_body(
    *, event_id: str, event_type: str, customer_id: str, occurred_at: str | None = None
) -> bytes:
    payload = {
        "event_id": event_id,
        "event_type": event_type,
        "occurred_at": occurred_at or timezone.now().isoformat(),
        "notification_id": f"ntf_{event_id}",
        "data": {"id": f"txn_{event_id}", "customer_id": customer_id, "status": "completed"},
    }
    return json.dumps(payload).encode("utf-8")


def _subscription_body(
    *, event_id: str, customer_id: str, status: str, occurred_at: str | None = None
) -> bytes:
    payload = {
        "event_id": event_id,
        "event_type": "subscription.updated",
        "occurred_at": occurred_at or timezone.now().isoformat(),
        "notification_id": f"ntf_{event_id}",
        "data": {
            "id": "sub_123",
            "customer_id": customer_id,
            "status": status,
            "current_billing_period": {},
            "items": [],
        },
    }
    return json.dumps(payload).encode("utf-8")


@override_settings(PADDLE_WEBHOOK_SECRET=TEST_SECRET)
class TransactionEventEmailTests(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="lifecycle-clinic", name="Lifecycle Clinic", email="billing@lifecycle.example.com",
            status=ClinicStatus.ACTIVE,
        )
        self.plan = Plan.objects.create(slug="growth", name="Growth")
        self.sub = Subscription.objects.create(
            clinic=self.clinic, plan=self.plan, paddle_customer_id="ctm_lifecycle",
            status=SubscriptionStatus.ACTIVE,
        )

    def _post(self, body: bytes):
        return self.client.post(
            WEBHOOK_URL, data=body, content_type="application/json",
            HTTP_PADDLE_SIGNATURE=_sign(body, secret=TEST_SECRET),
        )

    def test_transaction_completed_sends_payment_successful_once(self):
        body = _transaction_body(
            event_id="txn_evt_1", event_type="transaction.completed", customer_id="ctm_lifecycle"
        )
        with patch(
            "apps.notifications.service.NotificationService.send_payment_successful_email"
        ) as mock_send:
            resp = self._post(body)
        self.assertEqual(resp.status_code, 200)
        mock_send.assert_called_once_with(
            to="billing@lifecycle.example.com", clinic_name="Lifecycle Clinic", plan_name="Growth"
        )

    def test_duplicate_transaction_completed_delivery_does_not_resend(self):
        body = _transaction_body(
            event_id="txn_evt_dup", event_type="transaction.completed", customer_id="ctm_lifecycle"
        )
        with patch(
            "apps.notifications.service.NotificationService.send_payment_successful_email"
        ) as mock_send:
            self._post(body)
            resp2 = self._post(body)  # exact same signed body, second delivery
        self.assertEqual(resp2.status_code, 200)
        mock_send.assert_called_once()

    def test_transaction_payment_failed_sends_payment_failed_email(self):
        body = _transaction_body(
            event_id="txn_evt_2", event_type="transaction.payment_failed", customer_id="ctm_lifecycle"
        )
        with patch(
            "apps.notifications.service.NotificationService.send_payment_failed_email"
        ) as mock_send:
            self._post(body)
        mock_send.assert_called_once_with(
            to="billing@lifecycle.example.com", clinic_name="Lifecycle Clinic"
        )

    def test_transaction_past_due_sends_payment_past_due_email(self):
        body = _transaction_body(
            event_id="txn_evt_3", event_type="transaction.past_due", customer_id="ctm_lifecycle"
        )
        with patch(
            "apps.notifications.service.NotificationService.send_payment_past_due_email"
        ) as mock_send:
            self._post(body)
        mock_send.assert_called_once_with(
            to="billing@lifecycle.example.com", clinic_name="Lifecycle Clinic"
        )

    def test_transaction_paid_is_not_wired_to_avoid_double_notifying(self):
        """Deliberate: only transaction.completed sends the success email —
        Paddle can fire both `completed` and `paid` for one real payment."""
        body = _transaction_body(
            event_id="txn_evt_4", event_type="transaction.paid", customer_id="ctm_lifecycle"
        )
        with patch(
            "apps.notifications.service.NotificationService.send_payment_successful_email"
        ) as mock_send:
            resp = self._post(body)
        self.assertEqual(resp.status_code, 200)
        mock_send.assert_not_called()

    def test_unresolvable_customer_id_does_not_crash_or_send(self):
        body = _transaction_body(
            event_id="txn_evt_5", event_type="transaction.completed", customer_id="ctm_unknown"
        )
        with patch(
            "apps.notifications.service.NotificationService.send_payment_successful_email"
        ) as mock_send:
            resp = self._post(body)
        self.assertEqual(resp.status_code, 200)
        mock_send.assert_not_called()

    def test_clinic_with_no_email_is_skipped_gracefully(self):
        self.clinic.email = ""
        self.clinic.save(update_fields=["email"])
        body = _transaction_body(
            event_id="txn_evt_6", event_type="transaction.completed", customer_id="ctm_lifecycle"
        )
        with patch(
            "apps.notifications.service.NotificationService.send_payment_successful_email"
        ) as mock_send:
            resp = self._post(body)
        self.assertEqual(resp.status_code, 200)
        mock_send.assert_not_called()


@override_settings(PADDLE_WEBHOOK_SECRET=TEST_SECRET)
class SubscriptionTransitionEmailTests(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="transition-clinic", name="Transition Clinic",
            email="billing@transition.example.com", status=ClinicStatus.ACTIVE,
        )
        self.plan = Plan.objects.create(slug="growth2", name="Growth")

    def _post(self, body: bytes):
        return self.client.post(
            WEBHOOK_URL, data=body, content_type="application/json",
            HTTP_PADDLE_SIGNATURE=_sign(body, secret=TEST_SECRET),
        )

    def test_transition_to_paused_sends_email(self):
        sub = Subscription.objects.create(
            clinic=self.clinic, plan=self.plan, paddle_customer_id="ctm_t1",
            status=SubscriptionStatus.ACTIVE,
        )
        body = _subscription_body(event_id="sub_evt_1", customer_id="ctm_t1", status="paused")
        with patch(
            "apps.notifications.service.NotificationService.send_subscription_paused_email"
        ) as mock_send:
            self._post(body)
        mock_send.assert_called_once_with(
            to="billing@transition.example.com", clinic_name="Transition Clinic"
        )
        sub.refresh_from_db()
        self.assertEqual(sub.status, SubscriptionStatus.PAUSED)

    def test_redundant_paused_status_does_not_resend(self):
        """Same status arriving again (e.g. a second subscription.updated
        for an unrelated field change) must not re-notify — only a real
        transition does."""
        sub = Subscription.objects.create(
            clinic=self.clinic, plan=self.plan, paddle_customer_id="ctm_t2",
            status=SubscriptionStatus.PAUSED,
        )
        later = (timezone.now()).isoformat()
        body = _subscription_body(
            event_id="sub_evt_2", customer_id="ctm_t2", status="paused", occurred_at=later
        )
        with patch(
            "apps.notifications.service.NotificationService.send_subscription_paused_email"
        ) as mock_send:
            self._post(body)
        mock_send.assert_not_called()

    def test_transition_to_canceled_sends_email(self):
        Subscription.objects.create(
            clinic=self.clinic, plan=self.plan, paddle_customer_id="ctm_t3",
            status=SubscriptionStatus.ACTIVE,
        )
        body = _subscription_body(event_id="sub_evt_3", customer_id="ctm_t3", status="canceled")
        with patch(
            "apps.notifications.service.NotificationService.send_subscription_canceled_email"
        ) as mock_send:
            self._post(body)
        mock_send.assert_called_once()

    def test_past_due_to_active_sends_payment_recovered(self):
        Subscription.objects.create(
            clinic=self.clinic, plan=self.plan, paddle_customer_id="ctm_t4",
            status=SubscriptionStatus.PAST_DUE,
        )
        body = _subscription_body(event_id="sub_evt_4", customer_id="ctm_t4", status="active")
        with patch(
            "apps.notifications.service.NotificationService.send_payment_recovered_email"
        ) as mock_send:
            self._post(body)
        mock_send.assert_called_once_with(
            to="billing@transition.example.com", clinic_name="Transition Clinic"
        )

    def test_trialing_to_active_does_not_send_payment_recovered(self):
        """Recovery specifically means "was past_due" — a normal trial
        conversion must not be phrased as a payment recovery."""
        Subscription.objects.create(
            clinic=self.clinic, plan=self.plan, paddle_customer_id="ctm_t5",
            status=SubscriptionStatus.TRIALING,
        )
        body = _subscription_body(event_id="sub_evt_5", customer_id="ctm_t5", status="active")
        with patch(
            "apps.notifications.service.NotificationService.send_payment_recovered_email"
        ) as mock_send:
            self._post(body)
        mock_send.assert_not_called()

    def test_paused_to_active_sends_account_reactivated_not_payment_recovered(self):
        """Resuming a paused subscription isn't a payment-failure story —
        must use the distinct "welcome back" copy, not "payment recovered"."""
        Subscription.objects.create(
            clinic=self.clinic, plan=self.plan, paddle_customer_id="ctm_t7",
            status=SubscriptionStatus.PAUSED,
        )
        body = _subscription_body(event_id="sub_evt_7", customer_id="ctm_t7", status="active")
        with patch(
            "apps.notifications.service.NotificationService.send_account_reactivated_email"
        ) as mock_reactivated, patch(
            "apps.notifications.service.NotificationService.send_payment_recovered_email"
        ) as mock_recovered:
            self._post(body)
        mock_reactivated.assert_called_once_with(
            to="billing@transition.example.com", clinic_name="Transition Clinic"
        )
        mock_recovered.assert_not_called()

    def test_no_email_helper_called_when_status_is_unrecognized(self):
        """An unmapped Paddle status leaves sub.status unchanged — same
        value before/after means no transition, so no email regardless."""
        Subscription.objects.create(
            clinic=self.clinic, plan=self.plan, paddle_customer_id="ctm_t6",
            status=SubscriptionStatus.ACTIVE,
        )
        body = _subscription_body(
            event_id="sub_evt_6", customer_id="ctm_t6", status="some_future_paddle_status"
        )
        with patch("apps.notifications.service.NotificationService.send_email") as mock_send:
            resp = self._post(body)
        self.assertEqual(resp.status_code, 200)
        mock_send.assert_not_called()
