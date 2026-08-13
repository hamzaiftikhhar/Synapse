"""Specialty CRUD — soft delete, unique per-clinic slug."""

from uuid import UUID

from django.db.models import Q
from django.utils import timezone
from ninja import Query, Router
from ninja.errors import HttpError

from apps.api.auth.deps import clinic_from, jwt_auth
from apps.api.common.schemas import MessageOut, PaginatedOut
from apps.api.specialties.schemas import SpecialtyIn, SpecialtyOut, SpecialtyUpdateIn
from apps.specialties.models import Specialty
from apps.specialties.services.specialty_service import (
    create_specialty as create_specialty_row,
)
from apps.specialties.services.specialty_service import unique_slug as _unique_slug

router = Router(tags=["Specialties"])


def _serialize(specialty: Specialty) -> SpecialtyOut:
    return SpecialtyOut(
        id=specialty.id,
        name=specialty.name,
        slug=specialty.slug,
        description=specialty.description,
        is_active=specialty.is_active,
        is_deleted=specialty.is_deleted,
        created_at=specialty.created_at,
        updated_at=specialty.updated_at,
    )


def _get_specialty(clinic_id: UUID, specialty_id: UUID) -> Specialty:
    try:
        return Specialty.objects.get(
            clinic_id=clinic_id, id=specialty_id, is_deleted=False
        )
    except Specialty.DoesNotExist:
        raise HttpError(404, "Specialty not found") from None


@router.get("", response=PaginatedOut[SpecialtyOut], auth=jwt_auth)
def list_specialties(
    request,
    search: str | None = Query(None),
    is_active: bool | None = Query(None),
    include_deleted: bool = Query(False),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    clinic = clinic_from(request)
    qs = Specialty.objects.filter(clinic=clinic)
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


@router.post("", response={201: SpecialtyOut}, auth=jwt_auth)
def create_specialty(request, payload: SpecialtyIn):
    clinic = clinic_from(request)
    if not payload.name.strip():
        raise HttpError(400, "Specialty name is required")
    specialty = create_specialty_row(
        clinic=clinic,
        name=payload.name,
        slug=payload.slug,
        description=payload.description,
        is_active=payload.is_active,
    )
    return 201, _serialize(specialty)


@router.get("/{specialty_id}", response=SpecialtyOut, auth=jwt_auth)
def get_specialty(request, specialty_id: UUID):
    return _serialize(_get_specialty(clinic_from(request).id, specialty_id))


@router.patch("/{specialty_id}", response=SpecialtyOut, auth=jwt_auth)
def update_specialty(request, specialty_id: UUID, payload: SpecialtyUpdateIn):
    clinic = clinic_from(request)
    specialty = _get_specialty(clinic.id, specialty_id)
    data = payload.dict(exclude_unset=True)
    if "slug" in data and data["slug"]:
        data["slug"] = _unique_slug(clinic.id, data["slug"], exclude_id=specialty.id)
    elif "name" in data and not specialty.slug:
        data["slug"] = _unique_slug(clinic.id, data["name"], exclude_id=specialty.id)
    for field, value in data.items():
        setattr(specialty, field, value)
    specialty.save()
    return _serialize(specialty)


@router.delete("/{specialty_id}", response=MessageOut, auth=jwt_auth)
def delete_specialty(request, specialty_id: UUID):
    specialty = _get_specialty(clinic_from(request).id, specialty_id)
    specialty.is_deleted = True
    specialty.deleted_at = timezone.now()
    specialty.is_active = False
    specialty.save(update_fields=["is_deleted", "deleted_at", "is_active", "updated_at"])
    return MessageOut(detail="Specialty soft-deleted")
