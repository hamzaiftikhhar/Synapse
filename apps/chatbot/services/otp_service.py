"""OTP generation, storage, and verification — channel-aware (SMS / email)."""

from __future__ import annotations

import hashlib
import logging
import secrets
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from apps.chatbot.models import ChatSession, OTPVerification
from apps.clinics.features import get_feature_flags, get_verification_mode
from apps.clinics.models import Clinic
from apps.notifications.service import NotificationService
from apps.patients.models import Patient
from apps.patients.services import patient_service

logger = logging.getLogger(__name__)


class OTPError(Exception):
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
    channel: str = "sms"


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


def resolve_otp_channel(clinic: Clinic, requested: str | None = None) -> str:
    mode = get_verification_mode(clinic)
    flags = get_feature_flags(clinic)
    req = (requested or "").lower().strip()

    if mode == "none":
        raise OTPError("Verification is disabled for this clinic", status_code=400)

    if mode == "sms":
        # Unified contact field may collect email; honor it when email OTP is enabled
        if req == "email" and flags.get("email_otp", True):
            return "email"
        if not flags.get("sms_otp", True):
            raise OTPError("SMS verification is disabled", status_code=400)
        return "sms"
    if mode == "email":
        if req == "sms" and flags.get("sms_otp", True):
            return "sms"
        if not flags.get("email_otp", True):
            raise OTPError("Email verification is disabled", status_code=400)
        return "email"
    # sms_or_email — honor explicit request; otherwise prefer sms when available
    if req in {"sms", "email"}:
        if req == "sms" and not flags.get("sms_otp", True):
            raise OTPError("SMS verification is disabled", status_code=400)
        if req == "email" and not flags.get("email_otp", True):
            raise OTPError("Email verification is disabled", status_code=400)
        return req
    if flags.get("sms_otp", True):
        return "sms"
    if flags.get("email_otp", True):
        return "email"
    raise OTPError("No verification channel is enabled", status_code=400)


def send_otp(
    *,
    clinic: Clinic,
    phone: str = "",
    email: str = "",
    session_token: str | None = None,
    first_name: str = "",
    last_name: str = "",
    channel: str | None = None,
) -> OTPSendResult:
    """
    Ensure Patient exists, store OTP, deliver via SMS or email.
    """
    phone = (phone or "").strip()
    email = (email or "").strip().lower()

    # Prefer explicit channel; otherwise infer from which contact was provided.
    requested = (channel or "").lower().strip()
    if not requested:
        if email and not phone:
            requested = "email"
        elif phone and not email:
            requested = "sms"
        elif email and phone:
            requested = "sms"

    channel_resolved = resolve_otp_channel(clinic, requested or None)

    if channel_resolved == "sms" and not phone:
        raise OTPError("Phone is required for SMS verification")
    if channel_resolved == "email" and not email:
        raise OTPError("Email is required for email verification")

    if channel_resolved == "sms" and phone:
        patient, _ = patient_service.get_or_create_by_phone(
            clinic=clinic,
            phone=phone,
            first_name=first_name,
            last_name=last_name,
        )
        if email and not patient.email:
            patient.email = email
            patient.save(update_fields=["email", "updated_at"])
    else:
        # Email channel — look up / create by email
        patient = Patient.objects.filter(clinic=clinic, email=email).first()
        if patient is None:
            placeholder = f"email:{email}"[:20]
            patient, _ = patient_service.get_or_create_by_phone(
                clinic=clinic,
                phone=placeholder,
                first_name=first_name,
                last_name=last_name,
            )
            patient.email = email
            patient.save(update_fields=["email", "updated_at"])

    session = _get_or_create_session(clinic=clinic, session_token=session_token)
    code = _generate_code()
    expires = timezone.now() + timedelta(minutes=settings.OTP_EXPIRE_MINUTES)

    OTPVerification.objects.create(
        clinic=clinic,
        session=session,
        patient=patient,
        phone=phone or getattr(patient, "phone", ""),
        email=email or getattr(patient, "email", ""),
        channel=channel_resolved,
        code_hash=_hash_code(code),
        expires_at=expires,
    )

    debug_code: str | None = None
    if channel_resolved == "sms":
        try:
            NotificationService.send_patient_otp_sms(to=phone, code=code)
        except Exception as exc:
            logger.exception("SMS OTP failed")
            raise OTPError(str(exc), status_code=503) from exc
        debug_code = code if settings.DEBUG else None
        from apps.chatbot.integrations import twilio_sms

        if not twilio_sms.is_configured():
            debug_code = code
    else:
        try:
            NotificationService.send_patient_otp_email(
                to=email, code=code, clinic_name=clinic.name
            )
        except Exception as exc:
            logger.exception("Email OTP failed")
            # In development still return the code so booking can proceed
            if not settings.DEBUG:
                raise OTPError(str(exc), status_code=503) from exc
        debug_code = code if settings.DEBUG else None

    return OTPSendResult(
        patient=patient,
        session=session,
        session_token=session.session_token,
        expires_in_minutes=settings.OTP_EXPIRE_MINUTES,
        debug_code=debug_code,
        channel=channel_resolved,
    )


def verify_otp(
    *,
    clinic: Clinic,
    phone: str = "",
    email: str = "",
    code: str,
    session_token: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
) -> OTPVerifyResult:
    session: ChatSession | None = None
    if session_token:
        try:
            session = ChatSession.objects.get(clinic=clinic, session_token=session_token)
        except ChatSession.DoesNotExist:
            raise OTPError("Session not found", status_code=404) from None

    phone = (phone or "").strip()
    email = (email or "").strip().lower()

    otp_qs = OTPVerification.objects.filter(
        clinic=clinic,
        verified_at__isnull=True,
        expires_at__gt=timezone.now(),
    ).order_by("-created_at")

    if phone:
        otp_qs = otp_qs.filter(phone=phone)
    elif email:
        otp_qs = otp_qs.filter(email=email)
    else:
        raise OTPError("Phone or email is required")

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

    patient = otp.patient
    if patient is None and phone:
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
