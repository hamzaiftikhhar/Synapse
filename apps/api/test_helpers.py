"""Shared staff-auth test helpers for the Django Ninja API test suite."""

from __future__ import annotations

from django.contrib.auth import get_user_model

from apps.accounts.models import ClinicStaff, UserRole
from apps.api.auth.jwt import create_staff_access_token
from apps.clinics.models import Clinic, ClinicStatus

User = get_user_model()


def make_verified_owner(*, email: str) -> tuple:
    """Create a verified CLINIC_ADMIN user with no clinic yet + auth headers."""
    user = User.objects.create_user(
        username=email.split("@")[0],
        email=email,
        password="Sup3rSecret!",
        role=UserRole.CLINIC_ADMIN,
        is_clinic_owner=True,
        is_active=True,
    )
    from django.utils import timezone

    user.email_verified_at = timezone.now()
    user.save(update_fields=["email_verified_at"])
    token = create_staff_access_token(user_id=user.id, role=user.role, tenant=None, clinic_id=None)
    return user, {"Authorization": f"Bearer {token}"}


def make_clinic_admin(*, email: str, clinic_slug: str, clinic_name: str = "") -> tuple:
    """Create a verified CLINIC_ADMIN user + their clinic + membership.

    Returns (user, clinic, auth_headers).
    """
    user = User.objects.create_user(
        username=email.split("@")[0],
        email=email,
        password="Sup3rSecret!",
        role=UserRole.CLINIC_ADMIN,
        is_clinic_owner=True,
        is_active=True,
    )
    clinic = Clinic.objects.create(
        slug=clinic_slug,
        name=clinic_name or clinic_slug,
        email=email,
        status=ClinicStatus.ONBOARDING,
    )
    ClinicStaff.objects.create(user=user, clinic=clinic, is_active=True)
    token = create_staff_access_token(
        user_id=user.id, role=user.role, tenant=clinic.slug, clinic_id=clinic.id
    )
    return user, clinic, {"Authorization": f"Bearer {token}"}
