"""Subscription.access_status / grace_period_ends_at — the application's
own access decision, computed lazily (no scheduled-job runner exists in
this codebase to flip a stored value the instant a grace period elapses)."""

from __future__ import annotations

from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.api.test_helpers import make_clinic_admin
from apps.billing.models import AccessStatus, Plan, Subscription, SubscriptionStatus
from apps.billing.tests.test_lifecycle_emails import _subscription_body
from apps.billing.tests.test_webhooks import _sign
from apps.clinics.models import Clinic

WEBHOOK_URL = "/api/v1/billing/paddle/webhook"
TEST_SECRET = "test-webhook-secret"
SUBSCRIPTION_URL = "/api/v1/billing/subscription"


class AccessStatusTests(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="access-status-clinic", name="Access Status Clinic",
            email="owner@access-status.example.com",
        )
        self.plan = Plan.objects.create(slug="growth3", name="Growth")

    def _sub(self, **overrides) -> Subscription:
        defaults = dict(clinic=self.clinic, plan=self.plan, paddle_customer_id="ctm_x")
        defaults.update(overrides)
        return Subscription.objects.create(**defaults)

    def test_trialing_and_active_are_access_active(self):
        for status in (SubscriptionStatus.TRIALING, SubscriptionStatus.ACTIVE):
            sub = self._sub(status=status)
            self.assertEqual(sub.access_status, AccessStatus.ACTIVE)
            sub.delete()

    def test_incomplete_is_active_not_suspended(self):
        """INCOMPLETE means checkout hasn't been confirmed *yet* — the
        normal state for a clinic mid-onboarding, not a revoked
        subscription. Regression: this was originally (wrongly) SUSPENDED,
        which locked owners out of finishing their own onboarding/checkout
        before they'd ever had a chance to pay — caught by
        apps.clinics.tests.OnboardingBillingGateTests failing a real
        onboarding-completion request with 401."""
        sub = self._sub(status=SubscriptionStatus.INCOMPLETE)
        self.assertEqual(sub.access_status, AccessStatus.ACTIVE)

    def test_paused_is_suspended(self):
        sub = self._sub(status=SubscriptionStatus.PAUSED)
        self.assertEqual(sub.access_status, AccessStatus.SUSPENDED)

    def test_canceled_is_suspended(self):
        sub = self._sub(status=SubscriptionStatus.CANCELED)
        self.assertEqual(sub.access_status, AccessStatus.SUSPENDED)

    def test_past_due_with_no_timer_yet_is_grace_period(self):
        """A past_due status without grace_period_started_at set (e.g. data
        seeded directly, or the webhook path not yet run) defaults to the
        safe direction — grace, not an immediate lockout."""
        sub = self._sub(status=SubscriptionStatus.PAST_DUE, grace_period_started_at=None)
        self.assertEqual(sub.access_status, AccessStatus.GRACE_PERIOD)
        self.assertIsNone(sub.grace_period_ends_at)

    @override_settings(BILLING_GRACE_PERIOD_DAYS=7)
    def test_past_due_within_window_is_grace_period(self):
        sub = self._sub(
            status=SubscriptionStatus.PAST_DUE,
            grace_period_started_at=timezone.now() - timedelta(days=3),
        )
        self.assertEqual(sub.access_status, AccessStatus.GRACE_PERIOD)
        self.assertGreater(sub.grace_period_ends_at, timezone.now())

    @override_settings(BILLING_GRACE_PERIOD_DAYS=7)
    def test_past_due_beyond_window_is_suspended(self):
        sub = self._sub(
            status=SubscriptionStatus.PAST_DUE,
            grace_period_started_at=timezone.now() - timedelta(days=8),
        )
        self.assertEqual(sub.access_status, AccessStatus.SUSPENDED)
        self.assertLess(sub.grace_period_ends_at, timezone.now())

    @override_settings(BILLING_GRACE_PERIOD_DAYS=3)
    def test_grace_period_days_is_configurable(self):
        sub = self._sub(
            status=SubscriptionStatus.PAST_DUE,
            grace_period_started_at=timezone.now() - timedelta(days=4),
        )
        self.assertEqual(sub.access_status, AccessStatus.SUSPENDED)

    def test_grace_period_ends_at_is_none_outside_past_due(self):
        sub = self._sub(
            status=SubscriptionStatus.ACTIVE,
            grace_period_started_at=timezone.now() - timedelta(days=1),
        )
        self.assertIsNone(sub.grace_period_ends_at)


@override_settings(PADDLE_WEBHOOK_SECRET=TEST_SECRET)
class GracePeriodTimerWebhookTests(TestCase):
    """grace_period_started_at is managed entirely by real webhook
    delivery — set on first entry to past_due, cleared on exit, never
    reset by a redundant redelivery of the same status."""

    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="grace-timer-clinic", name="Grace Timer Clinic",
            email="owner@grace-timer.example.com",
        )
        self.plan = Plan.objects.create(slug="growth4", name="Growth")

    def _post(self, body: bytes):
        return self.client.post(
            WEBHOOK_URL, data=body, content_type="application/json",
            HTTP_PADDLE_SIGNATURE=_sign(body, secret=TEST_SECRET),
        )

    def test_entering_past_due_starts_the_timer(self):
        Subscription.objects.create(
            clinic=self.clinic, plan=self.plan, paddle_customer_id="ctm_g1",
            status=SubscriptionStatus.ACTIVE,
        )
        body = _subscription_body(event_id="grace_evt_1", customer_id="ctm_g1", status="past_due")
        self._post(body)
        sub = Subscription.objects.get(paddle_customer_id="ctm_g1")
        self.assertIsNotNone(sub.grace_period_started_at)

    def test_leaving_past_due_clears_the_timer(self):
        started = timezone.now() - timedelta(days=2)
        Subscription.objects.create(
            clinic=self.clinic, plan=self.plan, paddle_customer_id="ctm_g2",
            status=SubscriptionStatus.PAST_DUE, grace_period_started_at=started,
        )
        body = _subscription_body(event_id="grace_evt_2", customer_id="ctm_g2", status="active")
        self._post(body)
        sub = Subscription.objects.get(paddle_customer_id="ctm_g2")
        self.assertIsNone(sub.grace_period_started_at)

    def test_redundant_past_due_redelivery_does_not_extend_the_timer(self):
        """A second, later past_due event for a subscription already in
        past_due must not push the deadline further out — only the first
        entry starts the clock."""
        original_start = timezone.now() - timedelta(days=5)
        Subscription.objects.create(
            clinic=self.clinic, plan=self.plan, paddle_customer_id="ctm_g3",
            status=SubscriptionStatus.PAST_DUE, grace_period_started_at=original_start,
            occurred_at=timezone.now() - timedelta(days=5),
        )
        body = _subscription_body(
            event_id="grace_evt_3", customer_id="ctm_g3", status="past_due",
            occurred_at=timezone.now().isoformat(),
        )
        self._post(body)
        sub = Subscription.objects.get(paddle_customer_id="ctm_g3")
        self.assertEqual(sub.grace_period_started_at, original_start)


class SubscriptionEndpointAccessStatusTests(TestCase):
    """GET /billing/subscription exposes access_status/grace_period_ends_at
    for the billing UI (Part 18's "we couldn't process your payment, you're
    still active" messaging needs to know which state it's in)."""

    def setUp(self):
        self.user, self.clinic, self.headers = make_clinic_admin(
            email="owner@endpoint-access.example.com", clinic_slug="endpoint-access-clinic"
        )
        self.plan = Plan.objects.create(slug="endpoint-plan", name="Endpoint Plan")

    def test_no_subscription_reports_suspended_for_display(self):
        resp = self.client.get(SUBSCRIPTION_URL, headers=self.headers)
        body = resp.json()
        self.assertEqual(body["access_status"], "suspended")
        self.assertFalse(body["has_access"])

    def test_active_subscription_reports_active(self):
        Subscription.objects.create(
            clinic=self.clinic, plan=self.plan, status=SubscriptionStatus.ACTIVE,
        )
        resp = self.client.get(SUBSCRIPTION_URL, headers=self.headers)
        body = resp.json()
        self.assertEqual(body["access_status"], "active")
        self.assertIsNone(body["grace_period_ends_at"])

    def test_past_due_reports_grace_period_with_deadline(self):
        Subscription.objects.create(
            clinic=self.clinic, plan=self.plan, status=SubscriptionStatus.PAST_DUE,
            grace_period_started_at=timezone.now(),
        )
        resp = self.client.get(SUBSCRIPTION_URL, headers=self.headers)
        body = resp.json()
        self.assertEqual(body["access_status"], "grace_period")
        self.assertIsNotNone(body["grace_period_ends_at"])
