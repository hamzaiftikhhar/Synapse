"""Patient CRUD — tenant-scoped via JWT clinic_id."""

from uuid import UUID

from django.db import IntegrityError
from django.db.models import Q
from ninja import Query, Router
from ninja.errors import HttpError

from apps.api.auth.deps import clinic_from, jwt_auth
from apps.api.common.schemas import MessageOut, PaginatedOut
from apps.api.patients.schemas import PatientIn, PatientOut, PatientUpdateIn
from apps.patients.models import Patient

router = Router(tags=["Patients"])


def _serialize(patient: Patient) -> PatientOut:
    return PatientOut(
        id=patient.id,
        phone=patient.phone,
        email=patient.email,
        first_name=patient.first_name,
        last_name=patient.last_name,
        full_name=patient.full_name,
        date_of_birth=patient.date_of_birth,
        preferred_language=patient.preferred_language,
        is_verified=patient.is_verified,
        created_at=patient.created_at,
        updated_at=patient.updated_at,
    )


def _get_patient(clinic_id: UUID, patient_id: UUID) -> Patient:
    try:
        return Patient.objects.get(clinic_id=clinic_id, id=patient_id)
    except Patient.DoesNotExist:
        raise HttpError(404, "Patient not found") from None


@router.get("", response=PaginatedOut[PatientOut], auth=jwt_auth)
def list_patients(
    request,
    search: str | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    clinic = clinic_from(request)
    qs = Patient.objects.filter(clinic=clinic).order_by("last_name", "first_name")
    if search:
        qs = qs.filter(
            Q(first_name__icontains=search)
            | Q(last_name__icontains=search)
            | Q(phone__icontains=search)
            | Q(email__icontains=search)
        )
    count = qs.count()
    results = [_serialize(p) for p in qs[offset : offset + limit]]
    return PaginatedOut(count=count, results=results)


@router.post("", response={201: PatientOut}, auth=jwt_auth)
def create_patient(request, payload: PatientIn):
    clinic = clinic_from(request)
    try:
        patient = Patient.objects.create(clinic=clinic, **payload.dict())
    except IntegrityError as exc:
        raise HttpError(400, "Phone or email already exists for this clinic") from exc
    return 201, _serialize(patient)


@router.get("/{patient_id}", response=PatientOut, auth=jwt_auth)
def get_patient(request, patient_id: UUID):
    return _serialize(_get_patient(clinic_from(request).id, patient_id))


@router.patch("/{patient_id}", response=PatientOut, auth=jwt_auth)
def update_patient(request, patient_id: UUID, payload: PatientUpdateIn):
    clinic_id = clinic_from(request).id
    patient = _get_patient(clinic_id, patient_id)
    for field, value in payload.dict(exclude_unset=True).items():
        setattr(patient, field, value)
    try:
        patient.save()
    except IntegrityError as exc:
        raise HttpError(400, "Phone or email already exists for this clinic") from exc
    return _serialize(patient)


@router.delete("/{patient_id}", response=MessageOut, auth=jwt_auth)
def delete_patient(request, patient_id: UUID):
    patient = _get_patient(clinic_from(request).id, patient_id)
    patient.delete()
    return MessageOut(detail="Patient deleted")
