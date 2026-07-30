"""Widget booking wizard API — start / step / hold / confirm."""

from __future__ import annotations

import logging
import secrets

from django.utils import timezone
from ninja import Router, Schema
from ninja.errors import HttpError

from apps.chatbot.booking.service import BookingError, BookingService
from apps.chatbot.services.otp_service import OTPError, send_otp, verify_otp
from apps.clinics.models import Clinic, ClinicStatus

logger = logging.getLogger(__name__)

router = Router(tags=["Widget Booking"])


class BookingStartIn(Schema):
    clinic_slug: str
    session_token: str | None = None
    message: str = ""
    reason: str = ""
    specialty_id: str | None = None
    specialty_name: str | None = None
    doctor_id: str | None = None
    doctor_name: str | None = None


class BookingStepIn(Schema):
    clinic_slug: str
    session_token: str
    booking_id: str
    action: str
    value: dict = {}


class BookingHoldIn(Schema):
    clinic_slug: str
    session_token: str
    booking_id: str


class BookingConfirmIn(Schema):
    clinic_slug: str
    session_token: str
    booking_id: str
    otp_code: str


class BookingOtpSendIn(Schema):
    clinic_slug: str
    session_token: str
    booking_id: str


def _resolve_clinic(slug: str) -> Clinic:
    try:
        clinic = Clinic.objects.get(slug=slug)
    except Clinic.DoesNotExist:
        raise HttpError(404, "Clinic not found") from None
    if clinic.status == ClinicStatus.SUSPENDED:
        raise HttpError(403, "Clinic is suspended")
    return clinic


def _resolve_session(clinic: Clinic, session_token: str | None):
    from apps.chatbot.models import ChatSession, ChatSessionStatus

    if session_token:
        try:
            return ChatSession.objects.get(
                clinic=clinic,
                session_token=session_token,
                status=ChatSessionStatus.ACTIVE,
            )
        except ChatSession.DoesNotExist:
            pass

    return ChatSession.objects.create(
        clinic=clinic,
        session_token=secrets.token_urlsafe(32),
        ip_hash="",
        user_agent="",
        is_authenticated=False,
        status=ChatSessionStatus.ACTIVE,
        last_active_at=timezone.now(),
    )


def _wrap(payload: dict, session) -> dict:
    return {
        **payload,
        "session_token": session.session_token,
    }


@router.post("/booking/start", auth=None)
def booking_start(request, payload: BookingStartIn):
    clinic = _resolve_clinic(payload.clinic_slug)
    session = _resolve_session(clinic, payload.session_token)
    try:
        result = BookingService.start(
            clinic=clinic,
            chat_session=session,
            message=payload.message or "",
            reason=payload.reason or payload.message or "",
            specialty_id=payload.specialty_id,
            specialty_name=payload.specialty_name,
            doctor_id=payload.doctor_id,
            doctor_name=payload.doctor_name,
        )
    except BookingError as exc:
        raise HttpError(exc.status_code, str(exc)) from exc
    return _wrap(result, session)


@router.post("/booking/step", auth=None)
def booking_step(request, payload: BookingStepIn):
    clinic = _resolve_clinic(payload.clinic_slug)
    session = _resolve_session(clinic, payload.session_token)
    try:
        result = BookingService.apply_step(
            clinic=clinic,
            chat_session=session,
            booking_id=payload.booking_id,
            action=payload.action,
            value=payload.value or {},
        )
    except BookingError as exc:
        raise HttpError(exc.status_code, str(exc)) from exc
    return _wrap(result, session)


@router.post("/booking/hold", auth=None)
def booking_hold(request, payload: BookingHoldIn):
    clinic = _resolve_clinic(payload.clinic_slug)
    session = _resolve_session(clinic, payload.session_token)
    try:
        result = BookingService.hold_slot(
            clinic=clinic,
            chat_session=session,
            booking_id=payload.booking_id,
        )
    except BookingError as exc:
        raise HttpError(exc.status_code, str(exc)) from exc
    return _wrap(result, session)


@router.post("/booking/otp/send", auth=None)
def booking_otp_send(request, payload: BookingOtpSendIn):
    """Send OTP for the phone collected in the booking details step."""
    clinic = _resolve_clinic(payload.clinic_slug)
    session = _resolve_session(clinic, payload.session_token)
    booking = (session.conversation_context or {}).get("booking") or {}
    if booking.get("booking_id") != payload.booking_id:
        raise HttpError(404, "Booking session not found")
    phone = booking.get("patient_phone") or ""
    if not phone:
        raise HttpError(400, "Patient phone missing — submit details first")

    try:
        result = send_otp(
            clinic=clinic,
            phone=phone,
            session_token=session.session_token,
            first_name=booking.get("patient_first_name") or "",
            last_name=booking.get("patient_last_name") or "",
        )
    except OTPError as exc:
        raise HttpError(exc.status_code, str(exc)) from exc

    return {
        "message": "Verification code sent",
        "session_token": result.session_token,
        "booking_id": payload.booking_id,
        "expires_in_minutes": result.expires_in_minutes,
        "debug_code": result.debug_code,
        "phone": phone,
    }


@router.post("/booking/confirm", auth=None)
def booking_confirm(request, payload: BookingConfirmIn):
    """Verify OTP and create the appointment."""
    clinic = _resolve_clinic(payload.clinic_slug)
    session = _resolve_session(clinic, payload.session_token)
    booking = (session.conversation_context or {}).get("booking") or {}
    if booking.get("booking_id") != payload.booking_id:
        raise HttpError(404, "Booking session not found")

    phone = booking.get("patient_phone") or ""
    try:
        otp_result = verify_otp(
            clinic=clinic,
            phone=phone,
            code=payload.otp_code,
            session_token=session.session_token,
            first_name=booking.get("patient_first_name"),
            last_name=booking.get("patient_last_name"),
        )
    except OTPError as exc:
        raise HttpError(exc.status_code, str(exc)) from exc

    try:
        result = BookingService.confirm(
            clinic=clinic,
            chat_session=session,
            booking_id=payload.booking_id,
            patient=otp_result.patient,
            otp_verified=True,
        )
    except BookingError as exc:
        raise HttpError(exc.status_code, str(exc)) from exc

    return _wrap(result, session)
