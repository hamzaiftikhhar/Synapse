"""Appointment CRUD — exercises doctor, patient, service, insurance relationships."""

import secrets
import string
from datetime import datetime
from uuid import UUID

from django.db import IntegrityError
from ninja import Query, Router
from ninja.errors import HttpError

from apps.api.auth.deps import clinic_from, jwt_auth
from apps.api.appointments.schemas import (
    AppointmentIn,
    AppointmentOut,
    AppointmentUpdateIn,
)
from apps.api.common.schemas import MessageOut, PaginatedOut
from apps.appointments.models import Appointment, AppointmentSource, AppointmentStatus
from apps.doctors.models import Doctor
from apps.insurance.models import InsurancePlan
from apps.patients.models import Patient
from apps.services.models import Service

router = Router(tags=["Appointments"])

VALID_STATUSES = {c.value for c in AppointmentStatus}
VALID_SOURCES = {c.value for c in AppointmentSource}


def _confirmation_code() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(6))


def _serialize(appt: Appointment) -> AppointmentOut:
    return AppointmentOut(
        id=appt.id,
        doctor_id=appt.doctor_id,
        doctor_name=appt.doctor.full_name,
        patient_id=appt.patient_id,
        patient_name=appt.patient.full_name,
        service_id=appt.service_id,
        service_name=appt.service.name if appt.service else None,
        insurance_plan_id=appt.insurance_plan_id,
        insurance_name=(
            str(appt.insurance_plan) if appt.insurance_plan else None
        ),
        start_time=appt.start_time,
        end_time=appt.end_time,
        status=appt.status,
        confirmation_code=appt.confirmation_code,
        notes=appt.notes,
        source=appt.source,
        created_at=appt.created_at,
        updated_at=appt.updated_at,
    )


def _get_appointment(clinic_id: UUID, appointment_id: UUID) -> Appointment:
    try:
        return (
            Appointment.objects.select_related(
                "doctor", "patient", "service", "insurance_plan"
            )
            .get(clinic_id=clinic_id, id=appointment_id)
        )
    except Appointment.DoesNotExist:
        raise HttpError(404, "Appointment not found") from None


def _resolve_fk(clinic_id: UUID, payload: dict) -> dict:
    """Validate FKs belong to the same clinic."""
    if "doctor_id" in payload:
        if not Doctor.objects.filter(
            clinic_id=clinic_id, id=payload["doctor_id"], is_deleted=False
        ).exists():
            raise HttpError(400, "Invalid doctor_id")

    if "patient_id" in payload:
        if not Patient.objects.filter(
            clinic_id=clinic_id, id=payload["patient_id"]
        ).exists():
            raise HttpError(400, "Invalid patient_id")

    if payload.get("service_id"):
        if not Service.objects.filter(
            clinic_id=clinic_id, id=payload["service_id"], is_deleted=False
        ).exists():
            raise HttpError(400, "Invalid service_id")

    if payload.get("insurance_plan_id"):
        if not InsurancePlan.objects.filter(
            clinic_id=clinic_id, id=payload["insurance_plan_id"], is_deleted=False
        ).exists():
            raise HttpError(400, "Invalid insurance_plan_id")

    if payload.get("status") and payload["status"] not in VALID_STATUSES:
        raise HttpError(400, f"Invalid status. Choose from: {sorted(VALID_STATUSES)}")

    if payload.get("source") and payload["source"] not in VALID_SOURCES:
        raise HttpError(400, f"Invalid source. Choose from: {sorted(VALID_SOURCES)}")

    start = payload.get("start_time")
    end = payload.get("end_time")
    if start and end and end <= start:
        raise HttpError(400, "end_time must be after start_time")

    return payload


@router.get("", response=PaginatedOut[AppointmentOut], auth=jwt_auth)
def list_appointments(
    request,
    status: str | None = Query(None),
    doctor_id: UUID | None = Query(None),
    patient_id: UUID | None = Query(None),
    from_date: datetime | None = Query(None),
    to_date: datetime | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    clinic = clinic_from(request)
    qs = (
        Appointment.objects.filter(clinic=clinic)
        .select_related("doctor", "patient", "service", "insurance_plan")
        .order_by("-start_time")
    )
    if status:
        qs = qs.filter(status=status)
    if doctor_id:
        qs = qs.filter(doctor_id=doctor_id)
    if patient_id:
        qs = qs.filter(patient_id=patient_id)
    if from_date:
        qs = qs.filter(start_time__gte=from_date)
    if to_date:
        qs = qs.filter(start_time__lte=to_date)
    count = qs.count()
    results = [_serialize(a) for a in qs[offset : offset + limit]]
    return PaginatedOut(count=count, results=results)


@router.post("", response={201: AppointmentOut}, auth=jwt_auth)
def create_appointment(request, payload: AppointmentIn):
    clinic = clinic_from(request)
    data = payload.dict()
    if not data.get("confirmation_code"):
        data["confirmation_code"] = _confirmation_code()
    _resolve_fk(clinic.id, data)
    try:
        appt = Appointment.objects.create(clinic=clinic, **data)
    except IntegrityError as exc:
        raise HttpError(
            400,
            "Could not create appointment — double booking or duplicate confirmation code",
        ) from exc
    appt = _get_appointment(clinic.id, appt.id)
    return 201, _serialize(appt)


@router.get("/{appointment_id}", response=AppointmentOut, auth=jwt_auth)
def get_appointment(request, appointment_id: UUID):
    return _serialize(_get_appointment(clinic_from(request).id, appointment_id))


@router.patch("/{appointment_id}", response=AppointmentOut, auth=jwt_auth)
def update_appointment(request, appointment_id: UUID, payload: AppointmentUpdateIn):
    clinic_id = clinic_from(request).id
    appt = _get_appointment(clinic_id, appointment_id)
    data = payload.dict(exclude_unset=True)
    merged = {
        "doctor_id": data.get("doctor_id", appt.doctor_id),
        "patient_id": data.get("patient_id", appt.patient_id),
        "service_id": data.get("service_id", appt.service_id),
        "insurance_plan_id": data.get("insurance_plan_id", appt.insurance_plan_id),
        "start_time": data.get("start_time", appt.start_time),
        "end_time": data.get("end_time", appt.end_time),
        "status": data.get("status", appt.status),
        "source": data.get("source", appt.source),
    }
    _resolve_fk(clinic_id, merged)
    for field, value in data.items():
        setattr(appt, field, value)
    try:
        appt.save()
    except IntegrityError as exc:
        raise HttpError(400, "Could not update — possible double booking") from exc
    return _serialize(_get_appointment(clinic_id, appt.id))


@router.delete("/{appointment_id}", response=MessageOut, auth=jwt_auth)
def delete_appointment(request, appointment_id: UUID):
    """Cancel appointment (sets status=cancelled rather than hard delete)."""
    appt = _get_appointment(clinic_from(request).id, appointment_id)
    appt.status = AppointmentStatus.CANCELLED
    appt.save(update_fields=["status", "updated_at"])
    return MessageOut(detail="Appointment cancelled")
