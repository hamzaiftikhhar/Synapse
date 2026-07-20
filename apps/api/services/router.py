"""Service CRUD — soft delete."""

from uuid import UUID

from django.db.models import Q
from django.utils import timezone
from ninja import Query, Router
from ninja.errors import HttpError

from apps.api.auth.deps import clinic_from, jwt_auth
from apps.api.common.schemas import MessageOut, PaginatedOut
from apps.api.services.schemas import ServiceIn, ServiceOut, ServiceUpdateIn
from apps.services.models import Service

router = Router(tags=["Services"])


def _serialize(service: Service) -> ServiceOut:
    return ServiceOut(
        id=service.id,
        name=service.name,
        description=service.description,
        duration_min=service.duration_min,
        price_cents=service.price_cents,
        is_active=service.is_active,
        is_deleted=service.is_deleted,
        created_at=service.created_at,
        updated_at=service.updated_at,
    )


def _get_service(clinic_id: UUID, service_id: UUID) -> Service:
    try:
        return Service.objects.get(
            clinic_id=clinic_id, id=service_id, is_deleted=False
        )
    except Service.DoesNotExist:
        raise HttpError(404, "Service not found") from None


@router.get("", response=PaginatedOut[ServiceOut], auth=jwt_auth)
def list_services(
    request,
    search: str | None = Query(None),
    is_active: bool | None = Query(None),
    include_deleted: bool = Query(False),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    clinic = clinic_from(request)
    qs = Service.objects.filter(clinic=clinic)
    if not include_deleted:
        qs = qs.filter(is_deleted=False)
    if is_active is not None:
        qs = qs.filter(is_active=is_active)
    if search:
        qs = qs.filter(Q(name__icontains=search) | Q(description__icontains=search))
    qs = qs.order_by("name")
    count = qs.count()
    results = [_serialize(s) for s in qs[offset : offset + limit]]
    return PaginatedOut(count=count, results=results)


@router.post("", response={201: ServiceOut}, auth=jwt_auth)
def create_service(request, payload: ServiceIn):
    service = Service.objects.create(clinic=clinic_from(request), **payload.dict())
    return 201, _serialize(service)


@router.get("/{service_id}", response=ServiceOut, auth=jwt_auth)
def get_service(request, service_id: UUID):
    return _serialize(_get_service(clinic_from(request).id, service_id))


@router.patch("/{service_id}", response=ServiceOut, auth=jwt_auth)
def update_service(request, service_id: UUID, payload: ServiceUpdateIn):
    service = _get_service(clinic_from(request).id, service_id)
    for field, value in payload.dict(exclude_unset=True).items():
        setattr(service, field, value)
    service.save()
    return _serialize(service)


@router.delete("/{service_id}", response=MessageOut, auth=jwt_auth)
def delete_service(request, service_id: UUID):
    service = _get_service(clinic_from(request).id, service_id)
    service.is_deleted = True
    service.deleted_at = timezone.now()
    service.is_active = False
    service.save(update_fields=["is_deleted", "deleted_at", "is_active", "updated_at"])
    return MessageOut(detail="Service soft-deleted")
