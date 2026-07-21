"""Staff / admin authentication endpoints (email + password + refresh JWT)."""

from django.conf import settings
from django.contrib.auth import authenticate
from ninja import Router
from ninja.errors import HttpError

from apps.accounts.models import ClinicStaff, UserRole
from apps.api.auth.deps import staff_jwt_auth
from apps.api.auth.jwt import (
    create_staff_access_token,
    create_staff_refresh_token,
    decode_staff_token,
)
from apps.api.auth.schemas import (
    ClinicOut,
    MeOut,
    RefreshIn,
    StaffLoginIn,
    StaffTokenOut,
    UserOut,
)
from apps.clinics.models import Clinic, ClinicStatus

router = Router(tags=["Auth — Staff"])


def _user_out(user) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
        role=user.role,
        is_clinic_owner=user.is_clinic_owner,
    )


def _clinic_out(clinic: Clinic) -> ClinicOut:
    return ClinicOut(
        id=clinic.id,
        slug=clinic.slug,
        name=clinic.name,
        timezone=clinic.timezone,
    )


def _issue_staff_tokens(*, user, clinic: Clinic | None) -> StaffTokenOut:
    clinic_id = clinic.id if clinic else None
    access = create_staff_access_token(
        user_id=user.id, clinic_id=clinic_id, role=user.role
    )
    refresh = create_staff_refresh_token(
        user_id=user.id, clinic_id=clinic_id, role=user.role
    )
    return StaffTokenOut(
        access_token=access,
        refresh_token=refresh,
        expires_in_minutes=settings.JWT_STAFF_ACCESS_TOKEN_EXPIRE_MINUTES,
        user=_user_out(user),
        clinic=_clinic_out(clinic) if clinic else None,
    )


@router.post("/login", response=StaffTokenOut, auth=None)
def login(request, payload: StaffLoginIn):
    """
    Clinic staff login (email + password).

    Returns access + refresh JWTs scoped to the clinic (except SUPER_ADMIN).
    Patient/widget clients must use /widget/otp/* instead.
    """
    try:
        clinic = Clinic.objects.get(slug=payload.clinic_slug)
    except Clinic.DoesNotExist:
        raise HttpError(401, "Invalid credentials") from None

    if clinic.status == ClinicStatus.SUSPENDED:
        raise HttpError(403, "Clinic is suspended")

    # USERNAME_FIELD is email — authenticate with username=email
    user = authenticate(
        request,
        username=payload.email,
        password=payload.password,
    )
    if user is None:
        raise HttpError(401, "Invalid credentials")

    if user.role == UserRole.SUPER_ADMIN:
        return _issue_staff_tokens(user=user, clinic=clinic)

    if not ClinicStaff.objects.filter(
        user=user, clinic=clinic, is_active=True
    ).exists():
        raise HttpError(401, "Invalid credentials")

    return _issue_staff_tokens(user=user, clinic=clinic)


@router.post("/refresh", response=StaffTokenOut, auth=None)
def refresh(request, payload: RefreshIn):
    """Exchange a staff refresh token for a new access + refresh pair."""
    token_payload = decode_staff_token(
        payload.refresh_token, expected_type="staff_refresh"
    )

    from django.contrib.auth import get_user_model

    User = get_user_model()
    try:
        user = User.objects.get(pk=token_payload.user_id, is_active=True)
    except User.DoesNotExist:
        raise HttpError(401, "Invalid credentials") from None

    if user.role != token_payload.role:
        raise HttpError(401, "Invalid credentials")

    clinic: Clinic | None = None
    if token_payload.clinic_id is not None:
        try:
            clinic = Clinic.objects.get(pk=token_payload.clinic_id)
        except Clinic.DoesNotExist:
            raise HttpError(401, "Invalid credentials") from None
        if clinic.status == ClinicStatus.SUSPENDED:
            raise HttpError(403, "Clinic is suspended")

        if user.role != UserRole.SUPER_ADMIN:
            if not ClinicStaff.objects.filter(
                user=user, clinic=clinic, is_active=True
            ).exists():
                raise HttpError(401, "Invalid credentials")

    return _issue_staff_tokens(user=user, clinic=clinic)


@router.get("/me", response=MeOut, auth=staff_jwt_auth)
def me(request):
    """Return the current staff user and clinic from the staff JWT."""
    auth = request.auth
    return MeOut(
        user=_user_out(auth.user),
        clinic=_clinic_out(auth.clinic) if auth.clinic else None,
    )
