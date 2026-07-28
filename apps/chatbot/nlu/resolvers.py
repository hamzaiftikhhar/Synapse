"""Best-effort entity resolution against clinic ORM (fuzzy + multi-value)."""

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

    Supports scalar or list entity values. Unmatched leave IDs as None.
    """
    doctor_ids = _match_many(clinic, entities.doctor_name, _match_doctor)
    specialty_ids = _match_many(clinic, entities.specialty, _match_specialty)
    insurance_ids = _match_many(clinic, entities.insurance_provider, _match_insurance)

    return ResolvedIds(
        doctor_id=_collapse_ids(doctor_ids),
        specialty_id=_collapse_ids(specialty_ids),
        service_id=_match_service(clinic, _first_str(entities.service)),
        insurance_plan_id=_collapse_ids(insurance_ids),
    )


def _first_str(value: str | list[str] | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _as_list(value: str | list[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [v for v in value if v]
    return [value] if value else []


def _collapse_ids(ids: list[str]) -> list[str] | str | None:
    if not ids:
        return None
    if len(ids) == 1:
        return ids[0]
    return ids


def _match_many(clinic: Clinic, value: str | list[str] | None, matcher) -> list[str]:
    found: list[str] = []
    for item in _as_list(value):
        hit = matcher(clinic, item)
        if hit and hit not in found:
            found.append(hit)
    return found


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        curr = [i]
        for j, cb in enumerate(b, start=1):
            ins = curr[j - 1] + 1
            delete = prev[j] + 1
            sub = prev[j - 1] + (ca != cb)
            curr.append(min(ins, delete, sub))
        prev = curr
    return prev[-1]


def _fuzzy_score(needle: str, candidate: str) -> float:
    """0–1 similarity; 1 is exact."""
    n = _normalize(needle)
    c = _normalize(candidate)
    if not n or not c:
        return 0.0
    if n == c:
        return 1.0
    if n in c or c in n:
        return 0.92
    # Token overlap (first name / last name)
    n_tokens = set(n.split())
    c_tokens = set(c.split())
    if n_tokens & c_tokens:
        return 0.85
    dist = _levenshtein(n, c)
    maxlen = max(len(n), len(c))
    return max(0.0, 1.0 - (dist / maxlen))


def _match_doctor(clinic: Clinic, name: str | None) -> str | None:
    if not name:
        return None
    from apps.doctors.models import Doctor

    qs = Doctor.objects.filter(
        clinic=clinic,
        is_deleted=False,
        is_active=True,
    ).only("id", "full_name")[:100]

    best_id = None
    best_score = 0.0
    for doctor in qs:
        score = _fuzzy_score(name, doctor.full_name)
        # Also try against each token (e.g. "rajat" vs "Rajat Sharma")
        for token in doctor.full_name.split():
            score = max(score, _fuzzy_score(name, token))
        if score > best_score:
            best_score = score
            best_id = str(doctor.id)

    # Typo tolerance: "rjet" → "rajat" (~0.6+)
    if best_score >= 0.6:
        return best_id
    return None


def _match_specialty(clinic: Clinic, name: str | None) -> str | None:
    if not name:
        return None
    from apps.specialties.models import Specialty

    needle = _normalize(name)
    # Map common role nouns → specialty roots
    aliases = {
        "dermatologist": "dermatology",
        "cardiologist": "cardiology",
        "pediatrician": "pediatrics",
        "neurologist": "neurology",
        "psychiatrist": "psychiatry",
        "ophthalmologist": "ophthalmology",
        "gynecologist": "gynecology",
        "urologist": "urology",
        "oncologist": "oncology",
    }
    needle = aliases.get(needle, needle)

    qs = Specialty.objects.filter(clinic=clinic, is_deleted=False, is_active=True)
    hit = (
        qs.filter(Q(name__icontains=needle) | Q(slug__icontains=needle.replace(" ", "-")))
        .order_by("name")
        .first()
    )
    if hit:
        return str(hit.id)
    best_id = None
    best_score = 0.0
    for row in qs.only("id", "name", "slug")[:100]:
        score = max(_fuzzy_score(needle, row.name), _fuzzy_score(needle, row.slug or ""))
        if score > best_score:
            best_score = score
            best_id = str(row.id)
    return best_id if best_score >= 0.7 else None


def _match_insurance(clinic: Clinic, name: str | None) -> str | None:
    if not name:
        return None
    from apps.insurance.models import InsurancePlan

    needle = name.strip()
    qs = InsurancePlan.objects.filter(
        clinic=clinic,
        is_deleted=False,
        is_accepted=True,
    )

    # Exact / contains first (Medicaid → provider_name containing Medicaid)
    hit = (
        qs.filter(
            Q(provider_name__icontains=needle) | Q(plan_name__icontains=needle)
        )
        .order_by("provider_name")
        .first()
    )
    if hit:
        return str(hit.id)

    # Brand token fallback: "Blue Cross Origin" → match plans containing "Blue Cross"
    tokens = [t for t in needle.lower().split() if len(t) > 2]
    for size in range(min(3, len(tokens)), 0, -1):
        phrase = " ".join(tokens[:size])
        hit = (
            qs.filter(
                Q(provider_name__icontains=phrase) | Q(plan_name__icontains=phrase)
            )
            .order_by("provider_name")
            .first()
        )
        if hit:
            return str(hit.id)

    best_id = None
    best_score = 0.0
    for plan in qs.only("id", "provider_name", "plan_name")[:100]:
        score = max(
            _fuzzy_score(needle, plan.provider_name),
            _fuzzy_score(needle, plan.plan_name or ""),
            _fuzzy_score(needle, f"{plan.provider_name} {plan.plan_name}"),
        )
        if score > best_score:
            best_score = score
            best_id = str(plan.id)
    return best_id if best_score >= 0.5 else None


def _match_service(clinic: Clinic, name: str | None) -> str | None:
    if not name:
        return None
    from apps.services.models import Service

    needle = name.strip()
    qs = Service.objects.filter(clinic=clinic, is_deleted=False, is_active=True)
    hit = qs.filter(name__icontains=needle).order_by("name").first()
    if hit:
        return str(hit.id)
    best_id = None
    best_score = 0.0
    for row in qs.only("id", "name")[:100]:
        score = _fuzzy_score(needle, row.name)
        if score > best_score:
            best_score = score
            best_id = str(row.id)
    return best_id if best_score >= 0.55 else None
