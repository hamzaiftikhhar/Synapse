"""Authentication request/response schemas — staff portal + patient widget."""

from uuid import UUID

from ninja import Schema

from apps.accounts.models import UserRole


# ─── Staff / admin portal ─────────────────────────────────────────────────────


class StaffLoginIn(Schema):
    """POST /auth/login body (email + password + clinic)."""

    email: str
    password: str
    clinic_slug: str


class RefreshIn(Schema):
    refresh_token: str


class UserOut(Schema):
    id: int
    email: str
    username: str
    first_name: str
    last_name: str
    role: UserRole
    is_clinic_owner: bool


class ClinicOut(Schema):
    id: UUID
    slug: str
    name: str
    timezone: str


class StaffTokenOut(Schema):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in_minutes: int
    user: UserOut
    clinic: ClinicOut | None = None


class MeOut(Schema):
    user: UserOut
    clinic: ClinicOut | None = None


# Backwards-compatible aliases
LoginIn = StaffLoginIn
LoginOut = StaffTokenOut


# ─── Patient widget (OTP) ─────────────────────────────────────────────────────


class OTPSendIn(Schema):
    clinic_slug: str
    phone: str
    session_token: str | None = None


class OTPSendOut(Schema):
    message: str
    expires_in_minutes: int
    # Only populated in DEBUG / when Twilio is not configured (dev convenience)
    debug_code: str | None = None


class OTPVerifyIn(Schema):
    clinic_slug: str
    phone: str
    code: str
    session_token: str | None = None
    first_name: str | None = None
    last_name: str | None = None


class PatientAuthOut(Schema):
    id: UUID
    phone: str
    first_name: str
    last_name: str
    is_verified: bool


class PatientTokenOut(Schema):
    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int
    patient: PatientAuthOut
    clinic: ClinicOut
