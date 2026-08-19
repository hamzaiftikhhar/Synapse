"""Verification API — the only HTTP surface for apps.verification.

Staff-authenticated: today's use case is an already-logged-in user
confirming their own phone number (Part 6's "optional phone verification"
step, which in this codebase happens after `accept-invite` already issues a
JWT). Nothing here imports Twilio, a provider class, or `settings.OTP_
PROVIDER` — only `VerificationService`.
"""

from __future__ import annotations

from django.utils import timezone
from ninja import Router

from apps.accounts.models import AuditAction
from apps.accounts.services.audit import write_audit
from apps.api.auth.deps import client_ip, staff_jwt_auth
from apps.api.verification.schemas import (
    VerificationCheckIn,
    VerificationOutcomeOut,
    VerificationSendIn,
)
from apps.verification.outcomes import VerificationStatus
from apps.verification.service import VerificationService
from core.ratelimit import check_rate_limit

router = Router(tags=["Verification"])

_SEND_MAX_PER_RECIPIENT, _SEND_RECIPIENT_WINDOW_S = 5, 600
_SEND_MAX_PER_IP, _SEND_IP_WINDOW_S = 20, 600
_CHECK_MAX_PER_IP, _CHECK_IP_WINDOW_S = 30, 600


def _throttle_send(request, to: str) -> None:
    check_rate_limit(
        "verify_send_ip", client_ip(request) or "",
        limit=_SEND_MAX_PER_IP, window_seconds=_SEND_IP_WINDOW_S,
    )
    check_rate_limit(
        "verify_send_to", to,
        limit=_SEND_MAX_PER_RECIPIENT, window_seconds=_SEND_RECIPIENT_WINDOW_S,
    )


def _out(outcome) -> VerificationOutcomeOut:
    return VerificationOutcomeOut(
        status=outcome.status.value,
        valid=outcome.valid,
        message=outcome.message,
        dev_code=outcome.dev_code,
    )


@router.post("/send", response=VerificationOutcomeOut, auth=staff_jwt_auth)
def send(request, payload: VerificationSendIn):
    _throttle_send(request, payload.to)
    outcome = VerificationService().send_verification(to=payload.to, channel=payload.channel)
    write_audit(
        action=AuditAction.PHONE_VERIFY_REQUESTED,
        actor=request.auth.user,
        clinic=request.auth.clinic,
        metadata={"channel": payload.channel, "status": outcome.status.value},
        ip_address=client_ip(request),
    )
    return _out(outcome)


@router.post("/resend", response=VerificationOutcomeOut, auth=staff_jwt_auth)
def resend(request, payload: VerificationSendIn):
    _throttle_send(request, payload.to)
    outcome = VerificationService().resend_verification(to=payload.to, channel=payload.channel)
    write_audit(
        action=AuditAction.PHONE_VERIFY_REQUESTED,
        actor=request.auth.user,
        clinic=request.auth.clinic,
        metadata={"channel": payload.channel, "status": outcome.status.value, "resend": True},
        ip_address=client_ip(request),
    )
    return _out(outcome)


@router.post("/check", response=VerificationOutcomeOut, auth=staff_jwt_auth)
def check(request, payload: VerificationCheckIn):
    check_rate_limit(
        "verify_check_ip", client_ip(request) or "",
        limit=_CHECK_MAX_PER_IP, window_seconds=_CHECK_IP_WINDOW_S,
    )
    outcome = VerificationService().check_verification(to=payload.to, code=payload.code)
    user = request.auth.user

    if outcome.status is VerificationStatus.APPROVED:
        if user.phone_number == payload.to:
            user.phone_verified_at = timezone.now()
            user.save(update_fields=["phone_verified_at"])
        write_audit(
            action=AuditAction.PHONE_VERIFY_APPROVED,
            actor=user,
            clinic=request.auth.clinic,
            metadata={"self_phone": user.phone_number == payload.to},
            ip_address=client_ip(request),
        )
    elif outcome.status is not VerificationStatus.PENDING:
        # PENDING covers "wrong code, attempts remain" — too routine per
        # keystroke to audit. Expired / max-attempts / not-found / failed
        # are all worth a record.
        write_audit(
            action=AuditAction.PHONE_VERIFY_FAILED,
            actor=user,
            clinic=request.auth.clinic,
            metadata={"status": outcome.status.value},
            ip_address=client_ip(request),
        )
    return _out(outcome)
