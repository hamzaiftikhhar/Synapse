"""Super Admin platform APIs — clinic list, create, status (no JWT role swap)."""

from __future__ import annotations

import logging
from datetime import timedelta
from uuid import UUID

from django.db.models import Avg, Q, Sum
from django.utils import timezone
from django.utils.text import slugify
from ninja import Query, Router, Schema
from ninja.errors import HttpError

from apps.accounts.models import AuditAction, ClinicStaff, User, UserRole
from apps.accounts.models import StaffAuthToken, StaffAuthTokenPurpose
from apps.accounts.services.audit import write_audit
from apps.api.auth.deps import client_ip, require_super_admin, staff_jwt_auth
from apps.api.auth.schemas import ClinicOut
from apps.clinics.features import default_widget_configuration
from apps.clinics.models import Clinic, ClinicApplication, ClinicApplicationStatus, ClinicStatus
from apps.notifications.service import NotificationService

logger = logging.getLogger(__name__)

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
    pending_applications: int = 0
    active_subscriptions: int = 0
    failed_documents: int = 0
    avg_latency_ms_30d: int = 0
    top_clinics_by_tokens: list[dict] = []


class PlatformClinicUsageOut(Schema):
    clinic_id: str
    name: str
    slug: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    calls: int
    estimated_usd: float


class PlatformModelUsageOut(Schema):
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    calls: int
    estimated_usd: float


class PlatformDailyUsageOut(Schema):
    date: str
    total_tokens: int
    calls: int


class PlatformRateCardOut(Schema):
    model: str
    input_usd_per_1m: float
    output_usd_per_1m: float


class PlatformAiUsageOut(Schema):
    days: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    calls: int
    estimated_usd: float
    clinics: list[PlatformClinicUsageOut]
    models: list[PlatformModelUsageOut]
    daily: list[PlatformDailyUsageOut]
    rates: list[PlatformRateCardOut]


class ClinicApplicationOut(Schema):
    id: UUID
    clinic_name: str
    owner_name: str
    work_email: str
    phone: str
    website: str
    num_doctors: int | None = None
    current_scheduling_system: str
    notes: str
    plan_slug: str
    source: str
    status: str
    rejection_reason: str = ""
    converted_clinic_id: UUID | None = None
    created_at: str


class ApproveApplicationIn(Schema):
    # Auto-derived from clinic_name if omitted — override only if the
    # applicant's name collides or needs adjusting before provisioning.
    slug: str | None = None
    # Required when the application has no plan_slug of its own (demo
    # requests never ask the visitor to pick one) — ignored otherwise.
    plan_slug: str | None = None


class RejectApplicationIn(Schema):
    reason: str = ""


class ApplicationActionOut(Schema):
    application: ClinicApplicationOut
    clinic: ClinicOut | None = None


def _application_out(app: ClinicApplication) -> ClinicApplicationOut:
    return ClinicApplicationOut(
        id=app.id,
        clinic_name=app.clinic_name,
        owner_name=app.owner_name,
        work_email=app.work_email,
        phone=app.phone,
        website=app.website,
        num_doctors=app.num_doctors,
        current_scheduling_system=app.current_scheduling_system,
        notes=app.notes,
        plan_slug=app.plan_slug,
        source=app.source,
        status=app.status,
        rejection_reason=app.rejection_reason,
        converted_clinic_id=app.converted_clinic_id,
        created_at=app.created_at.isoformat(),
    )


def _require_platform(request):
    return require_super_admin(request)


@router.get("/overview", response=PlatformOverviewOut, auth=staff_jwt_auth)
def platform_overview(request):
    """Aggregate platform metrics for Super Admin overview."""
    _require_platform(request)
    from apps.ai.models import AIUsageLog
    from apps.appointments.models import Appointment
    from apps.billing.models import Subscription, SubscriptionStatus
    from apps.knowledge.models import Document, DocumentStatus

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
    pending_apps = ClinicApplication.objects.filter(
        status__in=[ClinicApplicationStatus.PENDING, ClinicApplicationStatus.REVIEWING]
    ).count()
    active_subs = Subscription.objects.filter(
        status__in=[SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIALING]
    ).count()
    failed_docs = Document.objects.filter(
        is_deleted=False, status=DocumentStatus.FAILED
    ).count()
    avg_latency = (
        AIUsageLog.objects.filter(created_at__gte=since, latency_ms__gt=0).aggregate(
            a=Avg("latency_ms")
        )["a"]
        or 0
    )

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
        pending_applications=pending_apps,
        active_subscriptions=active_subs,
        failed_documents=failed_docs,
        avg_latency_ms_30d=int(avg_latency),
        top_clinics_by_tokens=top[:5],
    )


@router.get("/ai-usage", response=PlatformAiUsageOut, auth=staff_jwt_auth)
def platform_ai_usage(request, days: int = Query(30, ge=1, le=90)):
    """Cross-tenant token + estimated OpenAI spend. Super Admin only."""
    _require_platform(request)
    from apps.ai.services.analytics import platform_by_clinic, summarize_usage

    summary = summarize_usage(clinic_id=None, days=days)
    return PlatformAiUsageOut(
        days=summary["days"],
        prompt_tokens=summary["prompt_tokens"],
        completion_tokens=summary["completion_tokens"],
        total_tokens=summary["total_tokens"],
        calls=summary["calls"],
        estimated_usd=summary["estimated_usd"],
        clinics=platform_by_clinic(days=days),
        models=summary["models"],
        daily=summary["daily"],
        rates=summary["rates"],
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


# ── Clinic applications (Get Started intake review) ─────────────────────────


@router.get("/applications", response=list[ClinicApplicationOut], auth=staff_jwt_auth)
def list_applications(request, status: str = ""):
    _require_platform(request)
    qs = ClinicApplication.objects.all().order_by("-created_at")
    if status.strip():
        qs = qs.filter(status=status.strip())
    return [_application_out(a) for a in qs[:200]]


@router.get("/applications/{application_id}", response=ClinicApplicationOut, auth=staff_jwt_auth)
def get_application(request, application_id: UUID):
    _require_platform(request)
    try:
        app = ClinicApplication.objects.get(pk=application_id)
    except ClinicApplication.DoesNotExist:
        raise HttpError(404, "Application not found") from None
    return _application_out(app)


def _unique_slug(base: str) -> str:
    slug = slugify(base)[:60] or "clinic"
    candidate = slug
    n = 1
    while Clinic.objects.filter(slug=candidate).exists():
        candidate = f"{slug}-{n}"[:64]
        n += 1
    return candidate


@router.post(
    "/applications/{application_id}/approve", response=ApplicationActionOut, auth=staff_jwt_auth
)
def approve_application(request, application_id: UUID, payload: ApproveApplicationIn):
    """Provision Clinic + owner ClinicStaff + a pending Subscription for the
    requested plan, then invite the owner. Payment is NOT collected here —
    the clinic stays `onboarding` until the owner completes onboarding AND
    a verified Paddle webhook confirms payment (apps/billing/services/
    activation.py). This never activates the paid subscription itself."""
    auth = _require_platform(request)
    try:
        app = ClinicApplication.objects.get(pk=application_id)
    except ClinicApplication.DoesNotExist:
        raise HttpError(404, "Application not found") from None
    if app.status in {ClinicApplicationStatus.CONVERTED, ClinicApplicationStatus.REJECTED}:
        raise HttpError(400, f"Application is already {app.status}")

    from apps.billing.models import Plan, Subscription

    plan_slug = (payload.plan_slug or "").strip() or app.plan_slug
    if not plan_slug:
        raise HttpError(
            400,
            "This application has no plan yet (a demo request) — provide plan_slug "
            "to approve it.",
        )
    plan = Plan.objects.filter(slug=plan_slug, is_active=True).first()
    if plan is None:
        raise HttpError(400, "The requested plan is no longer available")

    slug = slugify(payload.slug)[:64] if payload.slug else ""
    slug = slug or _unique_slug(app.clinic_name)
    if Clinic.objects.filter(slug=slug).exists():
        raise HttpError(400, "Clinic slug already taken")

    clinic = Clinic.objects.create(
        slug=slug,
        name=app.clinic_name,
        email=app.work_email,
        phone=app.phone,
        status=ClinicStatus.ONBOARDING,
    )
    from apps.widget.models import WidgetSettings

    WidgetSettings.objects.create(clinic=clinic, configuration=default_widget_configuration())

    subscription = Subscription.objects.create(clinic=clinic, plan=plan)
    logger.info(
        "subscription_created clinic=%s subscription=%s plan=%s",
        clinic.id, subscription.id, plan.slug,
    )

    name_parts = app.owner_name.strip().split(maxsplit=1)
    first_name = name_parts[0] if name_parts else ""
    last_name = name_parts[1] if len(name_parts) > 1 else ""
    owner, owner_created = User.objects.get_or_create(
        email=app.work_email,
        defaults={
            "username": app.work_email.split("@")[0][:40],
            "first_name": first_name,
            "last_name": last_name,
            "role": UserRole.CLINIC_ADMIN,
            "is_clinic_owner": True,
            "is_active": False,
        },
    )
    ClinicStaff.objects.get_or_create(user=owner, clinic=clinic, defaults={"is_active": True})

    if owner_created:
        _, raw = StaffAuthToken.issue(
            user=owner, purpose=StaffAuthTokenPurpose.INVITE, ttl_hours=24 * 7
        )
        NotificationService.send_clinic_owner_invite_email(
            to=app.work_email, token=raw, clinic_name=clinic.name, first_name=first_name
        )
        # Never log the raw token — it's the invite link's credential.
        logger.info("invitation_sent clinic=%s user=%s", clinic.id, owner.id)
    # An existing (already-active) user simply gets clinic access added —
    # they can just log in, no separate invite needed.

    app.status = ClinicApplicationStatus.CONVERTED
    app.reviewed_by = auth.user
    app.reviewed_at = timezone.now()
    app.converted_clinic = clinic
    app.save(
        update_fields=["status", "reviewed_by", "reviewed_at", "converted_clinic", "updated_at"]
    )

    write_audit(
        action=AuditAction.APPLICATION_APPROVED,
        actor=auth.user,
        clinic=clinic,
        object_type="clinic_application",
        object_id=str(app.id),
        metadata={"plan_slug": plan.slug},
        ip_address=client_ip(request),
    )

    return ApplicationActionOut(
        application=_application_out(app),
        clinic=ClinicOut(
            id=clinic.id, slug=clinic.slug, name=clinic.name, timezone=clinic.timezone,
            status=clinic.status,
        ),
    )


@router.post(
    "/applications/{application_id}/reject", response=ClinicApplicationOut, auth=staff_jwt_auth
)
def reject_application(request, application_id: UUID, payload: RejectApplicationIn):
    auth = _require_platform(request)
    try:
        app = ClinicApplication.objects.get(pk=application_id)
    except ClinicApplication.DoesNotExist:
        raise HttpError(404, "Application not found") from None
    if app.status in {ClinicApplicationStatus.CONVERTED, ClinicApplicationStatus.REJECTED}:
        raise HttpError(400, f"Application is already {app.status}")

    app.status = ClinicApplicationStatus.REJECTED
    app.rejection_reason = (payload.reason or "").strip()
    app.reviewed_by = auth.user
    app.reviewed_at = timezone.now()
    app.save(update_fields=["status", "rejection_reason", "reviewed_by", "reviewed_at", "updated_at"])

    write_audit(
        action=AuditAction.APPLICATION_REJECTED,
        actor=auth.user,
        object_type="clinic_application",
        object_id=str(app.id),
        metadata={"reason": app.rejection_reason},
        ip_address=client_ip(request),
    )
    return _application_out(app)


@router.post(
    "/applications/{application_id}/review",
    response=ClinicApplicationOut,
    auth=staff_jwt_auth,
)
def mark_application_reviewing(request, application_id: UUID):
    _require_platform(request)
    try:
        app = ClinicApplication.objects.get(pk=application_id)
    except ClinicApplication.DoesNotExist:
        raise HttpError(404, "Application not found") from None
    if app.status in {ClinicApplicationStatus.CONVERTED, ClinicApplicationStatus.REJECTED}:
        raise HttpError(400, f"Application is already {app.status}")
    app.status = ClinicApplicationStatus.REVIEWING
    app.save(update_fields=["status", "updated_at"])
    return _application_out(app)
