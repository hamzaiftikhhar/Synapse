"""Patient API schemas."""

from datetime import date, datetime
from uuid import UUID

from ninja import Schema


class PatientOut(Schema):
    id: UUID
    phone: str
    email: str
    first_name: str
    last_name: str
    full_name: str
    date_of_birth: date | None
    preferred_language: str
    is_verified: bool
    created_at: datetime
    updated_at: datetime


class PatientIn(Schema):
    phone: str
    email: str = ""
    first_name: str
    last_name: str
    date_of_birth: date | None = None
    preferred_language: str = "en"
    is_verified: bool = False


class PatientUpdateIn(Schema):
    phone: str | None = None
    email: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    date_of_birth: date | None = None
    preferred_language: str | None = None
    is_verified: bool | None = None
