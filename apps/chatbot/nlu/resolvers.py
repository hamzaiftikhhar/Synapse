"""Best-effort entity resolution against clinic ORM (fuzzy + multi-value)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from django.db.models import Q

from apps.clinics.models import Clinic
from apps.chatbot.nlu.schemas import ExtractedEntities, ResolvedIds
from apps.chatbot.routing.signals import STOPWORDS

# Confidence bands for doctor matching
HIGH_CONFIDENCE = 0.85
MEDIUM_CONFIDENCE = 0.65
DEFAULT_THRESHOLD = 0.60


@dataclass(frozen=True)
class DoctorCandidate:
    doctor: dict[str, Any]
    score: float
    match_type: str = "fuzzy"


@dataclass(frozen=True)
class DoctorResolution:
    """Result of clinic-scoped doctor resolution with confidence bands."""

    status: str  # resolved | clarify | unknown
    doctor: dict[str, Any] | None
    candidates: tuple[DoctorCandidate, ...]
    confidence_band: str  # high | medium | low
    best_score: float = 0.0

    @property
    def needs_clarification(self) -> bool:
        return self.status == "clarify"


def confidence_band(score: float) -> str:
    if score >= HIGH_CONFIDENCE:
        return "high"
    if score >= MEDIUM_CONFIDENCE:
        return "medium"
    return "low"


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


def _strip_doctor_prefix(text: str) -> str:
    return re.sub(
        r"^(?:dr\.?|doctor|doc)\.?\s+",
        "",
        text.strip(),
        flags=re.I,
    )


def _doctor_name_tokens(full_name: str) -> list[str]:
    cleaned = (full_name or "").replace("Dr.", "").replace("Dr", "").strip()
    return [t for t in cleaned.split() if len(t) > 2]


def resolve_doctor_candidates(
    clinic: Clinic, text: str | None, *, limit: int = 3
) -> DoctorResolution:
    """Rank clinic doctors against free text with confidence bands."""
    query = (text or "").strip()
    if not query:
        return DoctorResolution(status="unknown", doctor=None, candidates=(), confidence_band="low")

    from apps.doctors.models import Doctor

    doctors = list(
        Doctor.objects.filter(clinic=clinic, is_deleted=False, is_active=True)
        .only("id", "full_name", "title", "bio")[:100]
    )
    lower = query.lower()
    scored: list[DoctorCandidate] = []

    for doctor in doctors:
        if not doctor.full_name:
            continue
        name_lower = doctor.full_name.lower()
        score = 0.0
        match_type = "fuzzy"

        if name_lower in lower:
            score = 1.0
            match_type = "full_substring"
        else:
            parts = _doctor_name_tokens(doctor.full_name)
            if parts and len(parts[-1]) > 3 and parts[-1].lower() in lower:
                score = max(score, 0.92)
                match_type = "last_name"
            if len(parts) >= 2:
                first_last = f"{parts[0]} {parts[-1]}".lower()
                if first_last in lower:
                    score = max(score, 0.95)
                    match_type = "first_last"

            words = [
                w.strip(".,!?")
                for w in query.split()
                if len(w.strip(".,!?")) > 2
                and w.lower() not in STOPWORDS
                and w.lower() not in {"doctor", "dr", "doc", "book"}
            ]
            for word in words:
                bare = _strip_doctor_prefix(word)
                for token in parts:
                    token_score = _fuzzy_score(bare or word, token)
                    if token_score > score:
                        score = token_score
                        match_type = "token_fuzzy"
                whole_score = _fuzzy_score(bare or word, doctor.full_name)
                if whole_score > score:
                    score = whole_score
                    match_type = "name_fuzzy"

        if score >= DEFAULT_THRESHOLD:
            scored.append(
                DoctorCandidate(
                    doctor=_doctor_payload(doctor),
                    score=round(score, 3),
                    match_type=match_type,
                )
            )

    scored.sort(key=lambda c: c.score, reverse=True)
    top = scored[:limit]
    if not top:
        return DoctorResolution(status="unknown", doctor=None, candidates=(), confidence_band="low")

    best = top[0]
    band = confidence_band(best.score)
    if band == "high":
        return DoctorResolution(
            status="resolved",
            doctor=best.doctor,
            candidates=tuple(top),
            confidence_band=band,
            best_score=best.score,
        )
    if band == "medium":
        return DoctorResolution(
            status="clarify",
            doctor=best.doctor,
            candidates=tuple(top),
            confidence_band=band,
            best_score=best.score,
        )
    return DoctorResolution(
        status="unknown",
        doctor=None,
        candidates=tuple(top),
        confidence_band=band,
        best_score=best.score,
    )


def resolve_doctor_from_text(
    clinic: Clinic, text: str | None, *, threshold: float = DEFAULT_THRESHOLD
) -> dict[str, Any] | None:
    """Resolve a doctor from free text using ranked candidates + confidence bands."""
    resolution = resolve_doctor_candidates(clinic, text)
    if resolution.status == "resolved":
        return resolution.doctor
    if resolution.status == "clarify" and resolution.best_score >= threshold:
        return resolution.doctor
    if resolution.doctor and resolution.best_score >= threshold:
        return resolution.doctor
    return None


def did_you_mean_doctor_reply(resolution: DoctorResolution) -> str | None:
    """Patient-facing clarifier for medium-confidence doctor matches."""
    if resolution.status != "clarify" or not resolution.candidates:
        return None
    best = resolution.candidates[0].doctor
    name = best.get("name") or "that doctor"
    alts = [c.doctor.get("name") for c in resolution.candidates[1:3] if c.doctor.get("name")]
    if alts:
        return f"Did you mean {name}? Other close matches: {', '.join(alts)}."
    return f"Did you mean {name}?"


def _doctor_payload(doctor: Any) -> dict[str, Any]:
    return {
        "id": str(doctor.id),
        "name": doctor.full_name,
        "title": doctor.title or "",
        "bio": (doctor.bio or "")[:240],
    }


def resolve_specialty_for_service(clinic: Clinic, service_id: str | None) -> str | None:
    """Resolve the specialty most associated with a known service, grounded in
    real Doctor<->Service<->Specialty relations (Service.category is free text
    and unused elsewhere in the chat pipeline — this ranks specialties by how
    many doctors performing this service belong to each one)."""
    if not service_id:
        return None
    from django.db.models import Count

    from apps.specialties.models import Specialty

    hit = (
        Specialty.objects.filter(
            clinic=clinic,
            is_deleted=False,
            is_active=True,
            doctors__is_deleted=False,
            doctors__is_active=True,
            doctors__services__id=service_id,
            doctors__services__is_deleted=False,
        )
        .annotate(cnt=Count("doctors", distinct=True))
        .order_by("-cnt")
        .first()
    )
    return str(hit.id) if hit else None


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
    # Include rejected plans — otherwise "Medicaid" fuzzy-matches "Medicare"
    qs = InsurancePlan.objects.filter(clinic=clinic, is_deleted=False)

    # Exact provider/plan name (case-insensitive) first
    exact = (
        qs.filter(Q(provider_name__iexact=needle) | Q(plan_name__iexact=needle))
        .order_by("-is_accepted", "provider_name")
        .first()
    )
    if exact:
        return str(exact.id)

    # Contains — prefer longer/closer provider names; still include rejected
    hit = (
        qs.filter(
            Q(provider_name__icontains=needle) | Q(plan_name__icontains=needle)
        )
        .order_by("-is_accepted", "provider_name")
        .first()
    )
    if hit:
        # Guard: don't let "Medicaid" resolve via a looser contains on unrelated rows
        return str(hit.id)

    # Brand token fallback
    tokens = [t for t in needle.lower().split() if len(t) > 2]
    for size in range(min(3, len(tokens)), 0, -1):
        phrase = " ".join(tokens[:size])
        hit = (
            qs.filter(
                Q(provider_name__icontains=phrase) | Q(plan_name__icontains=phrase)
            )
            .order_by("-is_accepted", "provider_name")
            .first()
        )
        if hit:
            return str(hit.id)

    # Strict fuzzy only — avoid Medicare↔Medicaid (edit distance 2 ≈ 0.75)
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
    return best_id if best_score >= 0.9 else None


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
