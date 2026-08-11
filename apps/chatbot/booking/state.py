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
    SPECIALTY = "specialty"
    DOCTOR = "doctor"
    DATE = "date"
    TIME = "time"
    DETAILS = "details"
    OTP = "otp"
    CONFIRMED = "confirmed"


@dataclass
class BookingSession:
    booking_id: str
    clinic_id: str
    mode: str
    step: str
    reason: str = ""
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
    # Reschedule flow: the appointment this booking replaces, if any. Kept
    # active until this new booking is confirmed — cancelled atomically with
    # the new appointment's creation in BookingService.confirm, never eagerly.
    replaces_appointment_id: str | None = None
    suggested_specialty_ids: list[str] = field(default_factory=list)
    show_all_times: bool = False
    time_hint: str | None = None  # ISO time floor, e.g. "17:00:00" — filters TIME step options
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BookingSession:
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        filtered = {k: v for k, v in data.items() if k in known}
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
