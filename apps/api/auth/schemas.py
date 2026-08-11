"""Auth request/response schemas."""

from datetime import datetime
from uuid import UUID

from ninja import Schema

from apps.accounts.models import UserRole


class StaffLoginIn(Schema):
    email: str
    password: str
    clinic_slug: str | None = None  # optional; legacy / ignored for multi-tenant select
    remember: bool = False


class StaffRegisterIn(Schema):
    email: str
    password: str
    first_name: str = ""
    last_name: str = ""


class TokenIn(Schema):
    token: str


class ResendVerificationIn(Schema):
    email: str


class ForgotPasswordIn(Schema):
    email: str


class ResetPasswordIn(Schema):
    token: str
    password: str


class ChangePasswordIn(Schema):
    current_password: str
    new_password: str


class RefreshIn(Schema):
    refresh_token: str


class SelectTenantIn(Schema):
    tenant: str  # clinic slug


class CreateClinicIn(Schema):
    name: str
    slug: str
    email: str | None = None
    phone: str = ""
    timezone: str = "America/New_York"


class EnterClinicIn(Schema):
    tenant: str  # slug or uuid


class ClinicOut(Schema):
    id: UUID
    slug: str
    name: str
    timezone: str
    status: str = "active"
    clinic_type: str = ""
    phone: str = ""
    address: dict = {}
    onboarding_step: str = ""
    onboarding_completed_at: datetime | None = None


class UserOut(Schema):
    id: int
    email: str
    username: str
    first_name: str
    last_name: str
    role: UserRole
    is_clinic_owner: bool
    email_verified: bool = False
    email_verified_at: datetime | None = None


class TenantOut(Schema):
    slug: str
    name: str
    status: str
    role: str = "CLINIC_ADMIN"


class StaffTokenOut(Schema):
    access_token: str
    refresh_token: str
    expires_in_minutes: int
    user: UserOut
    clinic: ClinicOut | None = None
    tenant: str | None = None
    tenants: list[TenantOut] = []


class MeOut(Schema):
    user: UserOut
    clinic: ClinicOut | None = None
    tenant: str | None = None
    tenants: list[TenantOut] = []
    can_exit_clinic: bool = False


class MessageOut(Schema):
    message: str


class EnterClinicOut(Schema):
    tenant: str
    clinic: ClinicOut
    message: str = "Tenant context set. Send X-Tenant-ID on clinic API requests."


# ── Patient (widget) OTP ─────────────────────────────────────────────────────


class OTPSendIn(Schema):
    clinic_slug: str
    phone: str = ""
    email: str = ""
    channel: str | None = None  # sms | email
    session_token: str | None = None
    first_name: str = ""
    last_name: str = ""


class OTPSendOut(Schema):
    message: str
    session_token: str
    patient_id: UUID
    expires_in_minutes: int
    channel: str = "sms"
    debug_code: str | None = None


class OTPVerifyIn(Schema):
    clinic_slug: str
    code: str
    phone: str = ""
    email: str = ""
    session_token: str | None = None
    first_name: str | None = None
    last_name: str | None = None


class PatientAuthOut(Schema):
    id: UUID
    phone: str
    first_name: str
    last_name: str
    is_verified: bool
    verified_at: datetime | None = None


class PatientTokenOut(Schema):
    access_token: str
    expires_in_minutes: int
    patient: PatientAuthOut
    clinic: ClinicOut
    # ChatSession token to use for appointment CRUD after verify. Always
    # prefer this over inventing a new guest session — it is the same row
    # OTP send/verify authenticated.
    session_token: str | None = None
