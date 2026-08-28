"""Booking session state stored on ChatSession.conversation_context."""

from __future__ import annotations

import secrets
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class BookingStep(str, Enum):
    PATH = "path"  # Who would you like to see?
    DISCOVERY = "discovery"
    SERVICE = "service"
    SPECIALTY = "specialty"  # legacy alias; coerced to SERVICE on load
    DOCTOR = "doctor"
    DATE = "date"
    TIME = "time"
    DETAILS = "details"
    OTP = "otp"
    # Reached only when a booking would otherwise auto-confirm with no
    # deliberate user gesture at all (an already-authenticated session, or
    # a clinic with verification disabled) — the normal DETAILS→OTP path
    # already requires entering a received code, which is itself a
    # confirming action, so it goes straight to CONFIRMED. See
    # BookingService._route_to_review_if_authenticated.
    REVIEW = "review"
    CONFIRMED = "confirmed"


@dataclass
class BookingSession:
    booking_id: str
    clinic_id: str
    mode: str
    step: str
    reason: str = ""
    service_id: str | None = None
    service_name: str | None = None
    specialty_id: str | None = None
    specialty_name: str | None = None
    doctor_id: str | None = None
    doctor_name: str | None = None
    date: str | None = None  # YYYY-MM-DD
    slot_start: str | None = None  # ISO
    slot_end: str | None = None
    patient_id: str | None = None
    patient_first_name: str = ""
    patient_last_name: str = ""
    patient_phone: str = ""
    patient_email: str = ""
    hold_expires_at: str | None = None
    confirmation_code: str | None = None
    appointment_id: str | None = None
    # Phase 42A — resolved insurance plan, threaded through the wizard as
    # a real InsurancePlan id/name rather than string-concatenated into
    # `reason` (the old behavior — never resolved, never shown at review,
    # never actually set on the Appointment despite the FK existing).
    insurance_plan_id: str | None = None
    insurance_plan_name: str | None = None
    # Phase 42A — DOB identity check. `pending_dob` is transient: set at
    # the DETAILS step, consumed (compared or captured) at OTP-verify
    # time, then cleared — the raw value is never shown in the REVIEW or
    # CONFIRMED payload, only the boolean outcome. Never log this field.
    pending_dob: str | None = None
    dob_verified: bool = False
    # Reschedule flow: the appointment this booking replaces, if any. Kept
    # active until this new booking is confirmed — cancelled atomically with
    # the new appointment's creation in BookingService.confirm, never eagerly.
    replaces_appointment_id: str | None = None
    suggested_specialty_ids: list[str] = field(default_factory=list)
    show_all_times: bool = False
    time_hint: str | None = None  # ISO time floor, e.g. "17:00:00" — filters TIME step options
    # Set once, at the moment a forward shortcut actually skips these steps
    # (_route_to_review_if_authenticated sets both; verification_mode="none"
    # sets only otp_skipped, since it genuinely shows/submits DETAILS first).
    # Read by step_index() so the progress counter reflects what this
    # session will actually show, and by apply_step("back") so Back walks
    # the same shortcut in reverse instead of stopping at a step the
    # forward flow never showed this patient.
    details_skipped: bool = False
    otp_skipped: bool = False
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BookingSession:
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        filtered = {k: v for k, v in data.items() if k in known}
        if filtered.get("mode") == "specialty_first":
            filtered["mode"] = "service_first"
        if filtered.get("step") == BookingStep.SPECIALTY.value:
            filtered["step"] = BookingStep.SERVICE.value
        return cls(**filtered)

    @classmethod
    def create(cls, *, clinic_id: str, mode: str, reason: str = "") -> BookingSession:
        now = datetime.utcnow().isoformat() + "Z"
        return cls(
            booking_id=secrets.token_urlsafe(16),
            clinic_id=str(clinic_id),
            mode=mode,
            step=BookingStep.PATH.value,
            reason=reason or "",
            created_at=now,
            updated_at=now,
        )
