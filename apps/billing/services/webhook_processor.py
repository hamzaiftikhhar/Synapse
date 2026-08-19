"""Paddle webhook verification + idempotent, order-safe state sync.

Paddle-Signature header format: `ts=<unix>;h1=<hex hmac-sha256>`. Signed
payload is `f"{ts}:{raw_body}"` over the *raw* bytes — this must run before
any JSON parsing/re-serialization, which is why the router passes
request.body untouched rather than a Ninja-parsed schema.

Idempotency: paddle_event_id is a unique DB column. Two concurrent
deliveries of the same event race on that constraint; the loser gets
IntegrityError and is treated as a no-op duplicate. A prior *failed*
delivery is retried (not skipped) so a transient error can heal itself on
Paddle's automatic redelivery.

Ordering: Paddle does not guarantee delivery order. Subscription.occurred_at
tracks the occurred_at of the last event actually applied; any event with an
occurred_at at or before that is discarded, never overwriting newer state.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from django.db import IntegrityError, transaction
from django.utils import timezone as dj_timezone

from apps.billing.models import (
    BillingEvent,
    BillingEventStatus,
    Plan,
    Subscription,
    SubscriptionStatus,
)

logger = logging.getLogger(__name__)

# Paddle's official SDKs apply a 5-second tolerance by default (per current
# developer.paddle.com/webhooks/signature-verification). Kept as a named
# constant, not inlined, so it's a one-line change if Paddle's own reference
# implementation turns out to use a different window in practice.
SIGNATURE_TIMESTAMP_TOLERANCE_SECONDS = 5

# Paddle's subscription.status values -> our own vocabulary (models.py).
# Decoupled so a wording change on Paddle's side doesn't ripple through
# every access check in the app.
_PADDLE_STATUS_MAP = {
    "trialing": SubscriptionStatus.TRIALING,
    "active": SubscriptionStatus.ACTIVE,
    "past_due": SubscriptionStatus.PAST_DUE,
    "paused": SubscriptionStatus.PAUSED,
    "canceled": SubscriptionStatus.CANCELED,
}


class SignatureError(Exception):
    """Missing, malformed, or invalid Paddle-Signature header."""


def verify_signature(raw_body: bytes, header_value: str | None, secret: str) -> None:
    if not secret:
        # Never silently accept unsigned webhooks just because the deploy
        # forgot to set the secret — fail loudly instead of pretending to
        # have verified something.
        raise SignatureError("Webhook secret is not configured")
    if not header_value:
        raise SignatureError("Missing Paddle-Signature header")

    parts: dict[str, str] = {}
    for chunk in header_value.split(";"):
        if "=" not in chunk:
            continue
        key, _, value = chunk.partition("=")
        parts[key.strip()] = value.strip()

    ts = parts.get("ts")
    h1 = parts.get("h1")
    if not ts or not h1:
        raise SignatureError("Malformed Paddle-Signature header")

    try:
        ts_int = int(ts)
    except ValueError as exc:
        raise SignatureError("Malformed Paddle-Signature timestamp") from exc

    if abs(time.time() - ts_int) > SIGNATURE_TIMESTAMP_TOLERANCE_SECONDS:
        raise SignatureError("Paddle-Signature timestamp outside tolerance")

    signed_payload = f"{ts}:".encode("utf-8") + raw_body
    expected = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, h1):
        raise SignatureError("Signature mismatch")


def _parse_occurred_at(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dj_timezone.is_naive(parsed):
        parsed = dj_timezone.make_aware(parsed, ZoneInfo("UTC"))
    return parsed


def _resolve_clinic_id(customer_id: str, data: dict[str, Any] | None = None) -> Any | None:
    sub = _find_subscription(data or {"customer_id": customer_id})
    return sub.clinic_id if sub else None


def _find_subscription(data: dict[str, Any]) -> Subscription | None:
    """Locate the local Subscription this Paddle event belongs to.

    Checkout always creates a local row first, but Paddle.js can mint a
    *new* customer at pay time (email change, overlay fallback). Matching
    only on paddle_customer_id then 200s the webhook and never flips
    status — which is why billing stayed on "No active plan".
    """
    customer_id = data.get("customer_id") or ""
    if customer_id:
        sub = Subscription.objects.filter(paddle_customer_id=customer_id).first()
        if sub is not None:
            return sub

    custom = data.get("custom_data") or {}
    clinic_id = custom.get("clinic_id") if isinstance(custom, dict) else None
    if clinic_id:
        sub = Subscription.objects.filter(clinic_id=clinic_id).first()
        if sub is not None:
            if customer_id and sub.paddle_customer_id != customer_id:
                sub.paddle_customer_id = customer_id
            return sub

    # Last resort: exactly one real incomplete checkout in flight.
    if customer_id:
        candidates = [
            s
            for s in Subscription.objects.filter(status=SubscriptionStatus.INCOMPLETE)
            if (s.paddle_customer_id or "").startswith("ctm_01")
        ]
        if len(candidates) == 1:
            sub = candidates[0]
            sub.paddle_customer_id = customer_id
            return sub
    return None


def _get_or_create_event(
    *,
    event_id: str,
    event_type: str,
    occurred_at: datetime,
    notification_id: str,
    payload: dict[str, Any],
    clinic_id: Any | None,
) -> tuple[BillingEvent, bool]:
    try:
        with transaction.atomic():
            event = BillingEvent.objects.create(
                paddle_event_id=event_id,
                event_type=event_type,
                occurred_at=occurred_at,
                notification_id=notification_id,
                payload=payload,
                clinic_id=clinic_id,
                status=BillingEventStatus.RECEIVED,
            )
        return event, True
    except IntegrityError:
        return BillingEvent.objects.get(paddle_event_id=event_id), False


def _resolve_plan(price_id: str) -> Plan | None:
    if not price_id:
        return None
    return Plan.objects.filter(paddle_price_id_sandbox=price_id).first() or Plan.objects.filter(
        paddle_price_id_live=price_id
    ).first()


# Paddle transaction events that get a customer-facing email. Deliberately
# narrow: transaction.completed (not also transaction.paid, which can fire
# for the same real payment — Paddle's own docs point to `completed` as the
# fulfillment-confirmation event) avoids double-notifying for one payment.
_TRANSACTION_EMAIL_SENDERS = {
    "transaction.completed": "send_payment_successful_email",
    "transaction.payment_failed": "send_payment_failed_email",
    "transaction.past_due": "send_payment_past_due_email",
}

# Structured-log event names (see the original request's observability
# list) — deliberately distinct from the email method names above, which
# describe the notification, not the log line.
_TRANSACTION_LOG_EVENTS = {
    "transaction.completed": "payment_succeeded",
    "transaction.payment_failed": "payment_failed",
    "transaction.past_due": "payment_past_due",
}


def _apply_transaction_event(
    data: dict[str, Any], event_type: str, *, send_email: bool
) -> Subscription | None:
    """Transaction events don't change Subscription state (subscription.*
    events already own that) — this only resolves which clinic a payment
    notification belongs to and sends it.

    `send_email` must be False when this event_id was already marked
    PROCESSED before this call (the "backfill a missing clinic_id on an
    already-processed event" retry path in process_webhook below) — unlike
    `_apply_subscription_event`, which has its own occurred_at staleness
    guard that already blocks a resend, this function has no state of its
    own to check against, so the caller must say so explicitly."""
    sub = _find_subscription(data)
    if sub is None:
        logger.warning(
            "Paddle webhook: no Subscription for transaction event customer_id=%s",
            data.get("customer_id") or "",
        )
        return None

    method_name = _TRANSACTION_EMAIL_SENDERS.get(event_type)
    if send_email:
        log_event = _TRANSACTION_LOG_EVENTS.get(event_type)
        if log_event:
            logger.info(
                "%s clinic=%s subscription=%s", log_event, sub.clinic_id, sub.id
            )
    if send_email and method_name and sub.clinic.email:
        from apps.notifications.service import NotificationService

        method = getattr(NotificationService, method_name)
        kwargs = {"to": sub.clinic.email, "clinic_name": sub.clinic.name}
        if method_name == "send_payment_successful_email":
            kwargs["plan_name"] = sub.plan.name
        method(**kwargs)
    return sub


def _send_status_transition_email(sub: Subscription, *, previous_status: str) -> None:
    """Only a genuine transition gets an email — re-applying the same
    status (a redundant subscription.updated, or two events landing in the
    same status) must not re-notify. `previous_status` is read before
    `sub.status` is mutated by the caller, so this only compares real
    before/after state, not the freshly-assigned value against itself.

    Also the one place that logs the billing lifecycle events from the
    original request's observability list (subscription_past_due,
    subscription_suspended, subscription_reactivated) — logged whenever the
    transition actually happens, even for a clinic with no email on file to
    notify (logging and notifying are separate concerns)."""
    if sub.status == previous_status:
        return

    if sub.status == SubscriptionStatus.PAST_DUE:
        logger.info("subscription_past_due clinic=%s subscription=%s", sub.clinic_id, sub.id)
    elif sub.status in {SubscriptionStatus.PAUSED, SubscriptionStatus.CANCELED}:
        logger.info(
            "subscription_suspended clinic=%s subscription=%s reason=%s",
            sub.clinic_id, sub.id, sub.status,
        )
    elif sub.status in {SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIALING} and previous_status in {
        SubscriptionStatus.PAST_DUE, SubscriptionStatus.PAUSED, SubscriptionStatus.CANCELED,
    }:
        logger.info(
            "subscription_reactivated clinic=%s subscription=%s from=%s",
            sub.clinic_id, sub.id, previous_status,
        )

    if not sub.clinic.email:
        return
    from apps.notifications.service import NotificationService

    if sub.status == SubscriptionStatus.PAUSED:
        NotificationService.send_subscription_paused_email(
            to=sub.clinic.email, clinic_name=sub.clinic.name
        )
    elif sub.status == SubscriptionStatus.CANCELED:
        NotificationService.send_subscription_canceled_email(
            to=sub.clinic.email, clinic_name=sub.clinic.name
        )
    elif sub.status == SubscriptionStatus.ACTIVE and previous_status == SubscriptionStatus.PAST_DUE:
        NotificationService.send_payment_recovered_email(
            to=sub.clinic.email, clinic_name=sub.clinic.name
        )
    elif (
        sub.status in {SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIALING}
        and previous_status == SubscriptionStatus.PAUSED
    ):
        # Distinct from "payment recovered" above — resuming a paused
        # subscription isn't a payment-failure story, it's "you're back".
        NotificationService.send_account_reactivated_email(
            to=sub.clinic.email, clinic_name=sub.clinic.name
        )


def _apply_subscription_event(data: dict[str, Any], occurred_at: datetime) -> Subscription | None:
    customer_id = data.get("customer_id") or ""
    sub = _find_subscription(data)
    if sub is None:
        # No local row for this customer — our checkout flow always creates
        # one before Paddle ever sees the customer, so this means the event
        # is for a customer we don't recognize. Nothing to attach it to.
        logger.warning("Paddle webhook: no Subscription for customer_id=%s", customer_id)
        return None

    if sub.occurred_at is not None and occurred_at <= sub.occurred_at:
        logger.info(
            "Paddle webhook: stale event for subscription %s (event=%s, current=%s) — skipped",
            sub.id,
            occurred_at,
            sub.occurred_at,
        )
        return

    previous_status = sub.status
    paddle_status = data.get("status") or ""
    if paddle_status in _PADDLE_STATUS_MAP:
        sub.status = _PADDLE_STATUS_MAP[paddle_status]

    # Grace-period timer: starts the instant a subscription first becomes
    # past_due, clears the instant it leaves that status (recovered or
    # canceled) — never reset by a redundant past_due redelivery, which
    # would otherwise keep extending someone's grace window indefinitely.
    if sub.status == SubscriptionStatus.PAST_DUE and previous_status != SubscriptionStatus.PAST_DUE:
        sub.grace_period_started_at = occurred_at
    elif sub.status != SubscriptionStatus.PAST_DUE and sub.grace_period_started_at is not None:
        sub.grace_period_started_at = None

    paddle_subscription_id = data.get("id")
    if paddle_subscription_id:
        sub.paddle_subscription_id = paddle_subscription_id

    period = data.get("current_billing_period") or {}
    if period.get("starts_at"):
        sub.current_period_start = _parse_occurred_at(period["starts_at"])
    if period.get("ends_at"):
        sub.current_period_end = _parse_occurred_at(period["ends_at"])

    scheduled = data.get("scheduled_change") or None
    sub.cancel_at_period_end = bool(scheduled and scheduled.get("action") == "cancel")

    if paddle_status == "canceled" and sub.canceled_at is None:
        sub.canceled_at = occurred_at

    items = data.get("items") or []
    if items:
        price_id = ((items[0] or {}).get("price") or {}).get("id", "")
        plan = _resolve_plan(price_id)
        if plan is not None:
            sub.plan = plan

    sub.occurred_at = occurred_at
    sub.save(
        update_fields=[
            "status",
            "paddle_customer_id",
            "paddle_subscription_id",
            "current_period_start",
            "current_period_end",
            "cancel_at_period_end",
            "canceled_at",
            "plan",
            "occurred_at",
            "grace_period_started_at",
            "updated_at",
        ]
    )

    _send_status_transition_email(sub, previous_status=previous_status)

    from apps.billing.services.activation import maybe_activate_clinic

    maybe_activate_clinic(sub)
    return sub


def process_webhook(*, raw_body: bytes, signature_header: str | None, secret: str) -> None:
    """Raises SignatureError (caller returns 401, no DB writes at all — the
    signature check happens before any database access) or lets processing
    exceptions propagate after recording BillingEvent.status = FAILED (caller
    returns non-200 so Paddle retries delivery)."""
    verify_signature(raw_body, signature_header, secret)

    try:
        body = json.loads(raw_body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise SignatureError("Malformed webhook body") from exc

    event_id = body.get("event_id") or ""
    event_type = body.get("event_type") or ""
    occurred_at_raw = body.get("occurred_at") or ""
    notification_id = body.get("notification_id") or ""
    data = body.get("data") or {}

    if not event_id or not event_type or not occurred_at_raw:
        raise SignatureError("Webhook body missing required fields")

    occurred_at = _parse_occurred_at(occurred_at_raw)
    clinic_id = (
        _resolve_clinic_id(data.get("customer_id") or "", data)
        if event_type.startswith(("subscription.", "transaction."))
        else None
    )

    event, created = _get_or_create_event(
        event_id=event_id,
        event_type=event_type,
        occurred_at=occurred_at,
        notification_id=notification_id,
        payload=body,
        clinic_id=clinic_id,
    )
    already_processed = not created and event.status == BillingEventStatus.PROCESSED
    if already_processed and event.clinic_id is not None:
        logger.info("Paddle webhook: duplicate of already-processed event %s — no-op", event_id)
        return

    try:
        with transaction.atomic():
            applied = None
            if event_type.startswith("subscription."):
                applied = _apply_subscription_event(data, occurred_at)
            elif event_type.startswith("transaction."):
                applied = _apply_transaction_event(
                    data, event_type, send_email=not already_processed
                )
            event.status = BillingEventStatus.PROCESSED
            event.processed_at = dj_timezone.now()
            event.error = ""
            update = ["status", "processed_at", "error"]
            if applied is not None and event.clinic_id is None:
                event.clinic_id = applied.clinic_id
                update.append("clinic_id")
            event.save(update_fields=update)
    except Exception as exc:  # noqa: BLE001 - must record failure then re-raise
        event.status = BillingEventStatus.FAILED
        event.error = str(exc)[:2000]
        event.save(update_fields=["status", "error"])
        logger.exception("Paddle webhook processing failed for event %s", event_id)
        raise
