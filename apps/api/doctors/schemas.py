"""Doctor API schemas."""

from datetime import datetime
from uuid import UUID

from ninja import Schema


class DoctorOut(Schema):
    id: UUID
    full_name: str
    title: str
    bio: str
    photo_url: str
    languages: list[str]
    is_active: bool
    is_accepting_patients: bool
    is_deleted: bool
    specialty_ids: list[UUID]
    service_ids: list[UUID]
    created_at: datetime
    updated_at: datetime


class DoctorIn(Schema):
    full_name: str
    title: str = ""
    bio: str = ""
    photo_url: str = ""
    languages: list[str] | None = None
    is_active: bool = True
    is_accepting_patients: bool = True
    specialty_ids: list[UUID] = []
    service_ids: list[UUID] = []


class DoctorUpdateIn(Schema):
    full_name: str | None = None
    title: str | None = None
    bio: str | None = None
    photo_url: str | None = None
    languages: list[str] | None = None
    is_active: bool | None = None
    is_accepting_patients: bool | None = None
    specialty_ids: list[UUID] | None = None
    service_ids: list[UUID] | None = None
