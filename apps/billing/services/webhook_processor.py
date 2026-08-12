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


def _resolve_clinic_id(customer_id: str) -> Any | None:
    sub = Subscription.objects.filter(paddle_customer_id=customer_id).only("clinic_id").first()
    return sub.clinic_id if sub else None


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


def _apply_subscription_event(data: dict[str, Any], occurred_at: datetime) -> None:
    customer_id = data.get("customer_id") or ""
    sub = Subscription.objects.filter(paddle_customer_id=customer_id).first()
    if sub is None:
        # No local row for this customer — our checkout flow always creates
        # one before Paddle ever sees the customer, so this means the event
        # is for a customer we don't recognize. Nothing to attach it to.
        logger.warning("Paddle webhook: no Subscription for customer_id=%s", customer_id)
        return

    if sub.occurred_at is not None and occurred_at <= sub.occurred_at:
        logger.info(
            "Paddle webhook: stale event for subscription %s (event=%s, current=%s) — skipped",
            sub.id,
            occurred_at,
            sub.occurred_at,
        )
        return

    paddle_status = data.get("status") or ""
    if paddle_status in _PADDLE_STATUS_MAP:
        sub.status = _PADDLE_STATUS_MAP[paddle_status]

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
            "paddle_subscription_id",
            "current_period_start",
            "current_period_end",
            "cancel_at_period_end",
            "canceled_at",
            "plan",
            "occurred_at",
            "updated_at",
        ]
    )

    from apps.billing.services.activation import maybe_activate_clinic

    maybe_activate_clinic(sub)


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
    clinic_id = _resolve_clinic_id(data.get("customer_id") or "") if event_type.startswith(
        "subscription."
    ) else None

    event, created = _get_or_create_event(
        event_id=event_id,
        event_type=event_type,
        occurred_at=occurred_at,
        notification_id=notification_id,
        payload=body,
        clinic_id=clinic_id,
    )
    if not created and event.status == BillingEventStatus.PROCESSED:
        logger.info("Paddle webhook: duplicate of already-processed event %s — no-op", event_id)
        return

    try:
        with transaction.atomic():
            if event_type.startswith("subscription."):
                _apply_subscription_event(data, occurred_at)
            event.status = BillingEventStatus.PROCESSED
            event.processed_at = dj_timezone.now()
            event.error = ""
            event.save(update_fields=["status", "processed_at", "error"])
    except Exception as exc:  # noqa: BLE001 - must record failure then re-raise
        event.status = BillingEventStatus.FAILED
        event.error = str(exc)[:2000]
        event.save(update_fields=["status", "error"])
        logger.exception("Paddle webhook processing failed for event %s", event_id)
        raise
