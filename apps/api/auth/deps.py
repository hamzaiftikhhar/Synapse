"""Auth dependencies — JWT bearer + clinic tenant isolation."""

from __future__ import annotations

from dataclasses import dataclass

from django.contrib.auth.models import User
from django.http import HttpRequest
from ninja.security import HttpBearer

from apps.accounts.models import ClinicStaff
from apps.api.auth.jwt import TokenPayload, decode_access_token
from apps.clinics.models import Clinic, ClinicStatus


@dataclass
class AuthContext:
    """Resolved identity for a protected API request."""

    user: User
    clinic: Clinic
    staff: ClinicStaff


class JWTAuth(HttpBearer):
    """Validate Authorization: Bearer <jwt> and resolve clinic tenant."""

    def authenticate(self, request, token: str) -> AuthContext | None:
        payload: TokenPayload = decode_access_token(token)

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

        if not staff.user.is_active:
            return None

        if staff.clinic.status == ClinicStatus.SUSPENDED:
            return None

        ctx = AuthContext(user=staff.user, clinic=staff.clinic, staff=staff)
        request.auth = ctx  # type: ignore[attr-defined]
        return ctx


jwt_auth = JWTAuth()


def clinic_from(request: HttpRequest) -> Clinic:
    """Tenant clinic from JWT — use in all protected endpoints."""
    return request.auth.clinic  # type: ignore[attr-defined]
