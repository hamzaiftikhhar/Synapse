"""Super Admin ops — users, subscriptions, documents, monitoring, audit, settings."""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from django.conf import settings
from django.db.models import Avg, Count, Max, Q, Sum
from django.utils import timezone
from ninja import Query, Router, Schema
from ninja.errors import HttpError

from apps.accounts.models import (
    AuditAction,
    AuditLog,
    ClinicStaff,
    StaffAuthToken,
    StaffAuthTokenPurpose,
    User,
    UserRole,
)
from apps.accounts.services.audit import write_audit
from apps.api.auth.deps import client_ip, require_super_admin, staff_jwt_auth
from apps.billing.models import Plan, Subscription
from apps.clinics.models import Clinic
from apps.knowledge.models import Document
from apps.knowledge.services import document_service as docs
from apps.notifications.service import NotificationService

router = Router(tags=["Platform — Super Admin"])


def _require_platform(request):
    return require_super_admin(request)


def _iso(value) -> str | None:
    return value.isoformat() if value else None


# ── Users ────────────────────────────────────────────────────────────────────


class PlatformClinicMembershipOut(Schema):
    id: str
    slug: str
    name: str
    is_active: bool


class PlatformUserOut(Schema):
    id: int
    email: str
    first_name: str
    last_name: str
    role: str
    is_active: bool
    is_clinic_owner: bool
    email_verified: bool
    last_login: str | None = None
    date_joined: str
    clinics: list[PlatformClinicMembershipOut]


class InviteUserIn(Schema):
    email: str
    first_name: str = ""
    last_name: str = ""
    clinic_id: UUID
    role: str = "STAFF"


class PatchUserIn(Schema):
    is_active: bool | None = None
    role: str | None = None
    first_name: str | None = None
    last_name: str | None = None


def _user_out(user: User) -> PlatformUserOut:
    memberships = list(user.clinic_memberships.select_related("clinic").all())
    return PlatformUserOut(
        id=user.id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        role=user.role,
        is_active=user.is_active,
        is_clinic_owner=user.is_clinic_owner,
        email_verified=bool(user.email_verified_at),
        last_login=_iso(user.last_login),
        date_joined=user.date_joined.isoformat(),
        clinics=[
            PlatformClinicMembershipOut(
                id=str(m.clinic_id),
                slug=m.clinic.slug,
                name=m.clinic.name,
                is_active=m.is_active,
            )
            for m in memberships
        ],
    )


@router.get("/users", response=list[PlatformUserOut], auth=staff_jwt_auth)
def list_users(request, search: str = "", role: str = ""):
    _require_platform(request)
    qs = User.objects.all().prefetch_related("clinic_memberships__clinic").order_by("-date_joined")
    if search.strip():
        term = search.strip()
        qs = qs.filter(
            Q(email__icontains=term)
            | Q(first_name__icontains=term)
            | Q(last_name__icontains=term)
        )
    if role.strip():
        qs = qs.filter(role=role.strip())
    return [_user_out(u) for u in qs[:200]]


@router.post("/users/invite", response=PlatformUserOut, auth=staff_jwt_auth)
def invite_user(request, payload: InviteUserIn):
    auth = _require_platform(request)
    role = (payload.role or UserRole.STAFF).upper()
    if role not in {UserRole.STAFF, UserRole.CLINIC_ADMIN}:
        raise HttpError(400, "Invite role must be STAFF or CLINIC_ADMIN")
    try:
        clinic = Clinic.objects.get(pk=payload.clinic_id)
    except Clinic.DoesNotExist:
        raise HttpError(404, "Clinic not found") from None

    email = payload.email.strip().lower()
    if not email:
        raise HttpError(400, "Email is required")
    user, created = User.objects.get_or_create(
        email=email,
        defaults={
            "username": email.split("@")[0][:40],
            "first_name": payload.first_name.strip(),
            "last_name": payload.last_name.strip(),
            "role": role,
            "is_clinic_owner": role == UserRole.CLINIC_ADMIN,
            "is_active": False,
        },
    )
    ClinicStaff.objects.get_or_create(
        user=user, clinic=clinic, defaults={"is_active": True}
    )
    if created:
        _, raw = StaffAuthToken.issue(
            user=user, purpose=StaffAuthTokenPurpose.INVITE, ttl_hours=24 * 7
        )
        NotificationService.send_clinic_owner_invite_email(
            to=email,
            token=raw,
            clinic_name=clinic.name,
            first_name=payload.first_name.strip(),
        )
    write_audit(
        action=AuditAction.USER_INVITE,
        actor=auth.user,
        clinic=clinic,
        object_type="user",
        object_id=str(user.id),
        metadata={"email": email, "created": created, "role": role},
        ip_address=client_ip(request),
    )
    user = User.objects.prefetch_related("clinic_memberships__clinic").get(pk=user.pk)
    return _user_out(user)


@router.patch("/users/{user_id}", response=PlatformUserOut, auth=staff_jwt_auth)
def patch_user(request, user_id: int, payload: PatchUserIn):
    auth = _require_platform(request)
    try:
        user = User.objects.prefetch_related("clinic_memberships__clinic").get(pk=user_id)
    except User.DoesNotExist:
        raise HttpError(404, "User not found") from None
    if user.id == auth.user.id and payload.is_active is False:
        raise HttpError(400, "You cannot deactivate your own account")
    if payload.role:
        role = payload.role.upper()
        if role not in {c.value for c in UserRole}:
            raise HttpError(400, "Invalid role")
        if role == UserRole.SUPER_ADMIN and user.role != UserRole.SUPER_ADMIN:
            raise HttpError(400, "Cannot promote to Super Admin here")
        if user.role == UserRole.SUPER_ADMIN and role != UserRole.SUPER_ADMIN:
            remaining = User.objects.filter(role=UserRole.SUPER_ADMIN, is_active=True).exclude(
                pk=user.pk
            ).count()
            if remaining < 1:
                raise HttpError(400, "Keep at least one Super Admin")
        user.role = role
    if payload.is_active is not None:
        user.is_active = payload.is_active
    if payload.first_name is not None:
        user.first_name = payload.first_name.strip()[:150]
    if payload.last_name is not None:
        user.last_name = payload.last_name.strip()[:150]
    user.save()
    write_audit(
        action=AuditAction.USER_UPDATE,
        actor=auth.user,
        object_type="user",
        object_id=str(user.id),
        metadata=payload.dict(exclude_none=True),
        ip_address=client_ip(request),
    )
    return _user_out(user)


# ── Subscriptions & plans ─────────────────────────────────────────────────────


class PlatformPlanOut(Schema):
    id: str
    slug: str
    name: str
    billing_interval: str
    display_price_cents: int | None = None
    display_currency: str
    is_active: bool
    display_order: int
    paddle_price_id_sandbox: str = ""
    paddle_price_id_live: str = ""
    subscriber_count: int = 0


class PlatformSubscriptionOut(Schema):
    id: str
    clinic_id: str
    clinic_name: str
    clinic_slug: str
    plan_slug: str
    plan_name: str
    status: str
    display_price_cents: int | None = None
    display_currency: str
    current_period_end: str | None = None
    cancel_at_period_end: bool
    paddle_subscription_id: str | None = None
    updated_at: str


class PatchPlanIn(Schema):
    name: str | None = None
    display_price_cents: int | None = None
    is_active: bool | None = None
    display_order: int | None = None
    paddle_price_id_sandbox: str | None = None
    paddle_price_id_live: str | None = None


def _plan_out(plan: Plan, subscriber_count: int | None = None) -> PlatformPlanOut:
    count = subscriber_count
    if count is None:
        count = plan.subscriptions.count()
    return PlatformPlanOut(
        id=str(plan.id),
        slug=plan.slug,
        name=plan.name,
        billing_interval=plan.billing_interval,
        display_price_cents=plan.display_price_cents,
        display_currency=plan.display_currency,
        is_active=plan.is_active,
        display_order=plan.display_order,
        paddle_price_id_sandbox=plan.paddle_price_id_sandbox,
        paddle_price_id_live=plan.paddle_price_id_live,
        subscriber_count=count,
    )


@router.get("/subscriptions", response=list[PlatformSubscriptionOut], auth=staff_jwt_auth)
def list_subscriptions(request, status: str = "", search: str = ""):
    _require_platform(request)
    qs = Subscription.objects.select_related("clinic", "plan").order_by("-updated_at")
    if status.strip():
        qs = qs.filter(status=status.strip())
    if search.strip():
        term = search.strip()
        qs = qs.filter(Q(clinic__name__icontains=term) | Q(clinic__slug__icontains=term))
    return [
        PlatformSubscriptionOut(
            id=str(s.id),
            clinic_id=str(s.clinic_id),
            clinic_name=s.clinic.name,
            clinic_slug=s.clinic.slug,
            plan_slug=s.plan.slug,
            plan_name=s.plan.name,
            status=s.status,
            display_price_cents=s.plan.display_price_cents,
            display_currency=s.plan.display_currency,
            current_period_end=_iso(s.current_period_end),
            cancel_at_period_end=s.cancel_at_period_end,
            paddle_subscription_id=s.paddle_subscription_id,
            updated_at=s.updated_at.isoformat(),
        )
        for s in qs[:200]
    ]


@router.get("/plans", response=list[PlatformPlanOut], auth=staff_jwt_auth)
def list_plans(request):
    _require_platform(request)
    plans = list(Plan.objects.annotate(n=Count("subscriptions")).order_by("display_order", "name"))
    return [_plan_out(p, subscriber_count=p.n) for p in plans]


@router.patch("/plans/{plan_id}", response=PlatformPlanOut, auth=staff_jwt_auth)
def patch_plan(request, plan_id: UUID, payload: PatchPlanIn):
    auth = _require_platform(request)
    try:
        plan = Plan.objects.get(pk=plan_id)
    except Plan.DoesNotExist:
        raise HttpError(404, "Plan not found") from None
    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise HttpError(400, "Name cannot be empty")
        plan.name = name[:100]
    if payload.display_price_cents is not None:
        plan.display_price_cents = max(0, payload.display_price_cents)
    if payload.is_active is not None:
        plan.is_active = payload.is_active
    if payload.display_order is not None:
        plan.display_order = payload.display_order
    if payload.paddle_price_id_sandbox is not None:
        plan.paddle_price_id_sandbox = payload.paddle_price_id_sandbox.strip()[:64]
    if payload.paddle_price_id_live is not None:
        plan.paddle_price_id_live = payload.paddle_price_id_live.strip()[:64]
    plan.save()
    write_audit(
        action=AuditAction.PLAN_UPDATE,
        actor=auth.user,
        object_type="plan",
        object_id=str(plan.id),
        metadata=payload.dict(exclude_none=True),
        ip_address=client_ip(request),
    )
    return _plan_out(plan)


# ── Documents ────────────────────────────────────────────────────────────────


class PlatformDocumentOut(Schema):
    id: str
    title: str
    file_name: str
    status: str
    processing_stage: str
    chunk_count: int
    clinic_id: str
    clinic_name: str
    clinic_slug: str
    error_message: str = ""
    created_at: str
    updated_at: str


def _doc_out(doc: Document) -> PlatformDocumentOut:
    return PlatformDocumentOut(
        id=str(doc.id),
        title=doc.title,
        file_name=doc.file_name,
        status=doc.status,
        processing_stage=doc.processing_stage,
        chunk_count=doc.chunk_count,
        clinic_id=str(doc.clinic_id),
        clinic_name=doc.clinic.name,
        clinic_slug=doc.clinic.slug,
        error_message=doc.error_message or "",
        created_at=doc.created_at.isoformat(),
        updated_at=doc.updated_at.isoformat(),
    )


@router.get("/documents", response=list[PlatformDocumentOut], auth=staff_jwt_auth)
def list_documents(request, status: str = "", search: str = ""):
    _require_platform(request)
    qs = Document.objects.filter(is_deleted=False).select_related("clinic").order_by("-created_at")
    if status.strip():
        qs = qs.filter(status=status.strip())
    if search.strip():
        term = search.strip()
        qs = qs.filter(
            Q(title__icontains=term)
            | Q(file_name__icontains=term)
            | Q(clinic__name__icontains=term)
        )
    return [_doc_out(d) for d in qs[:200]]


@router.post("/documents/{document_id}/reindex", response=PlatformDocumentOut, auth=staff_jwt_auth)
def reindex_platform_document(request, document_id: UUID):
    auth = _require_platform(request)
    try:
        document = Document.objects.select_related("clinic").get(pk=document_id, is_deleted=False)
    except Document.DoesNotExist:
        raise HttpError(404, "Document not found") from None
    try:
        document = docs.reindex_document(document, async_ingest=True)
    except docs.DocumentServiceError as exc:
        raise HttpError(400, str(exc)) from exc
    write_audit(
        action=AuditAction.DOCUMENT_UPLOAD,
        actor=auth.user,
        clinic=document.clinic,
        object_type="document",
        object_id=str(document.id),
        metadata={"reindex": True},
        ip_address=client_ip(request),
    )
    document.refresh_from_db()
    return _doc_out(document)


@router.delete("/documents/{document_id}", response=PlatformDocumentOut, auth=staff_jwt_auth)
def delete_platform_document(request, document_id: UUID):
    auth = _require_platform(request)
    try:
        document = Document.objects.select_related("clinic").get(pk=document_id, is_deleted=False)
    except Document.DoesNotExist:
        raise HttpError(404, "Document not found") from None
    document = docs.soft_delete_document(document)
    write_audit(
        action=AuditAction.DOCUMENT_DELETE,
        actor=auth.user,
        clinic=document.clinic,
        object_type="document",
        object_id=str(document.id),
        ip_address=client_ip(request),
    )
    return _doc_out(document)


# ── AI monitoring ─────────────────────────────────────────────────────────────


class MonitoringBucketOut(Schema):
    key: str
    calls: int
    avg_latency_ms: int
    max_latency_ms: int
    tokens: int


class SlowCallOut(Schema):
    id: str
    clinic_name: str
    clinic_slug: str
    model: str
    operation: str
    latency_ms: int
    total_tokens: int
    created_at: str


class PlatformMonitoringOut(Schema):
    days: int
    calls: int
    cached_calls: int
    avg_latency_ms: int
    max_latency_ms: int
    p95_latency_ms: int
    slow_calls: int
    failed_documents: int
    by_operation: list[MonitoringBucketOut]
    by_model: list[MonitoringBucketOut]
    slowest: list[SlowCallOut]


@router.get("/ai-monitoring", response=PlatformMonitoringOut, auth=staff_jwt_auth)
def ai_monitoring(request, days: int = Query(7, ge=1, le=90)):
    _require_platform(request)
    from apps.ai.models import AIUsageLog
    from apps.knowledge.models import DocumentStatus

    since = timezone.now() - timedelta(days=days)
    qs = AIUsageLog.objects.filter(created_at__gte=since)
    totals = qs.aggregate(
        calls=Count("id"),
        cached=Count("id", filter=Q(cached_response=True)),
        avg=Avg("latency_ms"),
        mx=Max("latency_ms"),
        slow=Count("id", filter=Q(latency_ms__gte=2000)),
    )
    sample = list(
        qs.order_by("-created_at").values_list("latency_ms", flat=True)[:5000]
    )
    p95 = 0
    if sample:
        ordered = sorted(sample)
        p95 = int(ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))])

    def buckets(field: str) -> list[MonitoringBucketOut]:
        rows = []
        for row in qs.values(field).annotate(
            calls=Count("id"),
            avg=Avg("latency_ms"),
            mx=Max("latency_ms"),
            tokens=Sum("total_tokens"),
        ):
            rows.append(
                MonitoringBucketOut(
                    key=row[field] or "unknown",
                    calls=int(row["calls"] or 0),
                    avg_latency_ms=int(row["avg"] or 0),
                    max_latency_ms=int(row["mx"] or 0),
                    tokens=int(row["tokens"] or 0),
                )
            )
        rows.sort(key=lambda r: r.calls, reverse=True)
        return rows

    slowest = []
    for row in (
        qs.select_related("clinic").order_by("-latency_ms", "-created_at")[:12]
    ):
        slowest.append(
            SlowCallOut(
                id=str(row.id),
                clinic_name=row.clinic.name if row.clinic_id else "—",
                clinic_slug=row.clinic.slug if row.clinic_id else "",
                model=row.model,
                operation=row.operation,
                latency_ms=row.latency_ms,
                total_tokens=row.total_tokens,
                created_at=row.created_at.isoformat(),
            )
        )

    return PlatformMonitoringOut(
        days=days,
        calls=int(totals["calls"] or 0),
        cached_calls=int(totals["cached"] or 0),
        avg_latency_ms=int(totals["avg"] or 0),
        max_latency_ms=int(totals["mx"] or 0),
        p95_latency_ms=p95,
        slow_calls=int(totals["slow"] or 0),
        failed_documents=Document.objects.filter(
            is_deleted=False, status=DocumentStatus.FAILED
        ).count(),
        by_operation=buckets("operation"),
        by_model=buckets("model"),
        slowest=slowest,
    )


# ── Audit ────────────────────────────────────────────────────────────────────


class PlatformAuditOut(Schema):
    id: int
    action: str
    actor_email: str
    clinic_name: str
    clinic_slug: str
    object_type: str
    object_id: str
    metadata: dict
    ip_address: str | None = None
    created_at: str


@router.get("/audit", response=list[PlatformAuditOut], auth=staff_jwt_auth)
def list_audit(request, action: str = "", search: str = ""):
    _require_platform(request)
    qs = AuditLog.objects.select_related("actor", "clinic").order_by("-created_at")
    if action.strip():
        qs = qs.filter(action=action.strip())
    if search.strip():
        term = search.strip()
        qs = qs.filter(
            Q(actor__email__icontains=term)
            | Q(clinic__name__icontains=term)
            | Q(clinic__slug__icontains=term)
            | Q(object_type__icontains=term)
            | Q(action__icontains=term)
        )
    return [
        PlatformAuditOut(
            id=row.id,
            action=row.action,
            actor_email=row.actor.email if row.actor_id else "system",
            clinic_name=row.clinic.name if row.clinic_id else "",
            clinic_slug=row.clinic.slug if row.clinic_id else "",
            object_type=row.object_type,
            object_id=row.object_id,
            metadata=row.metadata or {},
            ip_address=str(row.ip_address) if row.ip_address else None,
            created_at=row.created_at.isoformat(),
        )
        for row in qs[:200]
    ]


# ── Settings ─────────────────────────────────────────────────────────────────


class IntegrationStatusOut(Schema):
    key: str
    label: str
    configured: bool
    detail: str


class PlatformSettingsOut(Schema):
    frontend_url: str
    paddle_environment: str
    nlu_provider: str
    nlu_model: str
    embedding_provider: str
    embedding_model: str
    integrations: list[IntegrationStatusOut]
    plans: list[PlatformPlanOut]


@router.get("/settings", response=PlatformSettingsOut, auth=staff_jwt_auth)
def platform_settings(request):
    _require_platform(request)
    integrations = [
        IntegrationStatusOut(
            key="paddle",
            label="Paddle billing",
            configured=bool(getattr(settings, "PADDLE_API_KEY", "")),
            detail=getattr(settings, "PADDLE_ENVIRONMENT", "sandbox"),
        ),
        IntegrationStatusOut(
            key="paddle_webhooks",
            label="Paddle webhooks",
            configured=bool(getattr(settings, "PADDLE_WEBHOOK_SECRET", "")),
            detail="Verified event signature",
        ),
        IntegrationStatusOut(
            key="openai",
            label="OpenAI",
            configured=bool(getattr(settings, "OPENAI_API_KEY", "")),
            detail=getattr(settings, "NLU_MODEL", ""),
        ),
        IntegrationStatusOut(
            key="gemini",
            label="Gemini (NLU fallback)",
            configured=bool(getattr(settings, "GOOGLE_API_KEY", "")),
            detail=getattr(settings, "NLU_SECONDARY_PROVIDER", "gemini"),
        ),
        IntegrationStatusOut(
            key="email",
            label="Transactional email",
            configured=bool(getattr(settings, "EMAIL_HOST", "")),
            detail=getattr(settings, "DEFAULT_FROM_EMAIL", ""),
        ),
        IntegrationStatusOut(
            key="twilio",
            label="Twilio SMS",
            configured=bool(
                getattr(settings, "TWILIO_ACCOUNT_SID", "")
                and getattr(settings, "TWILIO_FROM_NUMBER", "")
            ),
            detail=getattr(settings, "TWILIO_FROM_NUMBER", "") or "Not set",
        ),
    ]
    plans = list(Plan.objects.annotate(n=Count("subscriptions")).order_by("display_order", "name"))
    return PlatformSettingsOut(
        frontend_url=getattr(settings, "FRONTEND_URL", ""),
        paddle_environment=getattr(settings, "PADDLE_ENVIRONMENT", "sandbox"),
        nlu_provider=getattr(settings, "NLU_PROVIDER", ""),
        nlu_model=getattr(settings, "NLU_MODEL", ""),
        embedding_provider=getattr(settings, "EMBEDDING_PROVIDER", ""),
        embedding_model=getattr(settings, "EMBEDDING_MODEL", ""),
        integrations=integrations,
        plans=[_plan_out(p, subscriber_count=p.n) for p in plans],
    )
