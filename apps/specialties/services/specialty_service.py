"""Specialty creation (incl. unique-slug generation) — shared by
apps/api/specialties/router.py and the importer commit path
(apps/importer/services/committer.py)."""

from uuid import UUID

from django.utils.text import slugify

from apps.clinics.models import Clinic
from apps.specialties.models import Specialty


def unique_slug(clinic_id: UUID, base: str, *, exclude_id: UUID | None = None) -> str:
    base = slugify(base)[:100] or "specialty"
    candidate = base
    n = 1
    qs = Specialty.objects.filter(clinic_id=clinic_id, slug=candidate)
    if exclude_id:
        qs = qs.exclude(id=exclude_id)
    while qs.exists():
        n += 1
        candidate = f"{base}-{n}"[:100]
        qs = Specialty.objects.filter(clinic_id=clinic_id, slug=candidate)
        if exclude_id:
            qs = qs.exclude(id=exclude_id)
    return candidate


def create_specialty(
    *,
    clinic: Clinic,
    name: str,
    slug: str = "",
    description: str = "",
    is_active: bool = True,
) -> Specialty:
    if not name.strip():
        raise ValueError("Specialty name is required")
    return Specialty.objects.create(
        clinic=clinic,
        name=name.strip(),
        slug=unique_slug(clinic.id, slug or name),
        description=description,
        is_active=is_active,
    )
