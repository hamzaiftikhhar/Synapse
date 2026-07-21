"""Auth dependencies — StaffJWTAuth vs PatientJWTAuth (independent systems)."""

from __future__ import annotations

from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.http import HttpRequest
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


@dataclass
class StaffAuthContext:
    """Resolved identity for a protected staff/admin API request."""

    user: User  # type: ignore[valid-type]
    clinic: Clinic | None
    staff: ClinicStaff | None
    role: str


@dataclass
class PatientAuthContext:
    """Resolved identity for a protected patient widget API request."""

    patient: Patient
    clinic: Clinic
    session_id: object | None


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

        if user.role == UserRole.SUPER_ADMIN:
            # Platform admin — no clinic membership required
            if payload.clinic_id is not None:
                try:
                    clinic = Clinic.objects.get(pk=payload.clinic_id)
                except Clinic.DoesNotExist:
                    return None
                if clinic.status == ClinicStatus.SUSPENDED:
                    return None
        else:
            if payload.clinic_id is None:
                return None
            try:
                staff = (
                    ClinicStaff.objects.select_related("user", "clinic")
                    .get(
                        user_id=payload.user_id,
                        clinic_id=payload.clinic_id,
                        is_active=True,
                    )
                )
            except ClinicStaff.DoesNotExist:
                return None
            clinic = staff.clinic
            if clinic.status == ClinicStatus.SUSPENDED:
                return None

        ctx = StaffAuthContext(
            user=user, clinic=clinic, staff=staff, role=user.role
        )
        request.auth = ctx  # type: ignore[attr-defined]
        return ctx


class PatientJWTAuth(HttpBearer):
    """Validate patient Bearer JWT. Rejects staff tokens. Zero admin permissions."""

    def authenticate(self, request, token: str) -> PatientAuthContext | None:
        payload: PatientTokenPayload = decode_patient_access_token(token)

        try:
            patient = Patient.objects.select_related("clinic").get(
                pk=payload.patient_id,
                clinic_id=payload.clinic_id,
            )
        except Patient.DoesNotExist:
            return None

        if patient.clinic.status == ClinicStatus.SUSPENDED:
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

# Backwards-compatible alias used by existing portal routers
jwt_auth = staff_jwt_auth


def clinic_from(request: HttpRequest) -> Clinic:
    """Tenant clinic from staff JWT — use in all clinic-scoped portal endpoints."""
    clinic = request.auth.clinic  # type: ignore[attr-defined]
    if clinic is None:
        from ninja.errors import HttpError

        raise HttpError(400, "Clinic context required")
    return clinic


def patient_from(request: HttpRequest) -> Patient:
    """Authenticated patient from patient JWT."""
    return request.auth.patient  # type: ignore[attr-defined]
