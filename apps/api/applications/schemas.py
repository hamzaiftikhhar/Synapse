"""Public clinic application (Get Started) schemas."""

from datetime import datetime
from uuid import UUID

from ninja import Schema


class ClinicApplicationIn(Schema):
    clinic_name: str
    owner_name: str
    work_email: str
    phone: str = ""
    website: str = ""
    num_doctors: int | None = None
    current_scheduling_system: str = ""
    plan_slug: str
    notes: str = ""


class ClinicApplicationOut(Schema):
    id: UUID
    status: str
    created_at: datetime
