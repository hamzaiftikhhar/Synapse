"""Authentication endpoints."""

from django.conf import settings
from django.contrib.auth import authenticate
from ninja import Router
from ninja.errors import HttpError

from apps.accounts.models import ClinicStaff
from apps.api.auth.deps import clinic_from, jwt_auth
from apps.api.auth.jwt import create_access_token
from apps.api.auth.schemas import ClinicOut, LoginIn, LoginOut, MeOut, UserOut
from apps.clinics.models import Clinic, ClinicStatus

router = Router(tags=["Auth"])


def _user_out(user) -> UserOut:
    return UserOut(
        id=user.id,
        username=user.username,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
    )


def _clinic_out(clinic: Clinic) -> ClinicOut:
    return ClinicOut(
        id=clinic.id,
        slug=clinic.slug,
        name=clinic.name,
        timezone=clinic.timezone,
    )


@router.post("/login", response=LoginOut, auth=None)
def login(request, payload: LoginIn):
    """
    Clinic staff login.

    Returns a JWT scoped to the clinic. All other endpoints require this token.
    """
    try:
        clinic = Clinic.objects.get(slug=payload.clinic_slug)
    except Clinic.DoesNotExist:
        raise HttpError(401, "Invalid credentials") from None

    if clinic.status == ClinicStatus.SUSPENDED:
        raise HttpError(403, "Clinic is suspended")

    user = authenticate(request, username=payload.username, password=payload.password)
    if user is None:
        raise HttpError(401, "Invalid credentials")

    if not ClinicStaff.objects.filter(
        user=user, clinic=clinic, is_active=True
    ).exists():
        raise HttpError(401, "Invalid credentials")

    token = create_access_token(user_id=user.id, clinic_id=clinic.id)
    return LoginOut(
        access_token=token,
        expires_in_minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES,
        user=_user_out(user),
        clinic=_clinic_out(clinic),
    )


@router.get("/me", response=MeOut, auth=jwt_auth)
def me(request):
    """Return the current user and clinic from the JWT."""
    auth = request.auth
    return MeOut(user=_user_out(auth.user), clinic=_clinic_out(auth.clinic))
