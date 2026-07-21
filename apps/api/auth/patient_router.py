"""Patient widget authentication — phone + OTP → short-lived patient JWT.

Independent from staff auth. No username/password. No access to admin routes.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from ninja import Router
from ninja.errors import HttpError

from apps.api.auth.jwt import create_patient_access_token
from apps.api.auth.schemas import (
    ClinicOut,
    OTPSendIn,
    OTPSendOut,
    OTPVerifyIn,
    PatientAuthOut,
    PatientTokenOut,
)
from apps.chatbot.models import ChatSession, OTPVerification
from apps.clinics.models import Clinic, ClinicStatus
from apps.patients.models import Patient

logger = logging.getLogger(__name__)

router = Router(tags=["Auth — Patient (Widget)"])


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _generate_code() -> str:
    length = settings.OTP_CODE_LENGTH
    # Numeric OTP for SMS UX
    upper = 10**length
    return str(secrets.randbelow(upper)).zfill(length)


def _send_sms(phone: str, code: str) -> None:
    """Deliver OTP via Twilio when configured; otherwise log (dev)."""
    sid = settings.TWILIO_ACCOUNT_SID
    token = settings.TWILIO_AUTH_TOKEN
    from_number = settings.TWILIO_FROM_NUMBER

    if not (sid and token and from_number):
        logger.warning("Twilio not configured — OTP for %s is %s (dev only)", phone, code)
        return

    try:
        from twilio.rest import Client  # type: ignore[import-untyped]
    except ImportError as exc:
        raise HttpError(
            503,
            "Twilio SDK not installed. Add twilio to requirements or leave unset for dev.",
        ) from exc

    client = Client(sid, token)
    client.messages.create(
        body=f"Your Synapse verification code is {code}",
        from_=from_number,
        to=phone,
    )


def _clinic_out(clinic: Clinic) -> ClinicOut:
    return ClinicOut(
        id=clinic.id,
        slug=clinic.slug,
        name=clinic.name,
        timezone=clinic.timezone,
    )


def _resolve_clinic(slug: str) -> Clinic:
    try:
        clinic = Clinic.objects.get(slug=slug)
    except Clinic.DoesNotExist:
        raise HttpError(404, "Clinic not found") from None
    if clinic.status == ClinicStatus.SUSPENDED:
        raise HttpError(403, "Clinic is suspended")
    return clinic


def _resolve_session(clinic: Clinic, session_token: str | None) -> ChatSession | None:
    if not session_token:
        return None
    try:
        return ChatSession.objects.get(clinic=clinic, session_token=session_token)
    except ChatSession.DoesNotExist:
        raise HttpError(404, "Session not found") from None


@router.post("/otp/send", response=OTPSendOut, auth=None)
def send_otp(request, payload: OTPSendIn):
    """
    Send a one-time code to the patient's phone.

    Creates OTPVerification. Does not create a Django User.
    """
    clinic = _resolve_clinic(payload.clinic_slug)
    session = _resolve_session(clinic, payload.session_token)

    if session is None:
        # OTP rows require a session FK — create an ephemeral widget session
        session = ChatSession.objects.create(
            clinic=clinic,
            session_token=secrets.token_urlsafe(32),
        )

    code = _generate_code()
    expires = timezone.now() + timedelta(minutes=settings.OTP_EXPIRE_MINUTES)

    patient = Patient.objects.filter(clinic=clinic, phone=payload.phone).first()

    OTPVerification.objects.create(
        clinic=clinic,
        session=session,
        patient=patient,
        phone=payload.phone,
        code_hash=_hash_code(code),
        expires_at=expires,
    )

    _send_sms(payload.phone, code)

    twilio_configured = bool(
        settings.TWILIO_ACCOUNT_SID
        and settings.TWILIO_AUTH_TOKEN
        and settings.TWILIO_FROM_NUMBER
    )
    return OTPSendOut(
        message="Verification code sent",
        expires_in_minutes=settings.OTP_EXPIRE_MINUTES,
        debug_code=None if twilio_configured and not settings.DEBUG else code,
    )


@router.post("/otp/verify", response=PatientTokenOut, auth=None)
def verify_otp(request, payload: OTPVerifyIn):
    """
    Verify OTP and issue a short-lived patient JWT.

    Token type is patient_access — StaffJWTAuth will reject it.
    """
    clinic = _resolve_clinic(payload.clinic_slug)
    session = _resolve_session(clinic, payload.session_token)

    otp_qs = OTPVerification.objects.filter(
        clinic=clinic,
        phone=payload.phone,
        verified_at__isnull=True,
        expires_at__gt=timezone.now(),
    ).order_by("-created_at")

    if session is not None:
        otp_qs = otp_qs.filter(session=session)

    otp = otp_qs.first()
    if otp is None:
        raise HttpError(401, "Invalid or expired code")

    if otp.attempts >= otp.max_attempts:
        raise HttpError(429, "Too many attempts")

    if otp.code_hash != _hash_code(payload.code):
        otp.attempts += 1
        otp.save(update_fields=["attempts"])
        raise HttpError(401, "Invalid or expired code")

    otp.verified_at = timezone.now()
    otp.save(update_fields=["verified_at"])

    patient = Patient.objects.filter(clinic=clinic, phone=payload.phone).first()
    if patient is None:
        first = (payload.first_name or "").strip() or "Guest"
        last = (payload.last_name or "").strip() or "Patient"
        patient = Patient.objects.create(
            clinic=clinic,
            phone=payload.phone,
            first_name=first,
            last_name=last,
            is_verified=True,
        )
    else:
        patient.is_verified = True
        patient.save(update_fields=["is_verified", "updated_at"])

    if session is not None:
        session.patient = patient
        session.is_authenticated = True
        session.save(update_fields=["patient", "is_authenticated"])

    access = create_patient_access_token(
        patient_id=patient.id,
        clinic_id=clinic.id,
        session_id=session.id if session else None,
    )

    return PatientTokenOut(
        access_token=access,
        expires_in_minutes=settings.JWT_PATIENT_ACCESS_TOKEN_EXPIRE_MINUTES,
        patient=PatientAuthOut(
            id=patient.id,
            phone=patient.phone,
            first_name=patient.first_name,
            last_name=patient.last_name,
            is_verified=patient.is_verified,
        ),
        clinic=_clinic_out(clinic),
    )
