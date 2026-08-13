"""
Soft symptom → specialty suggestions.

Never diagnoses. Language must stay advisory:
"Based on what you described, you may want to start with…"
"""

from __future__ import annotations

from typing import Any

# Keyword → specialty name hints (matched case-insensitively against clinic specialties)
_SYMPTOM_MAP: list[tuple[tuple[str, ...], tuple[str, ...]]] = [
    (
        ("headache", "migraine", "head pain", "dizziness", "seizure", "numbness"),
        ("neurology", "neurologist", "primary care", "general practice", "internal medicine"),
    ),
    (
        ("chest pain", "heart", "palpitation", "blood pressure", "cardiac", "shortness of breath"),
        ("cardiology", "cardiologist", "primary care", "general practice"),
    ),
    (
        ("stomach", "abdomen", "nausea", "diarrhea", "constipation", "acid reflux"),
        ("gastroenterology", "primary care", "general practice", "internal medicine"),
    ),
    (
        ("skin", "rash", "acne", "eczema", "mole", "itch", "itching", "scalp"),
        ("dermatology", "dermatologist", "primary care", "general practice"),
    ),
    (
        ("anxiety", "depression", "sleep", "insomnia", "mental"),
        ("psychiatry", "psychiatrist", "primary care", "psychology"),
    ),
    (
        ("pregnancy", "period", "obgyn", "gynecolog"),
        ("ob-gyn", "obstetrics", "gynecology", "women"),
    ),
    (
        ("joint", "back pain", "knee", "shoulder", "fracture", "sports", "leg pain", "leg", "hip"),
        ("orthopedic", "orthopedics", "sports medicine", "primary care", "general practice"),
    ),
    (
        ("ear", "nose", "throat", "sinus", "hearing"),
        ("ent", "otolaryngology", "primary care"),
    ),
    (
        ("eye", "vision", "blurry"),
        ("ophthalmology", "optometry", "eye"),
    ),
    (
        ("checkup", "check-up", "general", "fever", "cold", "flu", "cough", "pain"),
        ("primary care", "general practice", "internal medicine", "family"),
    ),
]


def suggest_specialties(
    clinic: Any,
    *,
    message: str = "",
    reason: str = "",
    limit: int = 4,
) -> tuple[list[dict[str, Any]], str]:
    """
    Return (suggested_specialty_dicts, guidance_text).

    Suggestions are intersected with the clinic's active specialties.
    """
    from apps.specialties.models import Specialty

    text = f"{message} {reason}".lower().strip()
    clinic_specs = list(
        Specialty.objects.filter(clinic=clinic, is_deleted=False, is_active=True).order_by("name")
    )
    if not clinic_specs:
        return [], "I can help you book an appointment. Let's get started."

    hinted_names: list[str] = []
    for keywords, specialty_hints in _SYMPTOM_MAP:
        if any(k in text for k in keywords):
            hinted_names.extend(specialty_hints)

    matched: list[Any] = []
    if hinted_names:
        for spec in clinic_specs:
            name_l = spec.name.lower()
            slug_l = (spec.slug or "").lower()
            if any(h in name_l or h in slug_l for h in hinted_names):
                if spec not in matched:
                    matched.append(spec)

    # Fall back to popular / first few clinic specialties
    if not matched:
        matched = clinic_specs[:limit]

    matched = matched[:limit]
    rows = [
        {
            "id": str(s.id),
            "name": s.name,
            "slug": s.slug,
            "description": (s.description or "")[:200],
            "plain_label": _plain_label(s.name),
        }
        for s in matched
    ]

    if hinted_names and rows:
        names = ", ".join(r["name"] for r in rows[:2])
        guidance = (
            f"Based on what you described, you may want to start with {names}. "
            "These are suggestions — not a diagnosis. You can choose a service or continue chatting."
        )
    else:
        guidance = (
            "I can help you book an appointment. Choose a service to continue, "
            "or pick a doctor directly."
        )

    return rows, guidance


def _plain_label(name: str) -> str:
    mapping = {
        "cardiology": "Cardiologist (Heart Doctor)",
        "neurology": "Neurologist (Brain & Nerves)",
        "dermatology": "Dermatologist (Skin)",
        "primary care": "Primary Care Physician",
        "general practice": "Primary Care / General Practice",
        "orthopedics": "Orthopedic Surgeon (Bones & Joints)",
        "psychiatry": "Psychiatrist (Mental Health)",
        "gastroenterology": "Gastroenterologist (Digestive)",
        "ophthalmology": "Eye Doctor",
        "ent": "Ear, Nose & Throat Doctor",
    }
    key = name.lower().strip()
    for k, v in mapping.items():
        if k in key:
            return v
    return name
