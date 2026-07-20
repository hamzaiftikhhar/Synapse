"""Authentication request/response schemas."""

from uuid import UUID

from ninja import Schema


class LoginIn(Schema):
    """POST /auth/login body."""

    username: str
    password: str
    clinic_slug: str


class UserOut(Schema):
    id: int
    username: str
    email: str
    first_name: str
    last_name: str


class ClinicOut(Schema):
    id: UUID
    slug: str
    name: str
    timezone: str


class LoginOut(Schema):
    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int
    user: UserOut
    clinic: ClinicOut


class MeOut(Schema):
    user: UserOut
    clinic: ClinicOut
