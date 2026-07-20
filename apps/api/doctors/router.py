"""Doctor CRUD — soft delete, M2M specialties/services."""

from typing import Any


from uuid import UUID

from django.db.models import Q
from django.utils import timezone
from ninja import Query, Router
from ninja.errors import HttpError

from apps.api.auth.deps import clinic_from, jwt_auth
from apps.api.common.schemas import MessageOut, PaginatedOut
from apps.api.doctors.schemas import DoctorIn, DoctorOut, DoctorUpdateIn
from apps.doctors.models import Doctor, DoctorService, DoctorSpecialty
from apps.services.models import Service
from apps.specialties.models import Specialty

router = Router(tags=["Doctors"])


def _serialize(doctor: Doctor) -> DoctorOut:
    return DoctorOut(
        id=doctor.id,
        full_name=doctor.full_name,
        title=doctor.title,
        bio=doctor.bio,
        photo_url=doctor.photo_url,
        languages=list(doctor.languages),
        is_active=doctor.is_active,
        is_accepting_patients=doctor.is_accepting_patients,
        is_deleted=doctor.is_deleted,
        specialty_ids=list(doctor.specialties.values_list("id", flat=True)),
        service_ids=list(doctor.services.values_list("id", flat=True)),
        created_at=doctor.created_at,
        updated_at=doctor.updated_at,
    )


def _get_doctor(clinic_id: UUID, doctor_id: UUID, *, include_deleted: bool = False) -> Doctor:
    qs = Doctor.objects.filter(clinic_id=clinic_id)
    if not include_deleted:
        qs = qs.filter(is_deleted=False)
    try:
        return qs.get(id=doctor_id)
    except Doctor.DoesNotExist:
        raise HttpError(404, "Doctor not found") from None


def _sync_specialties(clinic_id: UUID, doctor: Doctor, specialty_ids: list[UUID]) -> None:
    valid = set[Any](
        Specialty.objects.filter(
            clinic_id=clinic_id, id__in=specialty_ids, is_deleted=False
        ).values_list("id", flat=True)
    )
    if len(valid) != len(set(specialty_ids)):
        raise HttpError(400, "One or more specialty IDs are invalid")

    DoctorSpecialty.objects.filter(doctor=doctor).delete()
    DoctorSpecialty.objects.bulk_create(
        [
            DoctorSpecialty(doctor=doctor, specialty_id=sid, clinic_id=clinic_id)
            for sid in specialty_ids
        ]
    )


def _sync_services(clinic_id: UUID, doctor: Doctor, service_ids: list[UUID]) -> None:
    valid = set(
        Service.objects.filter(
            clinic_id=clinic_id, id__in=service_ids, is_deleted=False
        ).values_list("id", flat=True)
    )
    if len(valid) != len(set(service_ids)):
        raise HttpError(400, "One or more service IDs are invalid")

    DoctorService.objects.filter(doctor=doctor).delete()
    DoctorService.objects.bulk_create(
        [
            DoctorService(doctor=doctor, service_id=sid, clinic_id=clinic_id)
            for sid in service_ids
        ]
    )


@router.get("", response=PaginatedOut[DoctorOut], auth=jwt_auth)
def list_doctors(
    request,
    search: str | None = Query(None),
    is_active: bool | None = Query(None),
    include_deleted: bool = Query(False),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    clinic = clinic_from(request)
    qs = Doctor.objects.filter(clinic=clinic)
    if not include_deleted:
        qs = qs.filter(is_deleted=False)
    if is_active is not None:
        qs = qs.filter(is_active=is_active)
    if search:
        qs = qs.filter(Q(full_name__icontains=search) | Q(title__icontains=search))
    qs = qs.order_by("full_name")
    count = qs.count()
    results = [_serialize(d) for d in qs[offset : offset + limit]]
    return PaginatedOut(count=count, results=results)


@router.post("", response={201: DoctorOut}, auth=jwt_auth)
def create_doctor(request, payload: DoctorIn):
    clinic = clinic_from(request)
    data = payload.dict(exclude={"specialty_ids", "service_ids"})
    if data.get("languages") is None:
        data["languages"] = ["en"]
    doctor = Doctor.objects.create(clinic=clinic, **data)
    if payload.specialty_ids:
        _sync_specialties(clinic.id, doctor, payload.specialty_ids)
    if payload.service_ids:
        _sync_services(clinic.id, doctor, payload.service_ids)
    doctor.refresh_from_db()
    return 201, _serialize(doctor)


@router.get("/{doctor_id}", response=DoctorOut, auth=jwt_auth)
def get_doctor(request, doctor_id: UUID):
    return _serialize(_get_doctor(clinic_from(request).id, doctor_id))


@router.patch("/{doctor_id}", response=DoctorOut, auth=jwt_auth)
def update_doctor(request, doctor_id: UUID, payload: DoctorUpdateIn):
    clinic_id = clinic_from(request).id
    doctor = _get_doctor(clinic_id, doctor_id)
    data = payload.dict(exclude_unset=True, exclude={"specialty_ids", "service_ids"})
    for field, value in data.items():
        setattr(doctor, field, value)
    doctor.save()
    if payload.specialty_ids is not None:
        _sync_specialties(clinic_id, doctor, payload.specialty_ids)
    if payload.service_ids is not None:
        _sync_services(clinic_id, doctor, payload.service_ids)
    doctor.refresh_from_db()
    return _serialize(doctor)


@router.delete("/{doctor_id}", response=MessageOut, auth=jwt_auth)
def delete_doctor(request, doctor_id: UUID):
    """Soft delete — preserves appointment history."""
    doctor = _get_doctor(clinic_from(request).id, doctor_id)
    doctor.is_deleted = True
    doctor.deleted_at = timezone.now()
    doctor.is_active = False
    doctor.save(update_fields=["is_deleted", "deleted_at", "is_active", "updated_at"])
    return MessageOut(detail="Doctor soft-deleted")
