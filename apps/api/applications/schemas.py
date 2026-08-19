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
    # Required for the "get_started" source (validated in the router — a
    # dedicated Plan model check, not expressible as a schema constraint);
    # left blank for "demo_request", which doesn't ask for a plan yet.
    plan_slug: str = ""
    notes: str = ""
    source: str = "get_started"


class ClinicApplicationOut(Schema):
    id: UUID
    status: str
    created_at: datetime
