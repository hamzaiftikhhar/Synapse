"""Patient widget authentication — thin router over otp_service."""

from django.conf import settings
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
from apps.chatbot.services.otp_service import OTPError, send_otp, verify_otp
from apps.clinics.models import Clinic, ClinicStatus

router = Router(tags=["Auth — Patient (Widget)"])


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


def _patient_out(patient) -> PatientAuthOut:
    return PatientAuthOut(
        id=patient.id,
        phone=patient.phone,
        first_name=patient.first_name,
        last_name=patient.last_name,
        is_verified=patient.is_verified,
        verified_at=patient.verified_at,
    )


@router.post("/otp/send", response=OTPSendOut, auth=None)
def send_otp(request, payload: OTPSendIn):
    """
    Send OTP to verify a patient's phone.

    Ensures a Patient profile exists first; OTP only verifies the phone on that record.
    """
    clinic = _resolve_clinic(payload.clinic_slug)
    try:
        result = send_otp(
            clinic=clinic,
            phone=payload.phone,
            session_token=payload.session_token,
            first_name=payload.first_name or "",
            last_name=payload.last_name or "",
        )
    except OTPError as exc:
        raise HttpError(exc.status_code, str(exc)) from exc

    return OTPSendOut(
        message="Verification code sent",
        session_token=result.session_token,
        patient_id=result.patient.id,
        expires_in_minutes=result.expires_in_minutes,
        debug_code=result.debug_code,
    )


@router.post("/otp/verify", response=PatientTokenOut, auth=None)
def verify_otp(request, payload: OTPVerifyIn):
    """Verify OTP and issue a short-lived patient JWT."""
    clinic = _resolve_clinic(payload.clinic_slug)
    try:
        result = verify_otp(
            clinic=clinic,
            phone=payload.phone,
            code=payload.code,
            session_token=payload.session_token,
            first_name=payload.first_name,
            last_name=payload.last_name,
        )
    except OTPError as exc:
        raise HttpError(exc.status_code, str(exc)) from exc

    access = create_patient_access_token(
        patient_id=result.patient.id,
        clinic_id=clinic.id,
        session_id=result.session.id if result.session else None,
    )

    return PatientTokenOut(
        access_token=access,
        expires_in_minutes=settings.JWT_PATIENT_ACCESS_TOKEN_EXPIRE_MINUTES,
        patient=_patient_out(result.patient),
        clinic=_clinic_out(clinic),
    )
