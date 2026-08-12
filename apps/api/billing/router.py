"""Clinic-owner SaaS billing — Paddle Checkout + webhook synchronization.

Ownership/tenant resolution reuses the existing staff JWT architecture
(clinic_from(request)) exactly like every other clinic-scoped router — no
parallel tenant resolution, no client-supplied clinic_id.

Subscription STATE is only ever written by a verified webhook
(services/webhook_processor.py). The mutating endpoints here (checkout,
cancel, change-plan) call Paddle and return immediately; they never flip
Subscription.status themselves.
"""

from __future__ import annotations

import logging

from django.http import HttpRequest, HttpResponse
from ninja import Router
from ninja.errors import HttpError

from apps.accounts.models import AuditAction
from apps.accounts.services.audit import write_audit
from apps.api.auth.deps import clinic_from, client_ip, jwt_auth
from apps.api.billing.schemas import (
    CancelSubscriptionIn,
    ChangePlanIn,
    CheckoutIn,
    CheckoutOut,
    PlanOut,
    SubscriptionOut,
)
from apps.billing.models import Plan, Subscription, SubscriptionStatus
from apps.billing.services import paddle_client
from apps.billing.services.webhook_processor import SignatureError, process_webhook
from django.conf import settings

logger = logging.getLogger(__name__)

router = Router(tags=["Billing"])


def _require_owner(request: HttpRequest) -> None:
    user = request.auth.user  # type: ignore[attr-defined]
    if not getattr(user, "is_clinic_owner", False):
        raise HttpError(403, "Only the clinic owner can manage billing")


def _plan_out(plan: Plan) -> PlanOut:
    return PlanOut(
        id=plan.id,
        slug=plan.slug,
        name=plan.name,
        billing_interval=plan.billing_interval,
        display_price_cents=plan.display_price_cents,
        display_currency=plan.display_currency,
    )


def _subscription_out(sub: Subscription | None) -> SubscriptionOut:
    if sub is None:
        return SubscriptionOut(status=SubscriptionStatus.INCOMPLETE, has_access=False)
    return SubscriptionOut(
        status=sub.status,
        plan=_plan_out(sub.plan) if sub.plan_id else None,
        current_period_start=sub.current_period_start,
        current_period_end=sub.current_period_end,
        cancel_at_period_end=sub.cancel_at_period_end,
        canceled_at=sub.canceled_at,
        has_access=sub.has_access,
    )


@router.get("/plans", response=list[PlanOut], auth=jwt_auth)
def list_plans(request):
    return [_plan_out(p) for p in Plan.objects.filter(is_active=True)]


@router.get("/subscription", response=SubscriptionOut, auth=jwt_auth)
def get_subscription(request):
    clinic = clinic_from(request)
    sub = Subscription.objects.select_related("plan").filter(clinic=clinic).first()
    return _subscription_out(sub)


@router.post("/checkout", response=CheckoutOut, auth=jwt_auth)
def create_checkout(request, payload: CheckoutIn):
    clinic = clinic_from(request)
    _require_owner(request)

    if not paddle_client.is_configured():
        raise HttpError(503, "Billing is not configured")

    plan = Plan.objects.filter(slug=payload.plan_slug, is_active=True).first()
    if plan is None:
        raise HttpError(404, "Plan not found")

    price_id = plan.paddle_price_id(settings.PADDLE_ENVIRONMENT)
    if not price_id:
        raise HttpError(400, f"Plan is not configured for {settings.PADDLE_ENVIRONMENT}")

    sub, _ = Subscription.objects.get_or_create(clinic=clinic, defaults={"plan": plan})
    if sub.plan_id != plan.id and sub.status == SubscriptionStatus.INCOMPLETE:
        # Only overwrite the "intent" plan before Paddle has confirmed
        # anything — once a real subscription exists, plan changes go
        # through change-plan, not another checkout.
        sub.plan = plan
        sub.save(update_fields=["plan", "updated_at"])

    if not sub.paddle_customer_id:
        try:
            customer_id = paddle_client.create_customer(
                email=clinic.email, name=clinic.name, clinic_id=str(clinic.id)
            )
        except paddle_client.PaddleAPIError as exc:
            raise HttpError(502, "Could not reach Paddle") from exc
        sub.paddle_customer_id = customer_id
        sub.save(update_fields=["paddle_customer_id", "updated_at"])

    write_audit(
        action=AuditAction.SUBSCRIPTION_CHECKOUT_STARTED,
        actor=request.auth.user,  # type: ignore[attr-defined]
        clinic=clinic,
        object_type="plan",
        object_id=str(plan.id),
        ip_address=client_ip(request),
    )

    return CheckoutOut(
        paddle_environment=settings.PADDLE_ENVIRONMENT,
        paddle_price_id=price_id,
        paddle_customer_id=sub.paddle_customer_id,
    )


@router.post("/subscription/cancel", response=SubscriptionOut, auth=jwt_auth)
def cancel_subscription(request, payload: CancelSubscriptionIn):
    clinic = clinic_from(request)
    _require_owner(request)

    sub = Subscription.objects.select_related("plan").filter(clinic=clinic).first()
    if sub is None or not sub.paddle_subscription_id:
        raise HttpError(400, "No active subscription")

    if not paddle_client.is_configured():
        raise HttpError(503, "Billing is not configured")

    try:
        paddle_client.cancel_subscription(
            sub.paddle_subscription_id, at_period_end=payload.at_period_end
        )
    except paddle_client.PaddleAPIError as exc:
        raise HttpError(502, "Could not reach Paddle") from exc

    write_audit(
        action=AuditAction.SUBSCRIPTION_CANCEL_REQUESTED,
        actor=request.auth.user,  # type: ignore[attr-defined]
        clinic=clinic,
        object_type="subscription",
        object_id=str(sub.id),
        metadata={"at_period_end": payload.at_period_end},
        ip_address=client_ip(request),
    )

    # Local state is NOT mutated here — Paddle's webhook is authoritative.
    return _subscription_out(sub)


@router.post("/subscription/change-plan", response=SubscriptionOut, auth=jwt_auth)
def change_plan(request, payload: ChangePlanIn):
    clinic = clinic_from(request)
    _require_owner(request)

    sub = Subscription.objects.select_related("plan").filter(clinic=clinic).first()
    if sub is None or not sub.paddle_subscription_id:
        raise HttpError(400, "No active subscription")

    new_plan = Plan.objects.filter(slug=payload.plan_slug, is_active=True).first()
    if new_plan is None:
        raise HttpError(404, "Plan not found")

    price_id = new_plan.paddle_price_id(settings.PADDLE_ENVIRONMENT)
    if not price_id:
        raise HttpError(400, f"Plan is not configured for {settings.PADDLE_ENVIRONMENT}")

    if not paddle_client.is_configured():
        raise HttpError(503, "Billing is not configured")

    try:
        paddle_client.change_subscription_price(sub.paddle_subscription_id, price_id=price_id)
    except paddle_client.PaddleAPIError as exc:
        raise HttpError(502, "Could not reach Paddle") from exc

    write_audit(
        action=AuditAction.SUBSCRIPTION_CHANGE_REQUESTED,
        actor=request.auth.user,  # type: ignore[attr-defined]
        clinic=clinic,
        object_type="plan",
        object_id=str(new_plan.id),
        ip_address=client_ip(request),
    )

    # Local plan is NOT mutated here — Paddle's webhook is authoritative.
    return _subscription_out(sub)


@router.post("/paddle/webhook", auth=None)
def paddle_webhook(request: HttpRequest) -> HttpResponse:
    """Public — Paddle can't send our JWT. The signature IS the auth.

    Reads request.body directly (raw, untouched bytes) rather than a Ninja
    Schema, since signature verification must run over the exact bytes
    Paddle signed — any JSON parse/re-serialize first would break it.
    """
    signature = request.headers.get("Paddle-Signature")
    try:
        process_webhook(
            raw_body=request.body,
            signature_header=signature,
            secret=settings.PADDLE_WEBHOOK_SECRET,
        )
    except SignatureError as exc:
        logger.warning("Paddle webhook rejected: %s", exc)
        return HttpResponse(status=401)
    except Exception:
        logger.exception("Paddle webhook processing raised")
        return HttpResponse(status=500)
    return HttpResponse(status=200)
