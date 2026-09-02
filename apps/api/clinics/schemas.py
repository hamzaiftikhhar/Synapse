"""Clinic profile / business hours / widget settings / onboarding schemas."""

from datetime import datetime, time
from uuid import UUID

from ninja import Schema


class ClinicProfileOut(Schema):
    id: UUID
    slug: str
    name: str
    clinic_type: str
    email: str
    phone: str
    address: dict = {}
    timezone: str
    status: str
    onboarding_step: str
    onboarding_completed_at: datetime | None = None
    # Public-widget embed/CORS allowlist — see Clinic.allowed_origins.
    allowed_origins: list[str] = []
    created_at: datetime
    updated_at: datetime


class ClinicProfileUpdateIn(Schema):
    name: str | None = None
    clinic_type: str | None = None
    email: str | None = None
    phone: str | None = None
    address: dict | None = None
    timezone: str | None = None
    onboarding_step: str | None = None
    allowed_origins: list[str] | None = None


class BusinessHourOut(Schema):
    id: UUID
    day_of_week: int
    open_time: time | None = None
    close_time: time | None = None
    is_closed: bool


class BusinessHourIn(Schema):
    day_of_week: int
    open_time: time | None = None
    close_time: time | None = None
    is_closed: bool = False


class WidgetSettingsOut(Schema):
    configuration: dict


class WidgetSettingsUpdateIn(Schema):
    configuration: dict


class OnboardingChecklistOut(Schema):
    clinic: bool
    location: bool
    providers: bool
    services: bool
    hours: bool
    availability: bool


class OnboardingCountsOut(Schema):
    providers: int = 0
    services: int = 0
    specialties: int = 0
    insurance_plans: int = 0


class OnboardingStatusOut(Schema):
    ready: bool
    checklist: OnboardingChecklistOut
    counts: OnboardingCountsOut
