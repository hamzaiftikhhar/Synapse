"""OTP generation, storage, and verification — backend-owned; Twilio sends SMS only."""

from __future__ import annotations

import hashlib
import logging
import secrets
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from apps.chatbot.integrations import twilio_sms
from apps.chatbot.models import ChatSession, OTPVerification
from apps.clinics.models import Clinic
from apps.patients.models import Patient
from apps.patients.services import patient_service

logger = logging.getLogger(__name__)


class OTPError(Exception):
    """Base OTP flow error with HTTP status code."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


class OTPInvalidError(OTPError):
    def __init__(self, message: str = "Invalid or expired code") -> None:
        super().__init__(message, status_code=401)


class OTPRateLimitError(OTPError):
    def __init__(self, message: str = "Too many attempts") -> None:
        super().__init__(message, status_code=429)


@dataclass
class OTPSendResult:
    patient: Patient
    session: ChatSession
    session_token: str
    expires_in_minutes: int
    debug_code: str | None = None


@dataclass
class OTPVerifyResult:
    patient: Patient
    session: ChatSession | None


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _generate_code() -> str:
    length = settings.OTP_CODE_LENGTH
    return str(secrets.randbelow(10**length)).zfill(length)


def _get_or_create_session(
    *,
    clinic: Clinic,
    session_token: str | None,
) -> ChatSession:
    if session_token:
        try:
            return ChatSession.objects.get(clinic=clinic, session_token=session_token)
        except ChatSession.DoesNotExist:
            raise OTPError("Session not found", status_code=404) from None

    return ChatSession.objects.create(
        clinic=clinic,
        session_token=secrets.token_urlsafe(32),
    )


def send_otp(
    *,
    clinic: Clinic,
    phone: str,
    session_token: str | None = None,
    first_name: str = "",
    last_name: str = "",
) -> OTPSendResult:
    """
    1. Ensure Patient exists for clinic + phone
    2. Generate + store OTP
    3. Send SMS via Twilio (or dev fallback)
    """
    patient, _ = patient_service.get_or_create_by_phone(
        clinic=clinic,
        phone=phone,
        first_name=first_name,
        last_name=last_name,
    )
    session = _get_or_create_session(clinic=clinic, session_token=session_token)

    code = _generate_code()
    expires = timezone.now() + timedelta(minutes=settings.OTP_EXPIRE_MINUTES)

    OTPVerification.objects.create(
        clinic=clinic,
        session=session,
        patient=patient,
        phone=phone,
        code_hash=_hash_code(code),
        expires_at=expires,
    )

    debug_code: str | None = None
    sms_body = f"Your Synapse verification code is {code}"

    if twilio_sms.is_configured():
        try:
            twilio_sms.send_sms(to=phone, body=sms_body)
        except twilio_sms.TwilioSendError as exc:
            raise OTPError(str(exc), status_code=503) from exc
        if settings.DEBUG:
            debug_code = code
    else:
        logger.warning("Twilio not configured — OTP for %s (dev only)", phone)
        debug_code = code

    return OTPSendResult(
        patient=patient,
        session=session,
        session_token=session.session_token,
        expires_in_minutes=settings.OTP_EXPIRE_MINUTES,
        debug_code=debug_code,
    )


def verify_otp(
    *,
    clinic: Clinic,
    phone: str,
    code: str,
    session_token: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
) -> OTPVerifyResult:
    """
    Verify OTP and mark the existing Patient's phone as verified.

    Patient row must already exist (created at send or by staff).
    """
    session: ChatSession | None = None
    if session_token:
        try:
            session = ChatSession.objects.get(clinic=clinic, session_token=session_token)
        except ChatSession.DoesNotExist:
            raise OTPError("Session not found", status_code=404) from None

    otp_qs = OTPVerification.objects.filter(
        clinic=clinic,
        phone=phone,
        verified_at__isnull=True,
        expires_at__gt=timezone.now(),
    ).order_by("-created_at")

    if session is not None:
        otp_qs = otp_qs.filter(session=session)

    otp = otp_qs.first()
    if otp is None:
        raise OTPInvalidError()

    if otp.attempts >= otp.max_attempts:
        raise OTPRateLimitError()

    if otp.code_hash != _hash_code(code):
        otp.attempts += 1
        otp.save(update_fields=["attempts"])
        raise OTPInvalidError()

    otp.verified_at = timezone.now()
    otp.save(update_fields=["verified_at"])

    patient = patient_service.get_by_phone(clinic=clinic, phone=phone)
    if patient is None:
        raise OTPError("Patient not found — request a new code", status_code=404)

    if first_name or last_name:
        patient_service.update_profile(
            patient,
            first_name=first_name,
            last_name=last_name,
        )

    patient_service.mark_phone_verified(patient)

    if session is not None:
        session.patient = patient
        session.is_authenticated = True
        session.save(update_fields=["patient", "is_authenticated"])

    return OTPVerifyResult(patient=patient, session=session)
