"""Patient profile operations — source of truth for widget identity."""

from __future__ import annotations

from uuid import UUID

from django.utils import timezone

from apps.clinics.models import Clinic
from apps.patients.models import Patient


def get_by_phone(*, clinic: Clinic, phone: str) -> Patient | None:
    return Patient.objects.filter(clinic=clinic, phone=phone).first()


def get_or_create_by_phone(
    *,
    clinic: Clinic,
    phone: str,
    first_name: str = "",
    last_name: str = "",
) -> tuple[Patient, bool]:
    """
    Ensure a Patient row exists for this clinic + phone.

    OTP verifies the phone on this record; it does not replace Patient identity.
    """
    patient = get_by_phone(clinic=clinic, phone=phone)
    if patient is not None:
        return patient, False

    patient = Patient.objects.create(
        clinic=clinic,
        phone=phone,
        first_name=first_name.strip() or "New",
        last_name=last_name.strip() or "Patient",
        is_verified=False,
    )
    return patient, True


def mark_phone_verified(patient: Patient) -> Patient:
    patient.is_verified = True
    patient.verified_at = timezone.now()
    patient.save(update_fields=["is_verified", "verified_at", "updated_at"])
    return patient


def update_profile(
    patient: Patient,
    *,
    first_name: str | None = None,
    last_name: str | None = None,
    email: str | None = None,
) -> Patient:
    fields: list[str] = []
    if first_name is not None and first_name.strip():
        patient.first_name = first_name.strip()
        fields.append("first_name")
    if last_name is not None and last_name.strip():
        patient.last_name = last_name.strip()
        fields.append("last_name")
    if email is not None:
        patient.email = email.strip()
        fields.append("email")
    if fields:
        fields.append("updated_at")
        patient.save(update_fields=fields)
    return patient


def get_for_clinic(*, clinic_id: UUID, patient_id: UUID) -> Patient | None:
    return Patient.objects.filter(clinic_id=clinic_id, pk=patient_id).first()
