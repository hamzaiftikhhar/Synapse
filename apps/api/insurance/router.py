"""Insurance plan CRUD — soft delete, mirrors the Services router."""

from uuid import UUID

from django.db.models import Q
from django.utils import timezone
from ninja import Query, Router
from ninja.errors import HttpError

from apps.api.auth.deps import clinic_from, jwt_auth
from apps.api.common.schemas import MessageOut, PaginatedOut
from apps.api.insurance.schemas import (
    InsurancePlanIn,
    InsurancePlanOut,
    InsurancePlanUpdateIn,
)
from apps.insurance.models import InsurancePlan

router = Router(tags=["Insurance"])


def _serialize(plan: InsurancePlan) -> InsurancePlanOut:
    return InsurancePlanOut(
        id=plan.id,
        provider_name=plan.provider_name,
        plan_name=plan.plan_name,
        plan_type=plan.plan_type,
        is_accepted=plan.is_accepted,
        notes=plan.notes,
        is_deleted=plan.is_deleted,
        created_at=plan.created_at,
        updated_at=plan.updated_at,
    )


def _get_plan(clinic_id: UUID, plan_id: UUID) -> InsurancePlan:
    try:
        return InsurancePlan.objects.get(
            clinic_id=clinic_id, id=plan_id, is_deleted=False
        )
    except InsurancePlan.DoesNotExist:
        raise HttpError(404, "Insurance plan not found") from None


@router.get("", response=PaginatedOut[InsurancePlanOut], auth=jwt_auth)
def list_insurance_plans(
    request,
    search: str | None = Query(None),
    is_accepted: bool | None = Query(None),
    include_deleted: bool = Query(False),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    clinic = clinic_from(request)
    qs = InsurancePlan.objects.filter(clinic=clinic)
    if not include_deleted:
        qs = qs.filter(is_deleted=False)
    if is_accepted is not None:
        qs = qs.filter(is_accepted=is_accepted)
    if search:
        qs = qs.filter(
            Q(provider_name__icontains=search) | Q(plan_name__icontains=search)
        )
    qs = qs.order_by("provider_name")
    count = qs.count()
    results = [_serialize(p) for p in qs[offset : offset + limit]]
    return PaginatedOut(count=count, results=results)


@router.post("", response={201: InsurancePlanOut}, auth=jwt_auth)
def create_insurance_plan(request, payload: InsurancePlanIn):
    if not payload.provider_name.strip():
        raise HttpError(400, "Insurance provider name is required")
    plan = InsurancePlan.objects.create(clinic=clinic_from(request), **payload.dict())
    return 201, _serialize(plan)


@router.get("/{plan_id}", response=InsurancePlanOut, auth=jwt_auth)
def get_insurance_plan(request, plan_id: UUID):
    return _serialize(_get_plan(clinic_from(request).id, plan_id))


@router.patch("/{plan_id}", response=InsurancePlanOut, auth=jwt_auth)
def update_insurance_plan(request, plan_id: UUID, payload: InsurancePlanUpdateIn):
    plan = _get_plan(clinic_from(request).id, plan_id)
    for field, value in payload.dict(exclude_unset=True).items():
        setattr(plan, field, value)
    plan.save()
    return _serialize(plan)


@router.delete("/{plan_id}", response=MessageOut, auth=jwt_auth)
def delete_insurance_plan(request, plan_id: UUID):
    plan = _get_plan(clinic_from(request).id, plan_id)
    plan.is_deleted = True
    plan.deleted_at = timezone.now()
    plan.is_accepted = False
    plan.save(update_fields=["is_deleted", "deleted_at", "is_accepted", "updated_at"])
    return MessageOut(detail="Insurance plan soft-deleted")
