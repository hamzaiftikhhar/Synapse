"""Auth dependencies — StaffJWTAuth vs PatientJWTAuth + tenant resolution.

Tenant context for staff:
  1. SUPER_ADMIN + X-Tenant-ID header (slug or UUID) → that clinic
  2. Else JWT `tenant` (slug) or legacy `clinic_id` (UUID)
  3. Else no clinic (platform mode)
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from django.contrib.auth import get_user_model
from django.http import HttpRequest
from ninja.errors import HttpError
from ninja.security import HttpBearer

from apps.accounts.models import ClinicStaff, UserRole
from apps.api.auth.jwt import (
    PatientTokenPayload,
    StaffTokenPayload,
    decode_patient_access_token,
    decode_staff_token,
)
from apps.clinics.models import Clinic, ClinicStatus
from apps.patients.models import Patient

User = get_user_model()

TENANT_HEADER = "HTTP_X_TENANT_ID"


@dataclass
class StaffAuthContext:
    user: User  # type: ignore[valid-type]
    clinic: Clinic | None
    staff: ClinicStaff | None
    role: str
    tenant: str | None = None  # active slug


@dataclass
class PatientAuthContext:
    patient: Patient
    clinic: Clinic
    session_id: object | None


def _blocked_status(clinic: Clinic) -> bool:
    return clinic.status in {ClinicStatus.SUSPENDED, ClinicStatus.CANCELLED}


def resolve_clinic_ref(ref: str) -> Clinic | None:
    """Resolve public tenant identifier (slug or UUID) to Clinic."""
    ref = (ref or "").strip()
    if not ref:
        return None
    try:
        return Clinic.objects.get(slug=ref)
    except Clinic.DoesNotExist:
        pass
    try:
        return Clinic.objects.get(pk=UUID(ref))
    except (Clinic.DoesNotExist, ValueError, TypeError):
        return None


def _clinic_from_token(payload: StaffTokenPayload) -> Clinic | None:
    if payload.tenant:
        clinic = resolve_clinic_ref(payload.tenant)
        if clinic is not None:
            return clinic
    if payload.clinic_id is not None:
        try:
            return Clinic.objects.get(pk=payload.clinic_id)
        except Clinic.DoesNotExist:
            return None
    return None


class StaffJWTAuth(HttpBearer):
    """Validate staff Bearer JWT. Rejects patient tokens."""

    def authenticate(self, request, token: str) -> StaffAuthContext | None:
        payload: StaffTokenPayload = decode_staff_token(
            token, expected_type="staff_access"
        )

        try:
            user = User.objects.get(pk=payload.user_id, is_active=True)
        except User.DoesNotExist:
            return None

        if user.role != payload.role:
            return None

        clinic: Clinic | None = None
        staff: ClinicStaff | None = None
        tenant_slug: str | None = None

        header_tenant = request.META.get(TENANT_HEADER) or request.headers.get(
            "X-Tenant-ID"
        )

        if user.role == UserRole.SUPER_ADMIN:
            # Prefer valid X-Tenant-ID override; else JWT tenant.
            # Invalid/blocked refs must NOT 401 — fall back to platform mode.
            candidates: list[str] = []
            if header_tenant and str(header_tenant).strip():
                candidates.append(str(header_tenant).strip())
            if payload.tenant and str(payload.tenant).strip():
                t = str(payload.tenant).strip()
                if t not in candidates:
                    candidates.append(t)
            for ref in candidates:
                resolved = resolve_clinic_ref(ref)
                if resolved is not None and not _blocked_status(resolved):
                    clinic = resolved
                    tenant_slug = resolved.slug
                    break
            if clinic is None and payload.clinic_id is not None:
                resolved = _clinic_from_token(payload)
                if resolved is not None and not _blocked_status(resolved):
                    clinic = resolved
                    tenant_slug = resolved.slug
        else:
            # Non–super-admin: ignore forged X-Tenant-ID unless it matches membership
            clinic = _clinic_from_token(payload)
            if header_tenant:
                header_clinic = resolve_clinic_ref(header_tenant)
                if header_clinic is not None:
                    # Only allow if user is a member of that clinic
                    if ClinicStaff.objects.filter(
                        user=user, clinic=header_clinic, is_active=True
                    ).exists():
                        clinic = header_clinic
            if clinic is None:
                # Token may be auth-only (no tenant yet)
                ctx = StaffAuthContext(
                    user=user, clinic=None, staff=None, role=user.role, tenant=None
                )
                request.auth = ctx  # type: ignore[attr-defined]
                return ctx
            if _blocked_status(clinic):
                return None
            try:
                staff = ClinicStaff.objects.select_related("user", "clinic").get(
                    user_id=user.id,
                    clinic_id=clinic.id,
                    is_active=True,
                )
            except ClinicStaff.DoesNotExist:
                return None
            tenant_slug = clinic.slug

        ctx = StaffAuthContext(
            user=user,
            clinic=clinic,
            staff=staff,
            role=user.role,
            tenant=tenant_slug,
        )
        request.auth = ctx  # type: ignore[attr-defined]
        return ctx


class PatientJWTAuth(HttpBearer):
    def authenticate(self, request, token: str) -> PatientAuthContext | None:
        payload: PatientTokenPayload = decode_patient_access_token(token)

        try:
            patient = Patient.objects.select_related("clinic").get(
                pk=payload.patient_id,
                clinic_id=payload.clinic_id,
            )
        except Patient.DoesNotExist:
            return None

        if _blocked_status(patient.clinic):
            return None

        ctx = PatientAuthContext(
            patient=patient,
            clinic=patient.clinic,
            session_id=payload.session_id,
        )
        request.auth = ctx  # type: ignore[attr-defined]
        return ctx


staff_jwt_auth = StaffJWTAuth()
patient_jwt_auth = PatientJWTAuth()
jwt_auth = staff_jwt_auth


def clinic_from(request: HttpRequest) -> Clinic:
    """Tenant clinic from staff JWT / X-Tenant-ID — use in clinic-scoped portal endpoints."""
    clinic = request.auth.clinic  # type: ignore[attr-defined]
    if clinic is None:
        raise HttpError(400, "Clinic context required")
    return clinic


def patient_from(request: HttpRequest) -> Patient:
    return request.auth.patient  # type: ignore[attr-defined]


def require_super_admin(request: HttpRequest) -> StaffAuthContext:
    auth = request.auth  # type: ignore[attr-defined]
    if auth.role != UserRole.SUPER_ADMIN:
        raise HttpError(403, "Super admin only")
    return auth


def client_ip(request: HttpRequest) -> str | None:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")
