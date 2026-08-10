"""Staff / admin authentication — verify-first register, tenant select, Super Admin header context."""

from __future__ import annotations

import re

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify
from ninja import Router
from ninja.errors import HttpError

from apps.accounts.models import (
    AuditAction,
    ClinicStaff,
    StaffAuthToken,
    StaffAuthTokenPurpose,
    UserRole,
)
from apps.accounts.services.audit import write_audit
from apps.api.auth.deps import (
    client_ip,
    require_super_admin,
    resolve_clinic_ref,
    staff_jwt_auth,
)
from apps.api.auth.jwt import (
    create_staff_access_token,
    create_staff_refresh_token,
    decode_staff_token,
)
from apps.api.auth.schemas import (
    ChangePasswordIn,
    ClinicOut,
    CreateClinicIn,
    EnterClinicIn,
    ForgotPasswordIn,
    MeOut,
    MessageOut,
    RefreshIn,
    ResendVerificationIn,
    ResetPasswordIn,
    SelectTenantIn,
    StaffLoginIn,
    StaffRegisterIn,
    StaffTokenOut,
    TenantOut,
    TokenIn,
    UserOut,
)
from apps.clinics.features import default_widget_configuration
from apps.clinics.models import Clinic, ClinicStatus
from apps.notifications.service import NotificationService

User = get_user_model()
router = Router(tags=["Auth — Staff"])

_PASSWORD_MIN = 8


def _user_out(user) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
        role=user.role,
        is_clinic_owner=user.is_clinic_owner,
        email_verified=bool(user.email_verified_at),
        email_verified_at=user.email_verified_at,
    )


def _clinic_out(clinic: Clinic) -> ClinicOut:
    return ClinicOut(
        id=clinic.id,
        slug=clinic.slug,
        name=clinic.name,
        timezone=clinic.timezone,
        status=clinic.status,
        clinic_type=clinic.clinic_type,
        phone=clinic.phone,
        address=clinic.address or {},
        onboarding_step=clinic.onboarding_step,
        onboarding_completed_at=clinic.onboarding_completed_at,
    )


def _tenants_for(user) -> list[TenantOut]:
    if user.role == UserRole.SUPER_ADMIN:
        return []
    rows = (
        ClinicStaff.objects.filter(user=user, is_active=True)
        .select_related("clinic")
        .order_by("clinic__name")
    )
    return [
        TenantOut(
            slug=m.clinic.slug,
            name=m.clinic.name,
            status=m.clinic.status,
            role=user.role,
        )
        for m in rows
        if m.clinic.status != ClinicStatus.CANCELLED
    ]


def _issue_tokens(*, user, clinic: Clinic | None = None) -> StaffTokenOut:
    tenant = clinic.slug if clinic else None
    clinic_id = clinic.id if clinic else None
    access = create_staff_access_token(
        user_id=user.id, role=user.role, tenant=tenant, clinic_id=clinic_id
    )
    refresh = create_staff_refresh_token(
        user_id=user.id, role=user.role, tenant=tenant, clinic_id=clinic_id
    )
    return StaffTokenOut(
        access_token=access,
        refresh_token=refresh,
        expires_in_minutes=settings.JWT_STAFF_ACCESS_TOKEN_EXPIRE_MINUTES,
        user=_user_out(user),
        clinic=_clinic_out(clinic) if clinic else None,
        tenant=tenant,
        tenants=_tenants_for(user),
    )


def _validate_password(password: str) -> None:
    if len(password or "") < _PASSWORD_MIN:
        raise HttpError(400, f"Password must be at least {_PASSWORD_MIN} characters")


def _unique_username(email: str) -> str:
    base = slugify(email.split("@")[0])[:40] or "user"
    candidate = base
    n = 1
    while User.objects.filter(username=candidate).exists():
        candidate = f"{base}{n}"
        n += 1
    return candidate


@router.post("/register", response=MessageOut, auth=None)
def register(request, payload: StaffRegisterIn):
    """Create staff user only — clinic is created after email verification."""
    email = (payload.email or "").strip().lower()
    if not email or "@" not in email:
        raise HttpError(400, "Valid email is required")
    _validate_password(payload.password)
    if User.objects.filter(email=email).exists():
        # Do not reveal — still pretend success after silent no-op? Better: conflict.
        raise HttpError(400, "Unable to register with this email")

    user = User.objects.create_user(
        username=_unique_username(email),
        email=email,
        password=payload.password,
        first_name=(payload.first_name or "").strip(),
        last_name=(payload.last_name or "").strip(),
        role=UserRole.CLINIC_ADMIN,
        is_clinic_owner=True,
        is_active=False,
    )
    _, raw = StaffAuthToken.issue(
        user=user, purpose=StaffAuthTokenPurpose.EMAIL_VERIFY, ttl_hours=24
    )
    NotificationService.send_staff_verify_email(
        to=email, token=raw, first_name=user.first_name
    )
    write_audit(
        action=AuditAction.REGISTER,
        actor=user,
        metadata={"email": email},
        ip_address=client_ip(request),
    )
    return MessageOut(
        message="Check your email to verify your account before continuing."
    )


@router.post("/verify-email", response=MessageOut, auth=None)
def verify_email(request, payload: TokenIn):
    token_hash = StaffAuthToken.hash_token(payload.token.strip())
    row = (
        StaffAuthToken.objects.select_related("user")
        .filter(token_hash=token_hash, purpose=StaffAuthTokenPurpose.EMAIL_VERIFY)
        .first()
    )
    if row is None or not row.is_valid:
        raise HttpError(400, "Invalid or expired verification link")
    user = row.user
    user.email_verified_at = timezone.now()
    user.is_active = True
    user.save(update_fields=["email_verified_at", "is_active"])
    row.mark_used()
    write_audit(
        action=AuditAction.EMAIL_VERIFY,
        actor=user,
        ip_address=client_ip(request),
    )
    return MessageOut(message="Email verified. You can sign in and create your clinic.")


@router.post("/resend-verification", response=MessageOut, auth=None)
def resend_verification(request, payload: ResendVerificationIn):
    email = (payload.email or "").strip().lower()
    user = User.objects.filter(email=email).first()
    if user and not user.email_verified_at:
        _, raw = StaffAuthToken.issue(
            user=user, purpose=StaffAuthTokenPurpose.EMAIL_VERIFY, ttl_hours=24
        )
        NotificationService.send_staff_verify_email(
            to=email, token=raw, first_name=user.first_name
        )
    return MessageOut(message="If that account needs verification, we sent an email.")


@router.post("/forgot-password", response=MessageOut, auth=None)
def forgot_password(request, payload: ForgotPasswordIn):
    email = (payload.email or "").strip().lower()
    user = User.objects.filter(email=email, is_active=True).first()
    if user:
        _, raw = StaffAuthToken.issue(
            user=user, purpose=StaffAuthTokenPurpose.PASSWORD_RESET, ttl_hours=2
        )
        NotificationService.send_password_reset_email(to=email, token=raw)
        write_audit(
            action=AuditAction.PASSWORD_RESET,
            actor=user,
            metadata={"stage": "requested"},
            ip_address=client_ip(request),
        )
    return MessageOut(
        message="If an account exists for that email, we sent a reset link."
    )


@router.post("/reset-password", response=MessageOut, auth=None)
def reset_password(request, payload: ResetPasswordIn):
    _validate_password(payload.password)
    token_hash = StaffAuthToken.hash_token(payload.token.strip())
    row = (
        StaffAuthToken.objects.select_related("user")
        .filter(token_hash=token_hash, purpose=StaffAuthTokenPurpose.PASSWORD_RESET)
        .first()
    )
    if row is None or not row.is_valid:
        raise HttpError(400, "Invalid or expired reset link")
    user = row.user
    user.set_password(payload.password)
    user.save(update_fields=["password"])
    row.mark_used()
    StaffAuthToken.objects.filter(
        user=user, purpose=StaffAuthTokenPurpose.PASSWORD_RESET, used_at__isnull=True
    ).update(used_at=timezone.now())
    write_audit(
        action=AuditAction.PASSWORD_RESET,
        actor=user,
        metadata={"stage": "completed"},
        ip_address=client_ip(request),
    )
    return MessageOut(message="Password updated. You can sign in.")


@router.post("/change-password", response=MessageOut, auth=staff_jwt_auth)
def change_password(request, payload: ChangePasswordIn):
    user = request.auth.user
    if not user.check_password(payload.current_password):
        raise HttpError(400, "Current password is incorrect")
    _validate_password(payload.new_password)
    user.set_password(payload.new_password)
    user.save(update_fields=["password"])
    write_audit(
        action=AuditAction.PASSWORD_CHANGE,
        actor=user,
        clinic=request.auth.clinic,
        ip_address=client_ip(request),
    )
    return MessageOut(message="Password changed.")


@router.post("/login", response=StaffTokenOut, auth=None)
def login(request, payload: StaffLoginIn):
    """Authenticate only — tenant selected afterward (or via X-Tenant-ID for Super Admin)."""
    email = (payload.email or "").strip().lower()
    user = authenticate(request, username=email, password=payload.password)
    if user is None:
        raise HttpError(401, "Invalid credentials")
    if not user.is_active:
        raise HttpError(403, "Account is inactive. Verify your email first.")
    if user.role != UserRole.SUPER_ADMIN and not user.email_verified_at:
        # Legacy seeded users may lack email_verified_at — treat is_active staff as ok
        if not user.is_staff:
            raise HttpError(403, "Verify your email before signing in.")

    clinic = None
    # Optional legacy clinic_slug still accepted to jump straight into a tenant
    if payload.clinic_slug:
        clinic = resolve_clinic_ref(payload.clinic_slug)
        if clinic is None:
            raise HttpError(401, "Invalid credentials")
        if clinic.status in {ClinicStatus.SUSPENDED, ClinicStatus.CANCELLED}:
            raise HttpError(403, "Clinic is suspended")
        if user.role != UserRole.SUPER_ADMIN:
            if not ClinicStaff.objects.filter(
                user=user, clinic=clinic, is_active=True
            ).exists():
                raise HttpError(401, "Invalid credentials")

    user.last_login_ip = client_ip(request)
    user.save(update_fields=["last_login_ip"])
    write_audit(
        action=AuditAction.LOGIN,
        actor=user,
        clinic=clinic,
        ip_address=client_ip(request),
    )
    # Auto-verify legacy demo accounts on first login
    if user.email_verified_at is None and user.is_active:
        user.email_verified_at = timezone.now()
        user.save(update_fields=["email_verified_at"])

    return _issue_tokens(user=user, clinic=clinic)


@router.post("/refresh", response=StaffTokenOut, auth=None)
def refresh(request, payload: RefreshIn):
    token_payload = decode_staff_token(
        payload.refresh_token, expected_type="staff_refresh"
    )
    try:
        user = User.objects.get(pk=token_payload.user_id, is_active=True)
    except User.DoesNotExist:
        raise HttpError(401, "Invalid credentials") from None
    if user.role != token_payload.role:
        raise HttpError(401, "Invalid credentials")

    clinic = None
    if token_payload.tenant:
        clinic = resolve_clinic_ref(token_payload.tenant)
    elif token_payload.clinic_id is not None:
        clinic = Clinic.objects.filter(pk=token_payload.clinic_id).first()

    if clinic and clinic.status in {ClinicStatus.SUSPENDED, ClinicStatus.CANCELLED}:
        raise HttpError(403, "Clinic is suspended")
    if clinic and user.role != UserRole.SUPER_ADMIN:
        if not ClinicStaff.objects.filter(
            user=user, clinic=clinic, is_active=True
        ).exists():
            raise HttpError(401, "Invalid credentials")

    return _issue_tokens(user=user, clinic=clinic)


@router.get("/me", response=MeOut, auth=staff_jwt_auth)
def me(request):
    auth = request.auth
    return MeOut(
        user=_user_out(auth.user),
        clinic=_clinic_out(auth.clinic) if auth.clinic else None,
        tenant=auth.tenant,
        tenants=_tenants_for(auth.user),
        can_exit_clinic=auth.role == UserRole.SUPER_ADMIN and auth.clinic is not None,
    )


@router.get("/tenants", response=list[TenantOut], auth=staff_jwt_auth)
def list_tenants(request):
    return _tenants_for(request.auth.user)


@router.post("/tenants/select", response=StaffTokenOut, auth=staff_jwt_auth)
def select_tenant(request, payload: SelectTenantIn):
    user = request.auth.user
    clinic = resolve_clinic_ref(payload.tenant)
    if clinic is None:
        raise HttpError(404, "Clinic not found")
    if clinic.status in {ClinicStatus.SUSPENDED, ClinicStatus.CANCELLED}:
        raise HttpError(403, "Clinic is not available")
    if user.role == UserRole.SUPER_ADMIN:
        raise HttpError(
            400,
            "Super admin should use enter-clinic and send X-Tenant-ID instead",
        )
    if not ClinicStaff.objects.filter(
        user=user, clinic=clinic, is_active=True
    ).exists():
        raise HttpError(403, "Not a member of this clinic")
    write_audit(
        action=AuditAction.TENANT_SELECT,
        actor=user,
        clinic=clinic,
        ip_address=client_ip(request),
    )
    return _issue_tokens(user=user, clinic=clinic)


@router.post("/clinics", response=ClinicOut, auth=staff_jwt_auth)
def create_clinic(request, payload: CreateClinicIn):
    """Verified owner creates their clinic (after email verify).

    Atomicity is applied inline (not via @transaction.atomic on the view)
    because Django Ninja introspects the view's signature to resolve the
    request body model, and a function-decorator here breaks that
    resolution (`QueryParams is not fully defined`) on this ninja/pydantic
    version combo.
    """
    user = request.auth.user
    if user.role == UserRole.SUPER_ADMIN:
        raise HttpError(400, "Use platform clinic create for super admin")
    if not user.email_verified_at:
        raise HttpError(403, "Verify your email before creating a clinic")

    slug = slugify(payload.slug or payload.name)[:64]
    if not slug or not re.match(r"^[a-z0-9]+(?:-[a-z0-9]+)*$", slug):
        raise HttpError(400, "Invalid clinic slug")
    if Clinic.objects.filter(slug=slug).exists():
        raise HttpError(400, "Clinic slug already taken")

    with transaction.atomic():
        clinic = Clinic.objects.create(
            slug=slug,
            name=payload.name.strip(),
            email=(payload.email or user.email).strip(),
            phone=(payload.phone or "").strip(),
            timezone=payload.timezone or "America/New_York",
            status=ClinicStatus.ONBOARDING,
        )
        ClinicStaff.objects.create(user=user, clinic=clinic, is_active=True)
        user.role = UserRole.CLINIC_ADMIN
        user.is_clinic_owner = True
        user.save(update_fields=["role", "is_clinic_owner"])

        from apps.widget.models import WidgetSettings

        WidgetSettings.objects.create(
            clinic=clinic, configuration=default_widget_configuration()
        )
    write_audit(
        action=AuditAction.CLINIC_CREATE,
        actor=user,
        clinic=clinic,
        object_type="clinic",
        object_id=str(clinic.id),
        ip_address=client_ip(request),
    )
    return _clinic_out(clinic)


@router.post("/enter-clinic", response=StaffTokenOut, auth=staff_jwt_auth)
def enter_clinic(request, payload: EnterClinicIn):
    """Super Admin: enter a clinic — re-issue JWT with tenant (role stays SUPER_ADMIN)."""
    require_super_admin(request)
    clinic = resolve_clinic_ref(payload.tenant)
    if clinic is None:
        raise HttpError(404, "Clinic not found")
    if clinic.status in {ClinicStatus.SUSPENDED, ClinicStatus.CANCELLED}:
        raise HttpError(403, "Clinic is not available")
    write_audit(
        action=AuditAction.ENTER_CLINIC,
        actor=request.auth.user,
        clinic=clinic,
        ip_address=client_ip(request),
    )
    return _issue_tokens(user=request.auth.user, clinic=clinic)


@router.post("/exit-clinic", response=StaffTokenOut, auth=staff_jwt_auth)
def exit_clinic(request):
    """Super Admin: leave clinic context — re-issue JWT with tenant cleared."""
    require_super_admin(request)
    write_audit(
        action=AuditAction.EXIT_CLINIC,
        actor=request.auth.user,
        clinic=request.auth.clinic,
        ip_address=client_ip(request),
    )
    return _issue_tokens(user=request.auth.user, clinic=None)
