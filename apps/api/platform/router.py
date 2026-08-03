"""Super Admin platform APIs — clinic list, create, status (no JWT role swap)."""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from django.db.models import Q, Sum
from django.utils import timezone
from django.utils.text import slugify
from ninja import Router, Schema
from ninja.errors import HttpError

from apps.accounts.models import AuditAction, ClinicStaff, User, UserRole
from apps.accounts.models import StaffAuthToken, StaffAuthTokenPurpose
from apps.accounts.services.audit import write_audit
from apps.api.auth.deps import client_ip, require_super_admin, staff_jwt_auth
from apps.api.auth.schemas import ClinicOut
from apps.clinics.features import default_widget_configuration
from apps.clinics.models import Clinic, ClinicStatus
from apps.notifications.service import NotificationService

router = Router(tags=["Platform — Super Admin"])


class PlatformClinicOut(Schema):
    id: UUID
    slug: str
    name: str
    email: str
    status: str
    timezone: str
    doctor_count: int = 0
    staff_count: int = 0
    document_count: int = 0
    appointment_count_30d: int = 0
    token_usage_30d: int = 0
    created_at: str


class PlatformClinicCreateIn(Schema):
    name: str
    slug: str
    email: str
    phone: str = ""
    timezone: str = "America/New_York"
    owner_email: str | None = None
    owner_password: str | None = None


class PlatformClinicPatchIn(Schema):
    status: str | None = None
    name: str | None = None


class PlatformOverviewOut(Schema):
    clinic_count: int = 0
    active_clinics: int = 0
    suspended_clinics: int = 0
    onboarding_clinics: int = 0
    appointments_30d: int = 0
    tokens_30d: int = 0
    documents: int = 0
    staff_users: int = 0
    top_clinics_by_tokens: list[dict] = []


def _require_platform(request):
    return require_super_admin(request)


@router.get("/overview", response=PlatformOverviewOut, auth=staff_jwt_auth)
def platform_overview(request):
    """Aggregate platform metrics for Super Admin overview."""
    _require_platform(request)
    from apps.ai.models import AIUsageLog
    from apps.appointments.models import Appointment
    from apps.knowledge.models import Document

    since = timezone.now() - timedelta(days=30)
    clinics = list(Clinic.objects.all())
    active = sum(1 for c in clinics if c.status == ClinicStatus.ACTIVE)
    suspended = sum(1 for c in clinics if c.status == ClinicStatus.SUSPENDED)
    onboarding = sum(1 for c in clinics if c.status == ClinicStatus.ONBOARDING)

    tokens_30d = (
        AIUsageLog.objects.filter(created_at__gte=since).aggregate(t=Sum("total_tokens"))[
            "t"
        ]
        or 0
    )
    appts_30d = Appointment.objects.filter(created_at__gte=since).count()
    docs = Document.objects.filter(is_deleted=False).count()
    staff_users = User.objects.filter(
        role__in=[UserRole.CLINIC_ADMIN, UserRole.STAFF], is_active=True
    ).count()

    top = []
    for c in clinics:
        t = (
            AIUsageLog.objects.filter(clinic=c, created_at__gte=since).aggregate(
                t=Sum("total_tokens")
            )["t"]
            or 0
        )
        top.append({"slug": c.slug, "name": c.name, "tokens_30d": int(t)})
    top.sort(key=lambda x: x["tokens_30d"], reverse=True)

    return PlatformOverviewOut(
        clinic_count=len(clinics),
        active_clinics=active,
        suspended_clinics=suspended,
        onboarding_clinics=onboarding,
        appointments_30d=appts_30d,
        tokens_30d=int(tokens_30d),
        documents=docs,
        staff_users=staff_users,
        top_clinics_by_tokens=top[:5],
    )


@router.get("/clinics", response=list[PlatformClinicOut], auth=staff_jwt_auth)
def list_clinics(request, search: str = ""):
    _require_platform(request)
    qs = Clinic.objects.all().order_by("-created_at")
    if search.strip():
        qs = qs.filter(
            Q(name__icontains=search.strip()) | Q(slug__icontains=search.strip())
        )

    since = timezone.now() - timedelta(days=30)
    rows = []
    for c in qs[:200]:
        from apps.ai.models import AIUsageLog
        from apps.appointments.models import Appointment
        from apps.doctors.models import Doctor
        from apps.knowledge.models import Document

        token_sum = (
            AIUsageLog.objects.filter(clinic=c, created_at__gte=since).aggregate(
                t=Sum("total_tokens")
            )["t"]
            or 0
        )
        rows.append(
            PlatformClinicOut(
                id=c.id,
                slug=c.slug,
                name=c.name,
                email=c.email,
                status=c.status,
                timezone=c.timezone,
                doctor_count=Doctor.objects.filter(
                    clinic=c, is_deleted=False
                ).count(),
                staff_count=ClinicStaff.objects.filter(clinic=c, is_active=True).count(),
                document_count=Document.objects.filter(
                    clinic=c, is_deleted=False
                ).count(),
                appointment_count_30d=Appointment.objects.filter(
                    clinic=c, created_at__gte=since
                ).count(),
                token_usage_30d=int(token_sum),
                created_at=c.created_at.isoformat(),
            )
        )
    return rows


@router.post("/clinics", response=ClinicOut, auth=staff_jwt_auth)
def create_clinic(request, payload: PlatformClinicCreateIn):
    auth = _require_platform(request)
    slug = slugify(payload.slug or payload.name)[:64]
    if Clinic.objects.filter(slug=slug).exists():
        raise HttpError(400, "Clinic slug already taken")

    clinic = Clinic.objects.create(
        slug=slug,
        name=payload.name.strip(),
        email=payload.email.strip(),
        phone=(payload.phone or "").strip(),
        timezone=payload.timezone or "America/New_York",
        status=ClinicStatus.ONBOARDING,
    )
    from apps.widget.models import WidgetSettings

    WidgetSettings.objects.create(
        clinic=clinic, configuration=default_widget_configuration()
    )

    if payload.owner_email:
        email = payload.owner_email.strip().lower()
        owner, created = User.objects.get_or_create(
            email=email,
            defaults={
                "username": email.split("@")[0][:40],
                "role": UserRole.CLINIC_ADMIN,
                "is_clinic_owner": True,
                "is_active": True,
                "email_verified_at": timezone.now(),
            },
        )
        if created:
            pwd = payload.owner_password or "ChangeMe123!"
            owner.set_password(pwd)
            owner.save()
            _, raw = StaffAuthToken.issue(
                user=owner, purpose=StaffAuthTokenPurpose.PASSWORD_RESET, ttl_hours=48
            )
            NotificationService.send_password_reset_email(to=email, token=raw)
        ClinicStaff.objects.get_or_create(
            user=owner, clinic=clinic, defaults={"is_active": True}
        )

    write_audit(
        action=AuditAction.CLINIC_CREATE,
        actor=auth.user,
        clinic=clinic,
        object_type="clinic",
        object_id=str(clinic.id),
        ip_address=client_ip(request),
    )
    return ClinicOut(
        id=clinic.id,
        slug=clinic.slug,
        name=clinic.name,
        timezone=clinic.timezone,
        status=clinic.status,
    )


@router.patch("/clinics/{clinic_id}", response=ClinicOut, auth=staff_jwt_auth)
def patch_clinic(request, clinic_id: UUID, payload: PlatformClinicPatchIn):
    auth = _require_platform(request)
    try:
        clinic = Clinic.objects.get(pk=clinic_id)
    except Clinic.DoesNotExist:
        raise HttpError(404, "Clinic not found") from None

    if payload.name:
        clinic.name = payload.name.strip()
    if payload.status:
        if payload.status not in {c.value for c in ClinicStatus}:
            raise HttpError(400, "Invalid status")
        old = clinic.status
        clinic.status = payload.status
        write_audit(
            action=AuditAction.CLINIC_STATUS,
            actor=auth.user,
            clinic=clinic,
            metadata={"from": old, "to": payload.status},
            ip_address=client_ip(request),
        )
    clinic.save()
    return ClinicOut(
        id=clinic.id,
        slug=clinic.slug,
        name=clinic.name,
        timezone=clinic.timezone,
        status=clinic.status,
    )
