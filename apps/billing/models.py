"""Paddle billing — Plan catalog, per-clinic Subscription, webhook BillingEvent.

Paddle owns payment/billing truth. This app mirrors just enough state
locally to answer "what can this clinic do" without calling Paddle on every
request. Subscription state is only ever written by a verified webhook (see
services/webhook_processor.py) — the checkout/cancel/change-plan endpoints
call Paddle and wait for the resulting event; they never mutate Subscription
directly themselves.
"""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from core.models import TimestampedModel, UUIDModel


class BillingInterval(models.TextChoices):
    MONTH = "month", "Monthly"
    YEAR = "year", "Yearly"


class Plan(UUIDModel, TimestampedModel):
    """Our own pricing catalog — decoupled from Paddle's Product/Price so
    plan names/prices can change without touching application logic.
    Sandbox and live price IDs live on the same row since they're the same
    conceptual plan across environments."""

    slug = models.SlugField(max_length=64, unique=True)
    name = models.CharField(max_length=100)
    paddle_price_id_sandbox = models.CharField(max_length=64, blank=True, default="")
    paddle_price_id_live = models.CharField(max_length=64, blank=True, default="")
    billing_interval = models.CharField(
        max_length=10, choices=BillingInterval.choices, default=BillingInterval.MONTH
    )
    # Display-only — Paddle's price is the actual billing authority. Lets
    # the plan picker show a price without an extra Paddle API round trip.
    display_price_cents = models.PositiveIntegerField(null=True, blank=True)
    display_currency = models.CharField(max_length=3, default="USD")
    is_active = models.BooleanField(default=True)
    display_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "billing_plans"
        ordering = ["display_order", "name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.billing_interval})"

    def paddle_price_id(self, environment: str) -> str:
        return (
            self.paddle_price_id_live
            if environment == "live"
            else self.paddle_price_id_sandbox
        )


class SubscriptionStatus(models.TextChoices):
    """Our own status vocabulary, mapped from Paddle's subscription.status
    in webhook_processor.py — decoupled so a Paddle wording change doesn't
    ripple through every access check in the app."""

    # Local-only state: a Paddle customer exists (checkout was initiated)
    # but Paddle has not yet confirmed a real subscription via webhook.
    # Never granted access under has_access below.
    INCOMPLETE = "incomplete", "Incomplete"
    TRIALING = "trialing", "Trialing"
    ACTIVE = "active", "Active"
    PAST_DUE = "past_due", "Past due"
    PAUSED = "paused", "Paused"
    CANCELED = "canceled", "Canceled"


class AccessStatus(models.TextChoices):
    """The application's access decision — distinct from SubscriptionStatus
    (Paddle's own status). See Subscription.access_status."""

    ACTIVE = "active", "Active"
    GRACE_PERIOD = "grace_period", "Grace period"
    SUSPENDED = "suspended", "Suspended"


class Subscription(UUIDModel, TimestampedModel):
    """One per Clinic — this repo has no Organization/BillingAccount layer
    above Clinic (confirmed via repo audit), so Clinic is the natural,
    existing tenant to own a subscription 1:1."""

    clinic = models.OneToOneField(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="subscription",
    )
    paddle_customer_id = models.CharField(max_length=64, blank=True, default="")
    # No string default here on purpose: this is unique=True, and Postgres
    # treats "" as a real, colliding value but NULL as distinct-per-row — a
    # default of "" would make the second clinic ever provisioned without a
    # confirmed Paddle subscription yet fail with a duplicate-key error.
    paddle_subscription_id = models.CharField(
        max_length=64, blank=True, default=None, null=True, unique=True
    )
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="subscriptions")
    status = models.CharField(
        max_length=20,
        choices=SubscriptionStatus.choices,
        default=SubscriptionStatus.INCOMPLETE,
    )
    current_period_start = models.DateTimeField(null=True, blank=True)
    current_period_end = models.DateTimeField(null=True, blank=True)
    cancel_at_period_end = models.BooleanField(default=False)
    canceled_at = models.DateTimeField(null=True, blank=True)
    # Timestamp of the last webhook event actually applied to this row — a
    # stale/out-of-order delivery with an older occurred_at than this must
    # never overwrite newer state. See webhook_processor.py.
    occurred_at = models.DateTimeField(null=True, blank=True)
    # Set when `status` transitions *into* PAST_DUE, cleared when it
    # transitions *out of* PAST_DUE (recovered or canceled) — see
    # webhook_processor.py::_apply_subscription_event. Powers access_status
    # below; not touched for any other status.
    grace_period_started_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "billing_subscriptions"
        indexes = [
            models.Index(fields=["paddle_customer_id"]),
        ]

    def __str__(self) -> str:
        return f"{self.clinic.slug} — {self.plan.slug} ({self.status})"

    @property
    def has_access(self) -> bool:
        """Coarse "is this clinic paid up" check. cancel_at_period_end alone
        does not revoke access — access lasts until the period actually
        ends and Paddle sends the terminal canceled event."""
        return self.status in {SubscriptionStatus.TRIALING, SubscriptionStatus.ACTIVE}

    @property
    def access_status(self) -> str:
        """The application's own interpretation of Paddle's status —
        deliberately a separate concept from `status` itself (see module
        docstring: Paddle owns billing truth, this is *our* access
        decision). PAST_DUE gets a grace window before we actually restrict
        anything; PAUSED/CANCELED (a subscription that *was* paying and
        stopped) are immediately SUSPENDED.

        INCOMPLETE is deliberately grouped with ACTIVE here, not SUSPENDED
        — it means checkout hasn't been confirmed *yet* (the normal state
        for a clinic mid-onboarding), never that access was revoked. Access
        control for that stage is `Clinic.status` staying `onboarding`
        (a completely different, pre-existing gate) — this property must
        not also lock the owner out of finishing checkout in the first
        place. (Regression caught by apps.clinics.tests.
        OnboardingBillingGateTests before this shipped.)

        Evaluated lazily at read time (there is no scheduled-job runner in
        this codebase to flip a stored value the instant a grace period
        elapses) — see apps/api/auth/deps.py for where this is enforced.
        """
        if self.status in {
            SubscriptionStatus.INCOMPLETE,
            SubscriptionStatus.TRIALING,
            SubscriptionStatus.ACTIVE,
        }:
            return AccessStatus.ACTIVE
        if self.status == SubscriptionStatus.PAST_DUE:
            if self.grace_period_started_at is None:
                return AccessStatus.GRACE_PERIOD
            days = getattr(settings, "BILLING_GRACE_PERIOD_DAYS", 7)
            deadline = self.grace_period_started_at + timedelta(days=days)
            return AccessStatus.GRACE_PERIOD if timezone.now() < deadline else AccessStatus.SUSPENDED
        return AccessStatus.SUSPENDED  # PAUSED, CANCELED

    @property
    def grace_period_ends_at(self):
        """When the current grace window closes, or None outside one —
        display-only companion to access_status for the billing UI."""
        if self.status != SubscriptionStatus.PAST_DUE or self.grace_period_started_at is None:
            return None
        days = getattr(settings, "BILLING_GRACE_PERIOD_DAYS", 7)
        return self.grace_period_started_at + timedelta(days=days)


class BillingEventStatus(models.TextChoices):
    RECEIVED = "received", "Received"
    PROCESSED = "processed", "Processed"
    FAILED = "failed", "Failed"


class BillingEvent(UUIDModel, TimestampedModel):
    """Webhook delivery record — the idempotency key AND the audit/replay
    trail for billing state changes. Distinct from accounts.AuditLog (the
    general staff/security audit trail): this is provider-event bookkeeping.
    clinic is nullable — not every event (e.g. one for an unrecognized
    customer id) resolves to a clinic."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="billing_events",
    )
    paddle_event_id = models.CharField(max_length=64, unique=True)
    event_type = models.CharField(max_length=64)
    occurred_at = models.DateTimeField()
    notification_id = models.CharField(max_length=64, blank=True, default="")
    status = models.CharField(
        max_length=16,
        choices=BillingEventStatus.choices,
        default=BillingEventStatus.RECEIVED,
    )
    payload = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True, default="")
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "billing_events"
        indexes = [
            models.Index(fields=["clinic", "created_at"]),
            models.Index(fields=["event_type", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.event_type} {self.paddle_event_id[:12]} ({self.status})"
