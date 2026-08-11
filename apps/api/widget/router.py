"""Public widget endpoints — tenant config and guest chat (no patient JWT)."""

from __future__ import annotations

import logging
import secrets

from django.utils import timezone
from ninja import Router, Schema
from ninja.errors import HttpError

from apps.api.chat.router import _fallback_out, _to_out
from apps.api.chat.schemas import ChatMessageOut
from apps.chatbot.engine import ChatEngine
from apps.chatbot.marketing_engine import MarketingEngine
from apps.clinics.models import Clinic, ClinicStatus
from apps.widget.models import WidgetSettings

logger = logging.getLogger(__name__)

router = Router(tags=["Widget"])


class WidgetConfigOut(Schema):
    clinic_slug: str
    clinic_name: str
    phone: str
    configuration: dict


class WidgetChatIn(Schema):
    clinic_slug: str
    message: str
    session_token: str | None = None


class MarketingChatIn(Schema):
    message: str


class AppointmentActionIn(Schema):
    clinic_slug: str
    session_token: str
    appointment_id: str


class AppointmentsListIn(Schema):
    clinic_slug: str
    session_token: str


class AppointmentCardOut(Schema):
    id: str
    doctor: str
    doctor_id: str | None = None
    service: str = ""
    start_time: str
    end_time: str = ""
    status: str = ""
    confirmation_code: str = ""


class AppointmentsListOut(Schema):
    appointments: list[AppointmentCardOut]


class AppointmentCancelOut(Schema):
    detail: str
    appointment_id: str


class AppointmentRescheduleOut(Schema):
    detail: str
    appointment_id: str
    doctor_id: str
    doctor_name: str
    service_id: str | None = None
    service_name: str | None = None
    start_time: str
    end_time: str


def _resolve_clinic(slug: str) -> Clinic:
    try:
        clinic = Clinic.objects.get(slug=slug)
    except Clinic.DoesNotExist:
        raise HttpError(404, "Clinic not found") from None
    if clinic.status == ClinicStatus.SUSPENDED:
        raise HttpError(403, "Clinic is suspended")
    return clinic


@router.get("/config", response=WidgetConfigOut, auth=None)
def widget_config(request, clinic_slug: str):
    """Public widget configuration for tenant detection and branding."""
    from apps.clinics.features import (
        default_widget_configuration,
        get_feature_flags,
        get_verification_mode,
    )

    clinic = _resolve_clinic(clinic_slug)
    settings = WidgetSettings.objects.filter(clinic=clinic).first()
    configuration = (
        dict(settings.configuration)
        if settings and isinstance(settings.configuration, dict)
        else default_widget_configuration()
    )
    booking = dict(configuration.get("booking") or {})
    booking["verification_mode"] = get_verification_mode(clinic)
    booking["require_auth"] = booking["verification_mode"] != "none"
    configuration["booking"] = booking
    configuration["feature_flags"] = get_feature_flags(clinic)
    return WidgetConfigOut(
        clinic_slug=clinic.slug,
        clinic_name=clinic.name,
        phone=clinic.phone or "",
        configuration=configuration,
    )


@router.post("/chat/guest", response=ChatMessageOut, auth=None)
def guest_chat_message(request, payload: WidgetChatIn):
    """
    Anonymous patient chat — no OTP required for Q&A.

    OTP is only required when booking is confirmed (handled in booking wizard).
    """
    clinic = _resolve_clinic(payload.clinic_slug)
    message = (payload.message or "").strip()
    if not message:
        raise HttpError(422, "Message is required")
    if len(message) > 2000:
        raise HttpError(422, "Message too long")

    session = _resolve_guest_session(clinic, payload.session_token)
    patient = session.patient if session.is_authenticated else None

    try:
        result = ChatEngine().process(
            clinic=clinic,
            message=message,
            session=session,
            patient=patient,
        )
    except Exception as exc:
        logger.exception("Guest chat failed clinic=%s", clinic.id)
        out = _fallback_out()
        out.meta = {**out.meta, "session_token": session.session_token}
        return out

    out = _to_out(result)
    out.meta = {**out.meta, "session_token": session.session_token}
    return out


@router.post("/appointments/cancel", response=AppointmentCancelOut, auth=None)
def cancel_appointment(request, payload: AppointmentActionIn):
    """Cancel a patient's own appointment — requires an OTP-verified session."""
    from apps.appointments.models import Appointment, AppointmentStatus

    clinic = _resolve_clinic(payload.clinic_slug)
    session = _resolve_authenticated_session(clinic, payload.session_token)
    try:
        appt = Appointment.objects.get(
            id=payload.appointment_id, clinic=clinic, patient=session.patient
        )
    except (Appointment.DoesNotExist, ValueError):
        raise HttpError(404, "Appointment not found") from None

    appt.status = AppointmentStatus.CANCELLED
    appt.save(update_fields=["status", "updated_at"])
    return AppointmentCancelOut(detail="Appointment cancelled", appointment_id=str(appt.id))


@router.post("/appointments/reschedule", response=AppointmentRescheduleOut, auth=None)
def reschedule_appointment(request, payload: AppointmentActionIn):
    """
    Fetch reschedule context for a patient's own appointment — does NOT
    cancel it. The appointment stays live (and bookable as a fallback) for
    the entire time the patient is picking a new slot in the booking wizard;
    it's only cancelled atomically alongside the new appointment's creation,
    in BookingService.confirm (see `replaces_appointment_id`).
    """
    from apps.appointments.models import Appointment, AppointmentStatus

    clinic = _resolve_clinic(payload.clinic_slug)
    session = _resolve_authenticated_session(clinic, payload.session_token)
    try:
        appt = Appointment.objects.select_related("doctor", "service").get(
            id=payload.appointment_id,
            clinic=clinic,
            patient=session.patient,
            status__in=[AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED],
        )
    except (Appointment.DoesNotExist, ValueError):
        raise HttpError(404, "Appointment not found") from None

    return AppointmentRescheduleOut(
        detail="ok",
        appointment_id=str(appt.id),
        doctor_id=str(appt.doctor_id),
        doctor_name=appt.doctor.full_name,
        service_id=str(appt.service_id) if appt.service_id else None,
        service_name=appt.service.name if appt.service else None,
        start_time=appt.start_time.isoformat(),
        end_time=appt.end_time.isoformat(),
    )


@router.post("/appointments/list", response=AppointmentsListOut, auth=None)
def list_appointments(request, payload: AppointmentsListIn):
    """
    A patient's own upcoming appointments for an OTP-verified session.

    Used right after identity verification to render appointment cards as a
    direct state transition — not a new chat turn, no re-classification.
    """
    from apps.appointments.models import Appointment, AppointmentStatus

    clinic = _resolve_clinic(payload.clinic_slug)
    session = _resolve_authenticated_session(clinic, payload.session_token)

    upcoming = (
        Appointment.objects.filter(
            clinic=clinic,
            patient=session.patient,
            start_time__gte=timezone.now(),
            status__in=[AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED],
        )
        .select_related("doctor", "service")
        .order_by("start_time")[:10]
    )

    return AppointmentsListOut(
        appointments=[
            AppointmentCardOut(
                id=str(a.id),
                doctor=a.doctor.full_name,
                doctor_id=str(a.doctor_id),
                service=a.service.name if a.service else "",
                start_time=a.start_time.isoformat(),
                end_time=a.end_time.isoformat(),
                status=a.status,
                confirmation_code=a.confirmation_code,
            )
            for a in upcoming
        ]
    )


@router.post("/chat/marketing", response=ChatMessageOut, auth=None)
def marketing_chat_message(request, payload: MarketingChatIn):
    """Synapse marketing assistant — never exposes clinic tenant data."""
    message = (payload.message or "").strip()
    if not message:
        raise HttpError(422, "Message is required")

    result = MarketingEngine().process(message=message)
    return _to_out(result)


def _resolve_guest_session(clinic: Clinic, session_token: str | None):
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

    token = secrets.token_urlsafe(32)
    return ChatSession.objects.create(
        clinic=clinic,
        session_token=token,
        ip_hash="",
        user_agent="",
        is_authenticated=False,
        status=ChatSessionStatus.ACTIVE,
        last_active_at=timezone.now(),
    )


def _resolve_authenticated_session(clinic: Clinic, session_token: str):
    """A chat session that has already completed OTP verification
    (apps/api/auth/patient_router.py's /otp/verify sets session.patient +
    is_authenticated when given this same session_token)."""
    from apps.chatbot.models import ChatSession, ChatSessionStatus

    try:
        session = ChatSession.objects.get(
            clinic=clinic,
            session_token=session_token,
            status=ChatSessionStatus.ACTIVE,
        )
    except ChatSession.DoesNotExist:
        raise HttpError(404, "Session not found") from None
    if not session.is_authenticated or session.patient_id is None:
        raise HttpError(401, "Verification required")
    return session
