"""Booking wizard service — start, step, hold, confirm."""

from __future__ import annotations

import logging
import secrets
import string
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from django.db import IntegrityError, OperationalError, transaction
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
        slot_start: str | None = None,
        slot_end: str | None = None,
        insurance_name: str | None = None,
        replaces_appointment_id: str | None = None,
    ) -> dict[str, Any]:
        cfg = get_booking_config(clinic)
        text = (reason or message or "").strip()
        if insurance_name and insurance_name not in text:
            text = f"{text} (insurance: {insurance_name})".strip() if text else f"Book with {insurance_name}"

        # Phase 42A — resolve to a real InsurancePlan, not just free text
        # folded into `reason` (the old behavior: never resolved, never
        # shown at review, never actually set on the Appointment despite
        # the FK existing). Reuses the same name→plan matching
        # resolve_entities already does for the chat/NLU path — no new
        # matching logic, just an actual place for the result to land.
        insurance_plan_id, insurance_plan_name = cls._resolve_insurance(
            clinic, insurance_name
        )

        existing = cls._load_active(chat_session)
        prefills = any([specialty_id, doctor_id, service_id, slot_start])
        if existing and not prefills:
            from apps.chatbot.routing.signals import is_generic_book_request

            leftover = (
                existing.step != BookingStep.PATH.value
                or existing.doctor_id
                or existing.service_id
                or existing.date
            )
            if leftover and is_generic_book_request(text):
                # Bare "book an appointment" must not dump the patient into a
                # leftover TIME/DOCTOR step from an earlier draft.
                existing = None
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

        if insurance_plan_id:
            session.insurance_plan_id = insurance_plan_id
            session.insurance_plan_name = insurance_plan_name

        cls._apply_prefill(
            session,
            clinic,
            specialty_id=specialty_id,
            specialty_name=specialty_name,
            doctor_id=doctor_id,
            doctor_name=doctor_name,
            service_id=service_id,
            service_name=service_name,
            slot_start=slot_start,
            resuming=resuming,
        )
        cls._apply_date_time_hint(session, clinic, text)
        cls._apply_slot_prefill(
            session,
            clinic,
            slot_start=slot_start,
            slot_end=slot_end,
            doctor_id=doctor_id or session.doctor_id,
            doctor_name=doctor_name or session.doctor_name,
        )
        if replaces_appointment_id:
            session.replaces_appointment_id = replaces_appointment_id

        # Hero/availability taps prefill a concrete slot and land on DETAILS.
        # If this chat session already verified a patient (view/reschedule/
        # prior book), skip re-collecting contact + OTP — same short-circuit
        # as select_time / select_hero.
        if session.step == BookingStep.DETAILS.value:
            skip = cls._route_to_review_if_authenticated(
                clinic=clinic, chat_session=chat_session, session=session
            )
            if skip is not None:
                return skip

        cls._touch(session)
        cls._save(chat_session, session)
        payload = serialize_step(clinic, session)
        payload["resumed"] = resuming
        if not resuming:
            payload["guidance"] = guidance
            payload["suggested_specialties"] = suggested
        return payload

    @staticmethod
    def _resolve_insurance(
        clinic: Any, insurance_name: str | None
    ) -> tuple[str | None, str | None]:
        """Free-text provider/plan name → a real InsurancePlan on this
        clinic, reusing the exact same matcher the chat/NLU path already
        uses (`resolve_entities`) rather than a second parallel one."""
        if not insurance_name:
            return None, None
        from apps.chatbot.nlu.resolvers import resolve_entities
        from apps.chatbot.nlu.schemas import ExtractedEntities
        from apps.insurance.models import InsurancePlan

        resolved = resolve_entities(
            clinic, ExtractedEntities(insurance_provider=insurance_name)
        )
        plan_id = resolved.insurance_plan_id
        if isinstance(plan_id, list):
            plan_id = plan_id[0] if plan_id else None
        if not plan_id:
            return None, None
        plan = InsurancePlan.objects.filter(
            clinic=clinic, id=plan_id, is_deleted=False
        ).first()
        if plan is None:
            return None, None
        name = f"{plan.provider_name} ({plan.plan_name})" if plan.plan_name else plan.provider_name
        return str(plan.id), name

    @classmethod
    def active_booking_payload(cls, clinic: Any, chat_session: Any) -> dict[str, Any] | None:
        """Read-only snapshot of an in-progress booking, for session resume.

        Phase 42A: `/chat/resume` used to only replay historical chat
        messages — an interrupted mid-wizard booking had no way back once
        the tab closed and reopened, since `hydrateHistoryRow` deliberately
        stamps any *historical* booking_wizard message `completed: true`
        (frontend message-parser.ts) so an old, already-processed wizard
        card from real history can never mount live again. That's correct
        for genuine history; it left no path at all for a booking that's
        still actually in progress. This is the read the frontend uses to
        tell the two apart and remount a live wizard at its real step. Pure
        read — `serialize_step` only formats existing state, `_load_active`
        already excludes CONFIRMED bookings."""
        session = cls._load_active(chat_session)
        if session is None:
            return None
        return serialize_step(clinic, session)

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

    # Steps that mean "a slot is already picked and pending confirmation" —
    # reachable only via an explicit slot selection. A fresh doctor/service
    # prefill arriving here without its own explicit slot means the
    # *previous* attempt's commitment, never re-affirmed in this call.
    _SLOT_COMMITTED_STEPS = frozenset(
        {BookingStep.DETAILS.value, BookingStep.OTP.value, BookingStep.REVIEW.value}
    )

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
        slot_start: str | None = None,
        resuming: bool,
    ) -> None:
        """Update the draft in place with newly-known service/doctor/specialty.

        Service is the booking relationship (who can perform it). Specialty is
        discovery metadata only and never skips the patient to a doctor list.
        """
        changed_service = bool(service_id) and str(service_id) != (session.service_id or "")
        changed_specialty = bool(specialty_id) and str(specialty_id) != (
            session.specialty_id or ""
        )
        changed_doctor = bool(doctor_id) and str(doctor_id) != (session.doctor_id or "")

        # A new utterance that names who to book, but not what, must not keep
        # a previous *committed* draft's service. "Put me down with Dr Lin
        # as soon as you can" is not a continuation of leftover Adult
        # Cleaning left over from an already-reviewed/held booking.
        #
        # Scoped to _SLOT_COMMITTED_STEPS on purpose, not "any time doctor_id
        # arrives without service_id" — that broader version also fired
        # during completely normal, uninterrupted SERVICE -> DOCTOR
        # progression (pick a service, then immediately pick a doctor for
        # it), silently dropping a service the patient had just chosen
        # seconds earlier in the same live flow. Reproduced directly:
        # start(service_id=Cleaning) -> start(doctor_id=Maya, no service_id)
        # wiped Cleaning even though nothing about that flow was stale.
        stale_service = (
            bool(doctor_id)
            and not service_id
            and bool(session.service_id)
            and (
                bool(session.slot_start)
                or session.step in cls._SLOT_COMMITTED_STEPS
            )
        )

        # A doctor/service named in this call, with no slot tapped alongside
        # it, must not inherit a previous attempt's held time — including
        # leftover REVIEW/DETAILS. An explicit slot_start is a tap and wins.
        stale_commitment = (
            bool(doctor_id or service_id)
            and not slot_start
            and (
                bool(session.slot_start)
                or session.step in cls._SLOT_COMMITTED_STEPS
            )
        )

        if stale_service:
            session.service_id = None
            session.service_name = None

        if changed_service:
            session.service_id = str(service_id)
            session.service_name = service_name or cls._service_name(
                clinic, str(service_id)
            )
        if changed_specialty:
            session.specialty_id = str(specialty_id)
            session.specialty_name = specialty_name or cls._specialty_name(
                clinic, str(specialty_id)
            )
        if changed_doctor:
            session.doctor_id = str(doctor_id)
            session.doctor_name = doctor_name or cls._doctor_name(clinic, str(doctor_id))
        if session.service_name and not session.reason:
            session.reason = session.service_name

        if changed_doctor or changed_service or stale_commitment or stale_service:
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
            elif session.service_id:
                session.mode = "service_first"
                session.step = BookingStep.DOCTOR.value
            elif session.specialty_id:
                session.mode = "service_first"
                session.step = BookingStep.SERVICE.value
            else:
                # Patient chooses: First available / Help choose / Know doctor
                session.step = BookingStep.PATH.value
            return

        if (changed_doctor or stale_commitment) and session.step in {
            BookingStep.PATH.value,
            BookingStep.SERVICE.value,
            BookingStep.SPECIALTY.value,
            BookingStep.TIME.value,
            BookingStep.DETAILS.value,
            BookingStep.OTP.value,
            BookingStep.REVIEW.value,
        }:
            session.mode = "choose_doctor"
            session.step = BookingStep.DATE.value
        elif changed_service and not doctor_id and session.step in {
            BookingStep.PATH.value,
            BookingStep.SERVICE.value,
            BookingStep.SPECIALTY.value,
            BookingStep.DOCTOR.value,
            BookingStep.DATE.value,
            BookingStep.TIME.value,
            BookingStep.DETAILS.value,
            BookingStep.OTP.value,
            BookingStep.REVIEW.value,
        }:
            session.mode = "service_first"
            session.step = BookingStep.DOCTOR.value

    @classmethod
    def _apply_date_time_hint(cls, session: BookingSession, clinic: Any, text: str) -> None:
        """Seed the DATE/TIME steps from a message like "Botox Friday after 5"
        so the patient isn't made to click through steps they already answered.

        The date comes from the same canonical resolver the availability
        handler uses. It must not be re-derived here: this method used to run
        its own `parse_natural_date(dates[0])`, which for "book me with dr aris
        16 oct friday" seeded the *next Friday* instead of October 16 — the
        booking wizard quietly disagreeing with the answer the patient had just
        been shown. Anything the resolver won't commit to (unreadable,
        ambiguous, past, beyond the horizon, or a whole month rather than a
        day) seeds nothing, and the patient picks a date themselves.
        """
        if not text:
            return
        from apps.chatbot.booking.config import booking_horizon_days
        from apps.chatbot.nlu.entity_extract import extract_entities
        from apps.chatbot.sql_tool.utils import (
            clinic_timezone,
            is_asap_request,
            is_same_day_request,
            parse_time_floor,
        )
        from apps.chatbot.temporal import TemporalStatus, resolve_temporal_query

        entities = extract_entities(text)
        tz = clinic_timezone(clinic)

        target_date = None
        if is_same_day_request(text) or is_asap_request(text):
            target_date = timezone.now().astimezone(tz).date()
        else:
            scope = resolve_temporal_query(
                date_entities=entities.get("date") or [],
                today=timezone.now().astimezone(tz).date(),
                horizon_days=booking_horizon_days(clinic),
                message=text,
                tz=tz,
            )
            if scope.status is TemporalStatus.RESOLVED and not scope.is_range:
                target_date = scope.start

        time_floor = parse_time_floor(entities.get("time") or [])

        if target_date is not None:
            session.date = target_date.isoformat()
        if time_floor is not None:
            session.time_hint = time_floor.isoformat()

        if session.date and session.doctor_id and session.step in {
            BookingStep.PATH.value,
            BookingStep.SERVICE.value,
            BookingStep.SPECIALTY.value,
            BookingStep.DOCTOR.value,
            BookingStep.DATE.value,
        }:
            session.step = BookingStep.TIME.value

    @classmethod
    def _apply_slot_prefill(
        cls,
        session: BookingSession,
        clinic: Any,
        *,
        slot_start: str | None,
        slot_end: str | None,
        doctor_id: str | None,
        doctor_name: str | None,
    ) -> None:
        """Jump straight to details when the patient tapped a concrete slot."""
        start = (slot_start or "").strip()
        end = (slot_end or "").strip()
        did = str(doctor_id or session.doctor_id or "").strip()
        if not start or not end or not did:
            return

        session.mode = "choose_doctor"
        session.doctor_id = did
        session.doctor_name = doctor_name or cls._doctor_name(clinic, did) or session.doctor_name
        try:
            parsed = datetime.fromisoformat(start.replace("Z", "+00:00"))
            session.date = parsed.date().isoformat()
        except Exception:
            pass

        if cls._slot_still_open(clinic, doctor_id=did, start=start):
            session.slot_start = start
            session.slot_end = end
            cls._hold_internal(session, clinic)
            session.step = BookingStep.DETAILS.value
            return

        # Slot taken — keep doctor, ask for another time
        session.slot_start = None
        session.slot_end = None
        session.show_all_times = False
        session.step = BookingStep.DATE.value

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
            # Walk the same shortcut this session's forward path actually
            # took, in reverse — session.otp_skipped/details_skipped are set
            # once, at the moment a forward step genuinely skipped them (see
            # _route_to_review_if_authenticated and submit_details'
            # verification_mode="none" branch), so Back can't stop at a step
            # this particular session never showed. Confirmed live: without
            # this, Back landed on a contact-details screen, then re-picking
            # a time from the step before it skipped straight past DETAILS
            # to REVIEW again — proving DETAILS was never a real stop for
            # that session, just a Back-only dead end.
            if prev == BookingStep.OTP and session.otp_skipped:
                prev = prev_step(session.mode, prev.value)
            if prev == BookingStep.DETAILS and session.details_skipped:
                prev = prev_step(session.mode, prev.value)
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
            sid = str(value.get("service_id") or "").strip()
            sname = str(value.get("service_name") or "").strip()
            if sid and path_id == "help_choose":
                session.service_id = sid
                session.service_name = sname or cls._service_name(clinic, sid)
                session.step = BookingStep.DOCTOR.value
            else:
                if path_id == "first_available":
                    session.service_id = None
                    session.service_name = None
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

        if action in {"clear_specialty", "clear_service"}:
            session.service_id = None
            session.service_name = None
            session.specialty_id = None
            session.specialty_name = None
            if session.step == BookingStep.DOCTOR.value:
                pass  # refresh doctors unfiltered
            elif session.step not in (
                BookingStep.SERVICE.value,
                BookingStep.SPECIALTY.value,
                BookingStep.DOCTOR.value,
            ):
                session.step = (
                    BookingStep.DOCTOR.value
                    if session.mode == "choose_doctor"
                    else BookingStep.SERVICE.value
                )
            cls._touch(session)
            cls._save(chat_session, session)
            return serialize_step(clinic, session)

        if action == "more_times":
            session.show_all_times = True
            cls._touch(session)
            cls._save(chat_session, session)
            return serialize_step(clinic, session)

        if action in {"select_service", "select_specialty"}:
            sid = str(value.get("id") or "")
            name = str(value.get("name") or "")
            if not sid:
                raise BookingError("Service id is required")
            session.service_id = sid
            session.service_name = name or cls._service_name(clinic, sid)
            session.doctor_id = None
            session.doctor_name = None
            session.date = None
            session.slot_start = None
            session.slot_end = None
            nxt = next_step(session.mode, session.step)
            if session.step in {
                BookingStep.SERVICE.value,
                BookingStep.SPECIALTY.value,
            } and nxt:
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
            skip = cls._route_to_review_if_authenticated(
                clinic=clinic, chat_session=chat_session, session=session
            )
            if skip is not None:
                return skip
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
                skip = cls._route_to_review_if_authenticated(
                    clinic=clinic, chat_session=chat_session, session=session
                )
                if skip is not None:
                    return skip
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
            dob_raw = str(value.get("date_of_birth") or "").strip()
            cfg = get_booking_config(clinic)
            vmode = cfg.get("verification_mode") or "sms"
            if not first:
                raise BookingError("First name is required")
            if not dob_raw:
                raise BookingError("Date of birth is required")
            try:
                dob = date.fromisoformat(dob_raw)
            except ValueError:
                raise BookingError("Enter a valid date of birth") from None
            today = timezone.now().date()
            if dob > today or dob.year < today.year - 120:
                raise BookingError("Enter a valid date of birth")

            # Normalize: if a single contact was mis-filed, classify by @
            if phone and "@" in phone and not email:
                email = phone.lower()
                phone = ""
            if email and "@" not in email and not phone:
                phone = email
                email = ""

            if email and ("@" not in email or "." not in email.split("@")[-1]):
                raise BookingError("Enter a valid email address")
            if phone:
                digits = "".join(ch for ch in phone if ch.isdigit())
                if len(digits) < 7 or len(digits) > 15:
                    raise BookingError("Enter a valid phone number")
            if not phone and not email:
                raise BookingError("Phone or email is required for verification")
            if not session.slot_start or not session.doctor_id:
                raise BookingError("Select a time slot first")
            cls._ensure_hold(session)
            session.patient_first_name = first
            session.patient_last_name = last
            session.patient_phone = phone
            session.patient_email = email
            session.pending_dob = dob.isoformat()
            if vmode == "none":
                # No OTP to type — without a REVIEW stop here, nothing between
                # this form and a real Appointment would ever require a
                # deliberate "yes, book it" gesture from the patient.
                session.otp_skipped = True
                session.step = BookingStep.REVIEW.value
                cls._touch(session)
                cls._save(chat_session, session)
                return serialize_step(clinic, session)
            session.step = BookingStep.OTP.value
            cls._touch(session)
            cls._save(chat_session, session)
            return serialize_step(clinic, session)

        if action == "verify_otp":
            # Phase 42A — this is the fix for the gap the docstring on
            # BookingStep.REVIEW used to describe as intentional: "the
            # normal DETAILS→OTP path already requires entering a received
            # code, which is itself a confirming action, so it goes
            # straight to CONFIRMED." That meant the single most common
            # booking path — a new or returning patient typing a phone/
            # email OTP — had no review screen and no separate "yes, book
            # it" gesture at all; the code-entry submit *was* the booking.
            # Splitting verification (this action, ends on REVIEW) from
            # confirmation (confirm_review below, ends on CONFIRMED) closes
            # that for every path, not just the two that already had it
            # (an already-authenticated session, or verification_mode=
            # "none").
            if session.step != BookingStep.OTP.value:
                raise BookingError("Not at the verification step")
            code = str(value.get("otp_code") or "").strip()
            if not code:
                raise BookingError("Enter the code we sent you")
            from apps.chatbot.services.otp_service import OTPError, verify_otp

            dob_value = None
            if session.pending_dob:
                try:
                    dob_value = date.fromisoformat(session.pending_dob)
                except ValueError:
                    dob_value = None
            try:
                result = verify_otp(
                    clinic=clinic,
                    phone=session.patient_phone,
                    email=session.patient_email,
                    code=code,
                    session_token=getattr(chat_session, "session_token", None),
                    first_name=session.patient_first_name,
                    last_name=session.patient_last_name,
                    date_of_birth=dob_value,
                )
            except OTPError as exc:
                raise BookingError(str(exc), status_code=exc.status_code) from exc
            session.patient_id = str(result.patient.id)
            session.dob_verified = result.dob_verified
            session.pending_dob = None
            session.step = BookingStep.REVIEW.value
            cls._touch(session)
            cls._save(chat_session, session)
            return serialize_step(clinic, session)

        if action == "edit_details":
            # Lets the patient fix a typo'd name or change their insurance
            # selection directly from Review, without re-running the whole
            # DETAILS→OTP flow. Deliberately narrower than submit_details:
            # phone/email/DOB are the identity-verification anchor (already
            # OTP+DOB-checked to reach REVIEW at all), so they are not
            # editable here — changing contact info has to go back through
            # real verification via the existing "Back" action, same rule
            # already applied to DOB.
            if session.step != BookingStep.REVIEW.value:
                raise BookingError("Nothing to edit yet")
            first = str(value.get("first_name") or "").strip()
            if not first:
                raise BookingError("First name is required")
            session.patient_first_name = first
            session.patient_last_name = str(value.get("last_name") or "").strip()
            if "insurance_name" in value:
                insurance_plan_id, insurance_plan_name = cls._resolve_insurance(
                    clinic, str(value.get("insurance_name") or "").strip() or None
                )
                session.insurance_plan_id = insurance_plan_id
                session.insurance_plan_name = insurance_plan_name
            cls._touch(session)
            cls._save(chat_session, session)
            return serialize_step(clinic, session)

        if action == "confirm_review":
            if session.step != BookingStep.REVIEW.value:
                raise BookingError("Nothing to confirm yet")
            patient = None
            otp_verified = False
            dob_verified = session.dob_verified
            if session.patient_id:
                # Already verified via the "verify_otp" action above — this
                # confirm is the separate, deliberate "Confirm & book" tap
                # from REVIEW, not a fresh code submission. A code can only
                # ever be consumed once (otp.verified_at), so re-running
                # verify_otp here isn't an option even if we wanted to.
                from apps.patients.models import Patient

                patient = Patient.objects.filter(
                    clinic=clinic, id=session.patient_id
                ).first()
                if patient is None:
                    raise BookingError(
                        "We couldn't find your verified details — please verify again",
                        status_code=401,
                    )
                otp_verified = True
            elif getattr(chat_session, "is_authenticated", False) and getattr(
                chat_session, "patient", None
            ):
                patient = chat_session.patient
                otp_verified = True
            return cls.confirm(
                clinic=clinic,
                chat_session=chat_session,
                booking_id=session.booking_id,
                patient=patient,
                otp_verified=otp_verified,
                dob_verified=dob_verified,
            )

        raise BookingError(f"Unknown action: {action}")

    @classmethod
    def _route_to_review_if_authenticated(
        cls,
        *,
        clinic: Any,
        chat_session: Any,
        session: BookingSession,
    ) -> dict[str, Any] | None:
        """
        Skip the details/OTP steps and go straight to REVIEW when this chat
        session already has a verified patient — e.g. the patient verified
        earlier this session to view/reschedule/cancel an appointment, or
        booked one already. Re-collecting their name and contact info and
        sending them a second OTP would be asking them to authenticate a
        second time for no reason; `chat_session.is_authenticated` /
        `.patient` is already the source of truth.

        This used to call confirm() directly here, creating the real
        Appointment with no user action between picking a time slot and
        being told "you're confirmed" — the normal DETAILS→OTP path always
        has the patient enter a received code as a deliberate confirming
        gesture, but this shortcut had none at all. Routing to REVIEW
        instead means every path now ends on an explicit "Confirm booking"
        tap before anything is actually created (BookingStep.REVIEW).

        Returns the review-step payload if this session should review, else
        None (meaning: proceed to the normal details/OTP step).
        """
        if not getattr(chat_session, "is_authenticated", False):
            return None
        patient = getattr(chat_session, "patient", None)
        if patient is None:
            return None
        # The review/confirmation cards read these off the session, not the
        # Patient row — populate them since we're skipping the details step
        # that would normally have set them. Email-only patients store a
        # hashed placeholder in Patient.phone (`email:<digest>`); never
        # surface that internal stand-in as a real phone number.
        phone = (patient.phone or "").strip()
        if phone.startswith("email:"):
            phone = ""
        session.patient_first_name = patient.first_name
        session.patient_last_name = patient.last_name
        session.patient_phone = phone
        session.patient_email = patient.email or ""
        session.details_skipped = True
        session.otp_skipped = True
        session.step = BookingStep.REVIEW.value
        cls._touch(session)
        cls._save(chat_session, session)
        return serialize_step(clinic, session)

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
        dob_verified: bool = False,
    ) -> dict[str, Any]:
        from apps.appointments.models import Appointment, AppointmentSource, AppointmentStatus
        from apps.doctors.models import Doctor
        from apps.patients.services import patient_service

        session = cls._load(chat_session, booking_id)
        cfg = get_booking_config(clinic)

        if cfg.get("require_auth") and not otp_verified and patient is None:
            raise BookingError("OTP verification required", status_code=401)

        cls._ensure_hold(session)

        if patient is None:
            # Get or create patient from booking details — routed through
            # patient_service's shared dedup primitives (Phase 29 Step 3
            # fix) rather than a raw get_or_create keyed on this wizard's
            # own phone formatting. This used to be its own inline lookup;
            # differently-formatted phone input against an existing
            # SMS-verified record (e.g. missing the "+1" prefix) could
            # silently create a second Patient row for the same person —
            # the comment further down about replaces_appointment_id
            # ownership was already flagging the symptom of this bug.
            phone = session.patient_phone or ""
            email = getattr(session, "patient_email", "") or ""
            if phone:
                patient, _ = patient_service.get_or_create_by_phone(
                    clinic=clinic,
                    phone=phone,
                    first_name=session.patient_first_name,
                    last_name=session.patient_last_name,
                )
            elif email:
                patient, _ = patient_service.get_or_create_by_email(
                    clinic=clinic,
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
            # Phase 42A — a clinic with verification_mode="none" never
            # calls verify_otp, so DOB was collected at DETAILS but never
            # compared/backfilled there. Capture it here (write-once, only
            # if nothing's on file yet) — this is capture, not a proven
            # identity check, so dob_verified is deliberately left as
            # whatever the caller passed (False unless already established
            # by an OTP path elsewhere this session), not set True here.
            if not patient.date_of_birth and session.pending_dob:
                try:
                    patient.date_of_birth = date.fromisoformat(session.pending_dob)
                    updates.append("date_of_birth")
                except ValueError:
                    pass
            if updates:
                patient.save(update_fields=updates)

        session.patient_id = str(patient.id)
        session.dob_verified = dob_verified
        session.pending_dob = None

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

        # Collision check — overlap, not just an identical start_time, so this
        # matches the excl_appointments_no_overlap constraint the insert will
        # hit anyway. Matching only on start_time let partial overlaps through
        # to surface as a raw IntegrityError instead of a clean message.
        conflict = Appointment.objects.filter(
            clinic=clinic,
            doctor=doctor,
            start_time__lt=end,
            end_time__gt=start,
        ).exclude(
            status__in=[AppointmentStatus.CANCELLED, AppointmentStatus.RESCHEDULED],
        ).exists()
        if conflict:
            raise BookingError(
                "That time slot is no longer available. Please choose another time.",
                status_code=409,
            )

        code = _confirmation_code()
        try:
            # `confirm` is itself @transaction.atomic (class decorator above),
            # so the create below and the reschedule-cancel that follows it
            # already commit-or-rollback together — the patient is never left
            # with neither appointment if this fails partway, and the old
            # appointment stays live (bookable fallback) through the whole
            # wizard right up until this exact point.
            appt = Appointment.objects.create(
                clinic=clinic,
                doctor=doctor,
                patient=patient,
                service_id=session.service_id or None,
                insurance_plan_id=session.insurance_plan_id or None,
                start_time=start,
                end_time=end,
                status=AppointmentStatus.CONFIRMED,
                confirmation_code=code,
                notes=session.reason[:500] if session.reason else "",
                source=AppointmentSource.CHATBOT,
            )
            if session.replaces_appointment_id:
                # Ownership is the chat session's original OTP-verified
                # patient (already re-validated in booking_start), not the
                # `patient` resolved just now from whatever the wizard's own
                # contact step collected — that can legitimately produce a
                # second Patient row for the same person (e.g. phone typed
                # without the "+1" the SMS-verified record was saved with),
                # which would silently fail to match here and leave both
                # appointments active.
                owner_patient_id = getattr(chat_session, "patient_id", None) or patient.id
                updated = (
                    Appointment.objects.filter(
                        id=session.replaces_appointment_id,
                        clinic=clinic,
                        patient_id=owner_patient_id,
                    )
                    .exclude(id=appt.id)
                    .update(status=AppointmentStatus.CANCELLED, updated_at=timezone.now())
                )
                if not updated:
                    logger.warning(
                        "Reschedule: old appointment %s not found/owned for "
                        "patient %s — new appointment %s created anyway",
                        session.replaces_appointment_id,
                        patient.id,
                        appt.id,
                    )
        except IntegrityError as exc:
            raise BookingError(
                "Could not create appointment — slot may have been taken.",
                status_code=409,
            ) from exc
        except OperationalError as exc:
            # Simultaneous inserts for the same doctor can deadlock inside the
            # overlap constraint's GiST check. Losing that race means the slot
            # went to the other request, so answer like any other conflict
            # rather than letting a 500 reach the widget.
            logger.warning(
                "Booking insert lost a database race for doctor %s at %s: %s",
                doctor.id,
                start.isoformat(),
                exc,
            )
            raise BookingError(
                "That time slot is no longer available. Please choose another time.",
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

        from apps.chatbot.services.visitor_service import link_session_visitor_to_patient

        link_session_visitor_to_patient(chat_session, patient)

        result = serialize_step(clinic, session)
        confirmation = result.get("confirmation")
        if confirmation:
            from apps.chatbot.services.message_history import persist_confirmation_message

            persist_confirmation_message(chat_session, confirmation)
        return result

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
    def _service_name(clinic: Any, service_id: str) -> str:
        from apps.services.models import Service

        try:
            return Service.objects.get(clinic=clinic, id=service_id).name
        except Service.DoesNotExist:
            return ""

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
