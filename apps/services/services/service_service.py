"""Service creation — shared by apps/api/services/router.py and the
importer commit path (apps/importer/services/committer.py) so both go
through one code path rather than duplicating creation logic."""

from apps.clinics.models import Clinic
from apps.services.models import Service


def create_service(
    *,
    clinic: Clinic,
    name: str,
    description: str = "",
    code: str = "",
    category: str = "",
    duration_min: int = 30,
    price_cents: int | None = None,
    is_active: bool = True,
    metadata: dict | None = None,
) -> Service:
    return Service.objects.create(
        clinic=clinic,
        name=name,
        description=description,
        code=code,
        category=category,
        duration_min=duration_min,
        price_cents=price_cents,
        is_active=is_active,
        metadata=metadata or {},
    )
