"""Best-effort entity resolution against clinic ORM."""

from __future__ import annotations

from django.db.models import Q

from apps.clinics.models import Clinic
from apps.chatbot.nlu.schemas import ExtractedEntities, ResolvedIds


def resolve_entities(
    clinic: Clinic,
    entities: ExtractedEntities,
) -> ResolvedIds:
    """
    Match extracted names to clinic-scoped records.

    Unmatched entities leave IDs as None — never raises.
    """
    return ResolvedIds(
        doctor_id=_match_doctor(clinic, entities.doctor_name),
        specialty_id=_match_specialty(clinic, entities.specialty),
        service_id=_match_service(clinic, entities.service),
        insurance_plan_id=_match_insurance(clinic, entities.insurance_provider),
    )


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


def _match_doctor(clinic: Clinic, name: str | None) -> str | None:
    if not name:
        return None
    from apps.doctors.models import Doctor

    needle = _normalize(name)
    qs = Doctor.objects.filter(
        clinic=clinic,
        is_deleted=False,
        is_active=True,
    )
    # Prefer icontains on full_name
    hit = qs.filter(full_name__icontains=name.strip()).order_by("full_name").first()
    if hit:
        return str(hit.id)
    for doctor in qs.only("id", "full_name")[:100]:
        if needle in _normalize(doctor.full_name) or _normalize(doctor.full_name) in needle:
            return str(doctor.id)
    return None


def _match_specialty(clinic: Clinic, name: str | None) -> str | None:
    if not name:
        return None
    from apps.specialties.models import Specialty

    needle = _normalize(name)
    qs = Specialty.objects.filter(clinic=clinic, is_deleted=False, is_active=True)
    hit = (
        qs.filter(Q(name__icontains=name.strip()) | Q(slug__icontains=needle.replace(" ", "-")))
        .order_by("name")
        .first()
    )
    if hit:
        return str(hit.id)
    for row in qs.only("id", "name", "slug")[:100]:
        if needle in _normalize(row.name) or needle.replace(" ", "-") in (row.slug or ""):
            return str(row.id)
    return None


def _match_service(clinic: Clinic, name: str | None) -> str | None:
    if not name:
        return None
    from apps.services.models import Service

    qs = Service.objects.filter(clinic=clinic, is_deleted=False, is_active=True)
    hit = qs.filter(name__icontains=name.strip()).order_by("name").first()
    return str(hit.id) if hit else None


def _match_insurance(clinic: Clinic, name: str | None) -> str | None:
    if not name:
        return None
    from apps.insurance.models import InsurancePlan

    qs = InsurancePlan.objects.filter(
        clinic=clinic,
        is_deleted=False,
        is_accepted=True,
    )
    hit = (
        qs.filter(
            Q(provider_name__icontains=name.strip())
            | Q(plan_name__icontains=name.strip())
        )
        .order_by("provider_name")
        .first()
    )
    return str(hit.id) if hit else None
