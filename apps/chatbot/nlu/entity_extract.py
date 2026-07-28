"""Local regex entity extraction — used after rule matches and as LLM assist."""

from __future__ import annotations

import re
from typing import Any

_DATE_PATTERNS = [
    r"\b(?:next\s+)?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    r"\btoday\b",
    r"\btomorrow\b",
    r"\bnext week\b",
    r"\bthis week\b",
]

_TIME_PATTERNS = [
    r"\bmorning\b",
    r"\bafternoon\b",
    r"\bevening\b",
    r"\bnoon\b",
    r"\bnight\b",
]

_SPECIALTIES = [
    "cardiology",
    "cardiologist",
    "dermatology",
    "dermatologist",
    "pediatrics",
    "pediatrician",
    "orthopedics",
    "orthopedic",
    "neurology",
    "neurologist",
    "psychiatry",
    "psychiatrist",
    "ophthalmology",
    "ophthalmologist",
    "gynecology",
    "gynecologist",
    "urology",
    "urologist",
    "oncology",
    "oncologist",
    "ent",
    "family medicine",
    "internal medicine",
    "general practice",
]

_INSURANCE_BRANDS = [
    "blue cross blue shield",
    "blue cross",
    "bluecross",
    "aetna",
    "united healthcare",
    "unitedhealthcare",
    "cigna",
    "humana",
    "kaiser",
    "medicaid",
    "medicare",
    "tricare",
    "anthem",
    "oscar",
    "molina",
]

_EMERGENCY_SYMPTOMS = [
    "chest pain",
    "left arm numbness",
    "arm numbness",
    "can't breathe",
    "cannot breathe",
    "difficulty breathing",
    "shortness of breath",
    "heart attack",
    "stroke",
    "severe bleeding",
    "unconscious",
    "choking",
    "suicidal",
]

_DOCTOR_RE = re.compile(
    r"\b(?:dr\.?|doctor)\s+([A-Za-z][A-Za-z'-]{1,30})(?:\s+([A-Za-z][A-Za-z'-]{1,30}))?",
    re.IGNORECASE,
)

_NEGATION_RE = re.compile(
    r"\b(don'?t|do not|doesn'?t|didn'?t|never|not|no longer|won'?t|cannot|can'?t)\b",
    re.IGNORECASE,
)

_COMPOUND_RE = re.compile(
    r"\b(and also|also tell|plus|in addition|as well as|and can|and do)\b|\?.*\?",
    re.IGNORECASE,
)


def has_negation_near(text: str, keyword: str, window: int = 40) -> bool:
    """True if a negation appears near the keyword."""
    for match in re.finditer(re.escape(keyword), text, re.IGNORECASE):
        start = max(0, match.start() - window)
        chunk = text[start : match.start()]
        if _NEGATION_RE.search(chunk):
            return True
    return False


def looks_like_compound(text: str) -> bool:
    """Multi-clause / multi-question messages should not use single-intent rules."""
    if _COMPOUND_RE.search(text):
        return True
    if text.count("?") >= 2:
        return True
    return False


def extract_entities(text: str) -> dict[str, Any]:
    """Extract entity lists from free text (deterministic)."""
    lower = text.lower()
    return {
        "doctor_name": _extract_doctors(text),
        "specialty": _extract_list(lower, _SPECIALTIES),
        "service": None,
        "insurance_provider": _extract_insurance(lower),
        "date": _extract_patterns(lower, _DATE_PATTERNS),
        "time": _extract_patterns(lower, _TIME_PATTERNS),
        "patient_name": None,
        "location": None,
        "symptom": None,
    }


def extract_emergency_symptoms(text: str) -> list[str]:
    lower = text.lower()
    found: list[str] = []
    for symptom in _EMERGENCY_SYMPTOMS:
        if symptom in lower and symptom not in found:
            found.append(symptom)
    return found


def _extract_doctors(text: str) -> list[str] | None:
    names: list[str] = []
    for match in _DOCTOR_RE.finditer(text):
        first = match.group(1)
        last = match.group(2)
        # Skip common non-name tokens after Dr.
        if first.lower() in {"available", "is", "are", "the", "a", "an"}:
            continue
        name = first if not last else f"{first} {last}"
        cleaned = name.strip(" .,?!")
        if cleaned and cleaned.lower() not in {n.lower() for n in names}:
            names.append(cleaned)
    return names or None


def _extract_insurance(lower: str) -> list[str] | None:
    found: list[str] = []
    for brand in sorted(_INSURANCE_BRANDS, key=len, reverse=True):
        if brand in lower:
            # Prefer longer matches; skip if already covered by longer brand
            if any(brand in existing.lower() for existing in found):
                continue
            if any(existing.lower() in brand for existing in found):
                continue
            # Title-case display
            display = " ".join(w.capitalize() for w in brand.split())
            if brand == "bluecross":
                display = "Blue Cross"
            found.append(display)
    # Also catch "Blue Cross Origin" style
    m = re.search(
        r"\b((?:blue\s*cross(?:\s*blue\s*shield)?|aetna|cigna|humana|kaiser|"
        r"united\s*healthcare?|medicare|medicaid|anthem|oscar|molina)"
        r"(?:\s+[a-z0-9]+){0,2})\b",
        lower,
    )
    if m:
        phrase = " ".join(w.capitalize() for w in m.group(1).split())
        if not any(phrase.lower() == f.lower() or phrase.lower() in f.lower() for f in found):
            found.append(phrase)
    return found or None


def _extract_patterns(lower: str, patterns: list[str]) -> list[str] | None:
    found: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, lower):
            value = match.group(0)
            if value not in found:
                found.append(value)
    return found or None


def _extract_list(lower: str, candidates: list[str]) -> list[str] | None:
    found: list[str] = []
    for item in candidates:
        if re.search(rf"\b{re.escape(item)}\b", lower):
            found.append(item)
    return found or None


def merge_entities(
    base: dict[str, Any] | None,
    extracted: dict[str, Any],
) -> dict[str, Any]:
    """Fill missing entity fields from local extraction; prefer existing non-null."""
    out = dict(base or {})
    for key, value in extracted.items():
        current = out.get(key)
        if current in (None, "", [], ()):
            out[key] = value
        elif isinstance(current, str) and value:
            # Promote scalar → list if extraction found more
            if isinstance(value, list):
                merged = [current]
                for item in value:
                    if item.lower() not in {c.lower() for c in merged}:
                        merged.append(item)
                out[key] = merged
    return out
