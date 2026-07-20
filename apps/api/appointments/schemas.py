"""Appointment API schemas."""

from datetime import datetime
from uuid import UUID

from ninja import Schema


class AppointmentOut(Schema):
    id: UUID
    doctor_id: UUID
    doctor_name: str
    patient_id: UUID
    patient_name: str
    service_id: UUID | None
    service_name: str | None
    insurance_plan_id: UUID | None
    insurance_name: str | None
    start_time: datetime
    end_time: datetime
    status: str
    confirmation_code: str
    notes: str
    source: str
    created_at: datetime
    updated_at: datetime


class AppointmentIn(Schema):
    doctor_id: UUID
    patient_id: UUID
    service_id: UUID | None = None
    insurance_plan_id: UUID | None = None
    start_time: datetime
    end_time: datetime
    status: str = "pending"
    notes: str = ""
    source: str = "admin"
    confirmation_code: str | None = None


class AppointmentUpdateIn(Schema):
    doctor_id: UUID | None = None
    patient_id: UUID | None = None
    service_id: UUID | None = None
    insurance_plan_id: UUID | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    status: str | None = None
    notes: str | None = None
    source: str | None = None
