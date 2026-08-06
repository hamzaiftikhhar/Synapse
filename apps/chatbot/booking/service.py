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
from apps.chatbot.booking.modes import (
    first_step,
    next_step,
    prev_step,
    resolve_mode_from_path,
)
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
        service_id: str | None = None,
        service_name: str | None = None,
    ) -> dict[str, Any]:
        cfg = get_booking_config(clinic)
        text = (reason or message or "").strip()

        existing = cls._load_active(chat_session)
        resuming = existing is not None
        suggested, guidance = ([], "")

        if resuming:
            session = existing
            if text and text != session.reason:
                session.reason = text
        else:
            if cfg.get("ai_discovery"):
                suggested, guidance = suggest_specialties(clinic, message=text, reason=text)
            session = BookingSession.create(
                clinic_id=str(clinic.id),
                mode=cfg["mode"],
                reason=text,
            )
            session.suggested_specialty_ids = [s["id"] for s in suggested]

        cls._apply_prefill(
            session,
            clinic,
            specialty_id=specialty_id,
            specialty_name=specialty_name,
            doctor_id=doctor_id,
            doctor_name=doctor_name,
            service_id=service_id,
            service_name=service_name,
            resuming=resuming,
        )
        cls._apply_date_time_hint(session, clinic, text)

        cls._touch(session)
        cls._save(chat_session, session)
        payload = serialize_step(clinic, session)
        payload["resumed"] = resuming
        if not resuming:
            payload["guidance"] = guidance
            payload["suggested_specialties"] = suggested
        return payload

    @staticmethod
    def _load_active(chat_session: Any) -> BookingSession | None:
        """The in-progress BookingSession for this chat session, if any —
        None when there isn't one yet or the last one already CONFIRMED."""
        ctx = chat_session.conversation_context or {}
        data = ctx.get("booking") if isinstance(ctx, dict) else None
        if not isinstance(data, dict):
            return None
        try:
            session = BookingSession.from_dict(data)
        except Exception:
            return None
        if session.step == BookingStep.CONFIRMED.value:
            return None
        return session

    @classmethod
    def _apply_prefill(
        cls,
        session: BookingSession,
        clinic: Any,
        *,
        specialty_id: str | None,
        specialty_name: str | None,
        doctor_id: str | None,
        doctor_name: str | None,
        service_id: str | None = None,
        service_name: str | None = None,
        resuming: bool,
    ) -> None:
        """Update the draft in place with newly-known specialty/doctor/service."""
        if service_id and not specialty_id:
            from apps.chatbot.nlu.resolvers import resolve_specialty_for_service

            resolved_specialty_id = resolve_specialty_for_service(clinic, str(service_id))
            if resolved_specialty_id:
                specialty_id = resolved_specialty_id
                specialty_name = specialty_name or cls._specialty_name(
                    clinic, resolved_specialty_id
                )

        changed_specialty = bool(specialty_id) and str(specialty_id) != (
            session.specialty_id or ""
        )
        changed_doctor = bool(doctor_id) and str(doctor_id) != (session.doctor_id or "")

        if changed_specialty:
            session.specialty_id = str(specialty_id)
            session.specialty_name = specialty_name or cls._specialty_name(
                clinic, str(specialty_id)
            )
        if changed_doctor:
            session.doctor_id = str(doctor_id)
            session.doctor_name = doctor_name or cls._doctor_name(clinic, str(doctor_id))
        if service_id:
            session.reason = session.reason or service_name or session.reason

        if changed_doctor or changed_specialty:
            session.date = None
            session.slot_start = None
            session.slot_end = None
            session.show_all_times = False
            session.hold_expires_at = None

        if not resuming:
            # Skip path chooser only when context already pins the route
            if session.doctor_id:
                session.mode = "choose_doctor"
                session.step = BookingStep.DATE.value
            elif session.specialty_id:
                session.mode = "specialty_first"
                session.step = BookingStep.DOCTOR.value
            else:
                # Patient chooses: First available / Help choose / Know doctor
                session.step = BookingStep.PATH.value
            return

        if changed_doctor and session.step in {
            BookingStep.PATH.value,
            BookingStep.SPECIALTY.value,
            BookingStep.TIME.value,
            BookingStep.DETAILS.value,
            BookingStep.OTP.value,
        }:
            session.mode = "choose_doctor"
            session.step = BookingStep.DATE.value
        elif changed_specialty and not doctor_id and session.step in {
            BookingStep.PATH.value,
            BookingStep.DOCTOR.value,
            BookingStep.DATE.value,
            BookingStep.TIME.value,
            BookingStep.DETAILS.value,
            BookingStep.OTP.value,
        }:
            session.mode = "specialty_first"
            session.step = BookingStep.DOCTOR.value

    @classmethod
    def _apply_date_time_hint(cls, session: BookingSession, clinic: Any, text: str) -> None:
        """Minimal relative date/time parsing so a message like "Botox Friday
        after 5" can seed the DATE/TIME steps instead of forcing the patient
        to click through them. Deliberately simple: "ASAP"/"same day" resolve
        to today only, not a multi-day forward search."""
        if not text:
            return
        from apps.chatbot.nlu.entity_extract import extract_entities
        from apps.chatbot.sql_tool.utils import (
            clinic_timezone,
            is_asap_request,
            is_same_day_request,
            parse_natural_date,
            parse_time_floor,
        )

        entities = extract_entities(text)
        tz = clinic_timezone(clinic)

        target_date = None
        if is_same_day_request(text) or is_asap_request(text):
            target_date = timezone.now().astimezone(tz).date()
        else:
            dates = entities.get("date") or []
            if dates:
                target_date = parse_natural_date(dates[0], tz=tz)

        time_floor = parse_time_floor(entities.get("time") or [])

        if target_date is not None:
            session.date = target_date.isoformat()
        if time_floor is not None:
            session.time_hint = time_floor.isoformat()

        if session.date and session.doctor_id and session.step in {
            BookingStep.PATH.value,
            BookingStep.SPECIALTY.value,
            BookingStep.DOCTOR.value,
            BookingStep.DATE.value,
        }:
            session.step = BookingStep.TIME.value

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
                if prev == BookingStep.PATH:
                    # Reset path-specific selections when returning to chooser
                    session.doctor_id = None
                    session.doctor_name = None
                    session.date = None
                    session.slot_start = None
                    session.slot_end = None
                    session.show_all_times = False
                    # Keep specialty only as soft chip if they picked one mid-flow
                if prev == BookingStep.TIME:
                    session.show_all_times = False
            cls._touch(session)
            cls._save(chat_session, session)
            return serialize_step(clinic, session)

        if action == "select_path":
            path_id = str(value.get("path") or value.get("id") or "").strip().lower()
            if path_id not in {"first_available", "help_choose", "know_doctor"}:
                raise BookingError("Invalid booking path")
            session.mode = resolve_mode_from_path(path_id)
            # Optional soft continue with a suggested specialty
            sid = str(value.get("specialty_id") or "").strip()
            sname = str(value.get("specialty_name") or "").strip()
            if sid and path_id == "help_choose":
                session.specialty_id = sid
                session.specialty_name = sname or cls._specialty_name(clinic, sid)
                session.step = BookingStep.DOCTOR.value
            else:
                if path_id == "first_available":
                    session.specialty_id = None
                    session.specialty_name = None
                    session.doctor_id = None
                    session.doctor_name = None
                session.step = first_step(session.mode).value
            session.date = None
            session.slot_start = None
            session.slot_end = None
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

        if action == "select_hero":
            start = str(value.get("start") or "")
            end = str(value.get("end") or "")
            doctor_id = str(value.get("doctor_id") or "")
            doctor_name = str(value.get("doctor") or value.get("doctor_name") or "")
            if not start or not end or not doctor_id:
                raise BookingError("Slot start, end, and doctor_id are required")

            # Hero data can be seconds/minutes stale by the time the patient
            # taps it — revalidate before holding, rather than discovering the
            # collision much later at confirm().
            if cls._slot_still_open(clinic, doctor_id=doctor_id, start=start):
                session.mode = "choose_doctor"
                session.doctor_id = doctor_id
                session.doctor_name = doctor_name or cls._doctor_name(clinic, doctor_id)
                session.slot_start = start
                session.slot_end = end
                cls._hold_internal(session, clinic)
                session.step = BookingStep.DETAILS.value
                cls._touch(session)
                cls._save(chat_session, session)
                return serialize_step(clinic, session)

            # Taken between hero-render and tap — fall back to date picking,
            # not an error page.
            session.mode = "general"
            session.doctor_id = None
            session.doctor_name = None
            session.date = None
            session.slot_start = None
            session.slot_end = None
            session.show_all_times = False
            session.step = BookingStep.DATE.value
            cls._touch(session)
            cls._save(chat_session, session)
            payload = serialize_step(clinic, session)
            payload["stale_hero"] = True
            return payload

        if action == "submit_details":
            first = str(value.get("first_name") or "").strip()
            last = str(value.get("last_name") or "").strip()
            phone = str(value.get("phone") or "").strip()
            email = str(value.get("email") or "").strip().lower()
            cfg = get_booking_config(clinic)
            vmode = cfg.get("verification_mode") or "sms"
            if not first:
                raise BookingError("First name is required")
            if vmode == "sms" and not phone:
                raise BookingError("Phone is required")
            if vmode == "email" and not email:
                raise BookingError("Email is required")
            if vmode in {"sms_or_email", "none"} and not phone and not email:
                raise BookingError("Phone or email is required")
            if not session.slot_start or not session.doctor_id:
                raise BookingError("Select a time slot first")
            cls._ensure_hold(session)
            session.patient_first_name = first
            session.patient_last_name = last
            session.patient_phone = phone
            session.patient_email = email
            if vmode == "none":
                cls._save(chat_session, session)
                return cls.confirm(
                    clinic=clinic,
                    chat_session=chat_session,
                    booking_id=session.booking_id,
                    patient=None,
                    otp_verified=False,
                )
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
            phone = session.patient_phone or ""
            email = getattr(session, "patient_email", "") or ""
            if phone:
                patient, _ = Patient.objects.get_or_create(
                    clinic=clinic,
                    phone=phone,
                    defaults={
                        "first_name": session.patient_first_name,
                        "last_name": session.patient_last_name,
                        "email": email,
                    },
                )
            elif email:
                patient = Patient.objects.filter(clinic=clinic, email=email).first()
                if patient is None:
                    patient = Patient.objects.create(
                        clinic=clinic,
                        phone=f"email:{email}"[:20],
                        email=email,
                        first_name=session.patient_first_name,
                        last_name=session.patient_last_name,
                    )
            else:
                raise BookingError("Patient contact is required")
            updates = []
            if not patient.first_name and session.patient_first_name:
                patient.first_name = session.patient_first_name
                updates.append("first_name")
            if not patient.last_name and session.patient_last_name:
                patient.last_name = session.patient_last_name
                updates.append("last_name")
            if email and not patient.email:
                patient.email = email
                updates.append("email")
            if updates:
                patient.save(update_fields=updates)

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

    @staticmethod
    def _slot_still_open(clinic: Any, *, doctor_id: str, start: str) -> bool:
        """Re-checks a specific doctor+slot is still bookable — used to
        revalidate the PATH step's hero slot, which can be stale by the time
        the patient taps it."""
        from apps.chatbot.booking.slots import active_holds_for_date, compute_slots_for_day
        from apps.doctors.models import Doctor

        try:
            start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
        except ValueError:
            return False
        try:
            doctor = Doctor.objects.get(clinic=clinic, id=doctor_id, is_deleted=False)
        except Doctor.DoesNotExist:
            return False

        target_date = start_dt.date()
        target = start_dt.replace(second=0, microsecond=0)
        slots = compute_slots_for_day(
            clinic,
            target_date=target_date,
            doctors=[doctor],
            excluded_keys=active_holds_for_date(clinic, target_date),
        )
        for s in slots:
            try:
                slot_start = datetime.fromisoformat(
                    str(s.get("start") or "").replace("Z", "+00:00")
                ).replace(second=0, microsecond=0)
            except ValueError:
                continue
            if slot_start == target:
                return True
        return False


def _confirmation_code() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(6))
