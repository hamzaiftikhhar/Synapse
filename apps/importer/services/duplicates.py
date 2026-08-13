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
    *, record_type: str, name: str, clinic: Clinic, in_batch_names: list[str]
) -> dict | None:
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
