"""Possible-duplicate detection for imported providers/services/specialties.

Pure stdlib difflib — no new dependency. Never blocks an import; a
duplicate match is surfaced to the human reviewer (ImportRecord.status =
DUPLICATE, ImportRecord.duplicate_match populated) who decides whether to
merge, skip, or create anyway.
"""

from __future__ import annotations

from difflib import SequenceMatcher

from apps.clinics.models import Clinic
from apps.importer.models import ImportRecordType

# Insurance identities are (payer, plan, network). Using a control character
# so a plan named "Gold|PPO" cannot collide with the encoding.
_INSURANCE_KEY_SEP = "\x1f"

# Below this ratio, two names are treated as unrelated. Chosen so a small
# typo ("Dr. Jon Smith" vs "Dr. John Smith", ~0.92) flags, but a genuinely
# different person with a similar surname ("Dr. James Smith" vs
# "Dr. John Smith", ~0.78) does not.
SIMILARITY_THRESHOLD = 0.85


def _live_names_for(record_type: str, clinic: Clinic) -> list[tuple[str, str]]:
    """Returns [(id, name)] for the model this record_type maps onto."""
    if record_type == ImportRecordType.PROVIDERS:
        from apps.doctors.models import Doctor

        rows = Doctor.objects.filter(clinic=clinic, is_deleted=False).values_list("id", "full_name")
    elif record_type == ImportRecordType.SERVICES:
        from apps.services.models import Service

        rows = Service.objects.filter(clinic=clinic, is_deleted=False).values_list("id", "name")
    elif record_type == ImportRecordType.SPECIALTIES:
        from apps.specialties.models import Specialty

        rows = Specialty.objects.filter(clinic=clinic, is_deleted=False).values_list("id", "name")
    else:
        return []
    return [(str(row_id), name) for row_id, name in rows]


def insurance_identity(provider_name: str, plan_name: str = "", plan_type: str = "") -> str:
    return _INSURANCE_KEY_SEP.join(
        [
            provider_name.strip().lower(),
            (plan_name or "").strip().lower(),
            (plan_type or "").strip().lower(),
        ]
    )


def extra_from_canonical(record_type: str, canonical_data: dict) -> dict:
    if record_type != ImportRecordType.INSURANCE:
        return {}
    return {
        "plan_name": (canonical_data.get("plan_name") or {}).get("value") or "",
        "plan_type": (canonical_data.get("plan_type") or {}).get("value") or "",
    }


def batch_token(record_type: str, name: str, extra: dict | None = None) -> str:
    extra = extra or {}
    if record_type == ImportRecordType.INSURANCE:
        return insurance_identity(name, extra.get("plan_name", ""), extra.get("plan_type", ""))
    return name


def _insurance_label(provider_name: str, plan_name: str = "", plan_type: str = "") -> str:
    return " · ".join(
        part for part in [provider_name.strip(), (plan_name or "").strip(), (plan_type or "").strip()] if part
    )


def _find_insurance_duplicate(
    *,
    clinic: Clinic,
    provider_name: str,
    plan_name: str,
    plan_type: str,
    in_batch_names: list[str],
) -> dict | None:
    """Exact (payer, plan, network) match — not fuzzy.

    Fuzzy matching on payer alone would flag Aetna Gold and Aetna Silver as
    the same row. Fuzzy matching on a concatenated label would still flag
    Aetna Gold PPO vs Aetna Gold HMO (similarity ~0.86, above the 0.85
    doctor-name threshold). Insurance catalogs are supposed to hold both.
    """
    if not provider_name or not provider_name.strip():
        return None

    key = insurance_identity(provider_name, plan_name, plan_type)
    from apps.insurance.models import InsurancePlan

    rows = InsurancePlan.objects.filter(clinic=clinic, is_deleted=False).values_list(
        "id", "provider_name", "plan_name", "plan_type"
    )
    for row_id, existing_provider, existing_plan, existing_type in rows:
        if insurance_identity(existing_provider, existing_plan, existing_type) == key:
            return {
                "model": ImportRecordType.INSURANCE,
                "id": str(row_id),
                "row_number": None,
                "similarity": 1.0,
                "label": _insurance_label(existing_provider, existing_plan, existing_type),
            }

    if key in in_batch_names:
        return {
            "model": ImportRecordType.INSURANCE,
            "id": None,
            "row_number": None,
            "similarity": 1.0,
            "label": _insurance_label(provider_name, plan_name, plan_type),
        }
    return None


def _best_match(name: str, candidates: list[tuple[str, str]]) -> tuple[str, str, float] | None:
    normalized = name.strip().lower()
    best: tuple[str, str, float] | None = None
    for candidate_id, candidate_name in candidates:
        candidate_normalized = candidate_name.strip().lower()
        if normalized == candidate_normalized:
            return candidate_id, candidate_name, 1.0
        ratio = SequenceMatcher(None, normalized, candidate_normalized).ratio()
        if ratio >= SIMILARITY_THRESHOLD and (best is None or ratio > best[2]):
            best = (candidate_id, candidate_name, ratio)
    return best


def find_duplicate(
    *,
    record_type: str,
    name: str,
    clinic: Clinic,
    in_batch_names: list[str],
    extra: dict | None = None,
) -> dict | None:
    extra = extra or {}
    if record_type == ImportRecordType.INSURANCE:
        return _find_insurance_duplicate(
            clinic=clinic,
            provider_name=name,
            plan_name=extra.get("plan_name", ""),
            plan_type=extra.get("plan_type", ""),
            in_batch_names=in_batch_names,
        )

    if not name or not name.strip():
        return None

    live_match = _best_match(name, _live_names_for(record_type, clinic))
    if live_match:
        match_id, match_name, similarity = live_match
        return {
            "model": record_type,
            "id": match_id,
            "row_number": None,
            "similarity": round(similarity, 2),
            "label": match_name,
        }

    batch_match = _best_match(name, [("", other) for other in in_batch_names])
    if batch_match:
        _, match_name, similarity = batch_match
        return {
            "model": record_type,
            "id": None,
            "row_number": None,
            "similarity": round(similarity, 2),
            "label": match_name,
        }

    return None
