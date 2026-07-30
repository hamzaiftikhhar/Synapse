"""Booking wizard service — start, step, hold, confirm."""

from __future__ import annotations

import logging
import secrets
import string
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.chatbot.booking.config import get_booking_config
from apps.chatbot.booking.discovery import suggest_specialties
from apps.chatbot.booking.modes import first_step, next_step, prev_step
from apps.chatbot.booking.serializers import serialize_step
from apps.chatbot.booking.state import BookingSession, BookingStep

logger = logging.getLogger(__name__)


class BookingError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


class BookingService:
    """Orchestrates the clinic booking wizard."""

    @classmethod
    def start(
        cls,
        *,
        clinic: Any,
        chat_session: Any,
        message: str = "",
        reason: str = "",
        specialty_id: str | None = None,
        specialty_name: str | None = None,
        doctor_id: str | None = None,
        doctor_name: str | None = None,
    ) -> dict[str, Any]:
        cfg = get_booking_config(clinic)
        text = (reason or message or "").strip()

        suggested, guidance = ([], "")
        if cfg.get("ai_discovery"):
            suggested, guidance = suggest_specialties(clinic, message=text, reason=text)

        session = BookingSession.create(
            clinic_id=str(clinic.id),
            mode=cfg["mode"],
            reason=text,
        )
        session.suggested_specialty_ids = [s["id"] for s in suggested]

        # Prefill from conversation
        if specialty_id:
            session.specialty_id = str(specialty_id)
            session.specialty_name = specialty_name or cls._specialty_name(
                clinic, str(specialty_id)
            )
        if doctor_id:
            session.doctor_id = str(doctor_id)
            session.doctor_name = doctor_name or cls._doctor_name(clinic, str(doctor_id))

        # Skip ahead when context is known
        if session.doctor_id:
            session.step = BookingStep.DATE.value
        elif session.specialty_id:
            session.step = BookingStep.DOCTOR.value
        else:
            session.step = first_step(cfg["mode"]).value
            if cfg["mode"] == "first_available" and not suggested:
                session.step = BookingStep.DATE.value

        cls._save(chat_session, session)
        payload = serialize_step(clinic, session)
        payload["guidance"] = guidance
        payload["suggested_specialties"] = suggested
        return payload

    @classmethod
    def apply_step(
        cls,
        *,
        clinic: Any,
        chat_session: Any,
        booking_id: str,
        action: str,
        value: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        session = cls._load(chat_session, booking_id)
        value = value or {}
        action = (action or "").strip().lower()

        if action == "back":
            prev = prev_step(session.mode, session.step)
            if prev:
                session.step = prev.value
                if prev == BookingStep.TIME:
                    session.show_all_times = False
            cls._touch(session)
            cls._save(chat_session, session)
            return serialize_step(clinic, session)

        if action == "clear_specialty":
            session.specialty_id = None
            session.specialty_name = None
            if session.step == BookingStep.DOCTOR.value:
                pass  # refresh doctors unfiltered
            elif session.step not in (
                BookingStep.SPECIALTY.value,
                BookingStep.DOCTOR.value,
            ):
                # Jump back to doctor/specialty for reselection
                session.step = (
                    BookingStep.DOCTOR.value
                    if session.mode == "choose_doctor"
                    else BookingStep.SPECIALTY.value
                )
            cls._touch(session)
            cls._save(chat_session, session)
            return serialize_step(clinic, session)

        if action == "more_times":
            session.show_all_times = True
            cls._touch(session)
            cls._save(chat_session, session)
            return serialize_step(clinic, session)

        if action == "select_specialty":
            sid = str(value.get("id") or "")
            name = str(value.get("name") or "")
            if not sid:
                raise BookingError("Specialty id is required")
            session.specialty_id = sid
            session.specialty_name = name or cls._specialty_name(clinic, sid)
            session.doctor_id = None
            session.doctor_name = None
            session.date = None
            session.slot_start = None
            session.slot_end = None
            nxt = next_step(session.mode, session.step)
            # From specialty always go to next in mode
            if session.step == BookingStep.SPECIALTY.value and nxt:
                session.step = nxt.value
            elif session.mode == "first_available":
                session.step = BookingStep.DATE.value
            else:
                session.step = BookingStep.DOCTOR.value
            cls._touch(session)
            cls._save(chat_session, session)
            return serialize_step(clinic, session)

        if action == "select_doctor":
            did = str(value.get("id") or "")
            if not did:
                raise BookingError("Doctor id is required")
            session.doctor_id = did
            session.doctor_name = str(value.get("name") or "") or cls._doctor_name(
                clinic, did
            )
            session.date = None
            session.slot_start = None
            session.slot_end = None
            session.show_all_times = False
            nxt = next_step(session.mode, BookingStep.DOCTOR.value)
            session.step = nxt.value if nxt else BookingStep.DATE.value
            cls._touch(session)
            cls._save(chat_session, session)
            return serialize_step(clinic, session)

        if action == "select_date":
            d = str(value.get("date") or "")
            if not d:
                raise BookingError("Date is required")
            session.date = d
            session.slot_start = None
            session.slot_end = None
            session.show_all_times = False
            # General / first_available may not have doctor yet — slots will pick one
            session.step = BookingStep.TIME.value
            cls._touch(session)
            cls._save(chat_session, session)
            return serialize_step(clinic, session)

        if action == "select_time":
            start = str(value.get("start") or "")
            end = str(value.get("end") or "")
            doctor_id = str(value.get("doctor_id") or session.doctor_id or "")
            doctor_name = str(value.get("doctor") or value.get("doctor_name") or "")
            if not start or not end or not doctor_id:
                raise BookingError("Slot start, end, and doctor_id are required")
            session.slot_start = start
            session.slot_end = end
            session.doctor_id = doctor_id
            session.doctor_name = doctor_name or cls._doctor_name(clinic, doctor_id)
            # Hold immediately when selecting time (before details)
            cls._hold_internal(session, clinic)
            session.step = BookingStep.DETAILS.value
            cls._touch(session)
            cls._save(chat_session, session)
            return serialize_step(clinic, session)

        if action == "submit_details":
            first = str(value.get("first_name") or "").strip()
            last = str(value.get("last_name") or "").strip()
            phone = str(value.get("phone") or "").strip()
            if not first or not phone:
                raise BookingError("First name and phone are required")
            if not session.slot_start or not session.doctor_id:
                raise BookingError("Select a time slot first")
            # Ensure hold still valid
            cls._ensure_hold(session)
            session.patient_first_name = first
            session.patient_last_name = last
            session.patient_phone = phone
            session.step = BookingStep.OTP.value
            cls._touch(session)
            cls._save(chat_session, session)
            return serialize_step(clinic, session)

        raise BookingError(f"Unknown action: {action}")

    @classmethod
    def hold_slot(
        cls,
        *,
        clinic: Any,
        chat_session: Any,
        booking_id: str,
    ) -> dict[str, Any]:
        session = cls._load(chat_session, booking_id)
        if not session.slot_start or not session.doctor_id:
            raise BookingError("No slot selected")
        cls._hold_internal(session, clinic)
        cls._save(chat_session, session)
        payload = serialize_step(clinic, session)
        payload["hold"] = {"expires_at": session.hold_expires_at}
        return payload

    @classmethod
    @transaction.atomic
    def confirm(
        cls,
        *,
        clinic: Any,
        chat_session: Any,
        booking_id: str,
        patient: Any | None = None,
        otp_verified: bool = False,
    ) -> dict[str, Any]:
        from apps.appointments.models import Appointment, AppointmentSource, AppointmentStatus
        from apps.doctors.models import Doctor
        from apps.patients.models import Patient

        session = cls._load(chat_session, booking_id)
        cfg = get_booking_config(clinic)

        if cfg.get("require_auth") and not otp_verified and patient is None:
            raise BookingError("OTP verification required", status_code=401)

        cls._ensure_hold(session)

        if patient is None:
            # Get or create patient from booking details
            patient, _ = Patient.objects.get_or_create(
                clinic=clinic,
                phone=session.patient_phone,
                defaults={
                    "first_name": session.patient_first_name,
                    "last_name": session.patient_last_name,
                },
            )
            if not patient.first_name and session.patient_first_name:
                patient.first_name = session.patient_first_name
                patient.last_name = session.patient_last_name
                patient.save(update_fields=["first_name", "last_name"])

        session.patient_id = str(patient.id)

        try:
            doctor = Doctor.objects.get(
                clinic=clinic, id=session.doctor_id, is_deleted=False
            )
        except Doctor.DoesNotExist as exc:
            raise BookingError("Doctor not found") from exc

        start = datetime.fromisoformat(session.slot_start.replace("Z", "+00:00"))
        end = datetime.fromisoformat(session.slot_end.replace("Z", "+00:00"))
        if timezone.is_naive(start):
            start = timezone.make_aware(start, ZoneInfo("UTC"))
        if timezone.is_naive(end):
            end = timezone.make_aware(end, ZoneInfo("UTC"))

        # Collision check
        conflict = Appointment.objects.filter(
            clinic=clinic,
            doctor=doctor,
            start_time=start,
            status__in=[AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED],
        ).exists()
        if conflict:
            raise BookingError(
                "That time slot is no longer available. Please choose another time.",
                status_code=409,
            )

        code = _confirmation_code()
        try:
            appt = Appointment.objects.create(
                clinic=clinic,
                doctor=doctor,
                patient=patient,
                start_time=start,
                end_time=end,
                status=AppointmentStatus.CONFIRMED,
                confirmation_code=code,
                notes=session.reason[:500] if session.reason else "",
                source=AppointmentSource.CHATBOT,
            )
        except IntegrityError as exc:
            raise BookingError(
                "Could not create appointment — slot may have been taken.",
                status_code=409,
            ) from exc

        session.confirmation_code = code
        session.appointment_id = str(appt.id)
        session.hold_expires_at = None
        session.step = BookingStep.CONFIRMED.value
        cls._touch(session)
        cls._save(chat_session, session)

        # Link patient to chat session
        if getattr(chat_session, "patient_id", None) is None:
            chat_session.patient = patient
            chat_session.is_authenticated = True
            chat_session.save(update_fields=["patient", "is_authenticated"])

        return serialize_step(clinic, session)

    # ── Persistence ───────────────────────────────────────────────────────────

    @staticmethod
    def _save(chat_session: Any, session: BookingSession) -> None:
        ctx = dict(chat_session.conversation_context or {})
        ctx["booking"] = session.to_dict()
        chat_session.conversation_context = ctx
        chat_session.last_active_at = timezone.now()
        chat_session.save(update_fields=["conversation_context", "last_active_at"])

    @staticmethod
    def _load(chat_session: Any, booking_id: str) -> BookingSession:
        ctx = chat_session.conversation_context or {}
        data = ctx.get("booking") if isinstance(ctx, dict) else None
        if not isinstance(data, dict) or data.get("booking_id") != booking_id:
            raise BookingError("Booking session not found", status_code=404)
        return BookingSession.from_dict(data)

    @staticmethod
    def _touch(session: BookingSession) -> None:
        session.updated_at = datetime.utcnow().isoformat() + "Z"

    @classmethod
    def _hold_internal(cls, session: BookingSession, clinic: Any) -> None:
        cfg = get_booking_config(clinic)
        minutes = int(cfg.get("slot_hold_minutes") or 10)
        expires = timezone.now() + timedelta(minutes=minutes)
        session.hold_expires_at = expires.isoformat()

    @staticmethod
    def _ensure_hold(session: BookingSession) -> None:
        if not session.hold_expires_at:
            raise BookingError("Slot hold expired — please select a time again")
        try:
            exp = datetime.fromisoformat(session.hold_expires_at.replace("Z", "+00:00"))
            if timezone.is_naive(exp):
                exp = timezone.make_aware(exp, ZoneInfo("UTC"))
            if exp < timezone.now():
                raise BookingError("Slot hold expired — please select a time again")
        except BookingError:
            raise
        except Exception as exc:
            raise BookingError("Invalid slot hold") from exc

    @staticmethod
    def _specialty_name(clinic: Any, specialty_id: str) -> str:
        from apps.specialties.models import Specialty

        try:
            return Specialty.objects.get(clinic=clinic, id=specialty_id).name
        except Specialty.DoesNotExist:
            return ""

    @staticmethod
    def _doctor_name(clinic: Any, doctor_id: str) -> str:
        from apps.doctors.models import Doctor

        try:
            return Doctor.objects.get(clinic=clinic, id=doctor_id).full_name
        except Doctor.DoesNotExist:
            return ""


def _confirmation_code() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(6))
