"""Insurance plan creation — shared by apps/api/insurance/router.py and
the importer commit path (apps/importer/services/committer.py)."""

from apps.clinics.models import Clinic
from apps.insurance.models import InsurancePlan

_PLAN_TYPE_MAX = 50


def create_insurance_plan(
    *,
    clinic: Clinic,
    provider_name: str,
    plan_name: str = "",
    plan_type: str = "",
    is_accepted: bool = True,
    notes: str = "",
    metadata: dict | None = None,
) -> InsurancePlan:
    if not provider_name.strip():
        raise ValueError("Insurance provider name is required")
    return InsurancePlan.objects.create(
        clinic=clinic,
        provider_name=provider_name.strip(),
        plan_name=(plan_name or "").strip(),
        plan_type=(plan_type or "").strip()[:_PLAN_TYPE_MAX],
        is_accepted=is_accepted,
        notes=notes or "",
        metadata=metadata or {},
    )
