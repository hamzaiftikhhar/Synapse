"""Billing/Paddle schemas."""

from datetime import datetime
from uuid import UUID

from ninja import Schema


class PlanOut(Schema):
    id: UUID
    slug: str
    name: str
    billing_interval: str
    display_price_cents: int | None = None
    display_currency: str = "USD"


class SubscriptionOut(Schema):
    status: str
    plan: PlanOut | None = None
    current_period_start: datetime | None = None
    current_period_end: datetime | None = None
    cancel_at_period_end: bool = False
    canceled_at: datetime | None = None
    has_access: bool = False


class CheckoutIn(Schema):
    plan_slug: str


class CheckoutOut(Schema):
    """Everything Paddle.js needs to open Checkout — price/customer are
    resolved server-side, never trusted from the client."""

    paddle_environment: str
    paddle_price_id: str
    paddle_customer_id: str
    clinic_id: str


class CancelSubscriptionIn(Schema):
    at_period_end: bool = True


class ChangePlanIn(Schema):
    plan_slug: str
