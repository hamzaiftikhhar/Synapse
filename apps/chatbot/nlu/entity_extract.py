"""Local regex entity extraction — used after rule matches and as LLM assist."""

from __future__ import annotations

import re
from typing import Any

from apps.chatbot.nlu.emergency_patterns import SYMPTOM_CUE_RE as _SYMPTOM_CUE_RE

_DATE_PATTERNS = [
    r"\bnext\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    r"\b(?:next\s+)?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    # Abbreviations that are never ordinary English words, so they stand
    # alone safely with no framing required.
    r"\b(?:tues|weds|thurs|thur|mon|tue|thu|fri)\b",
    # wed/sat are occasionally real words ("wed" the verb, "sat" past tense
    # of sit) but rarely collide in clinic chat, so a wider set of framing
    # words is safe.
    r"\b(?:on|this|next|for|of)\s+(?:wed|sat)\b",
    # sun stays strictly framed — "sun damage"/"sun exposure"/"protection
    # from/for sun" is routine phrasing at a dermatology clinic, so "for"/
    # "of" would misread it as Sunday. Only on/this/next (or the correctly-
    # spelled time-of-day suffix below) count.
    r"\b(?:on|this|next)\s+sun\b",
    r"\b(?:wed|sat|sun)\s+"
    r"(?:morning|afternoon|evening|night|noon)\b",
    r"\btoday\b",
    r"\btonight\b",
    r"\btomorrow\b",
    r"\bnext week\b",
    r"\bthis week\b",
    r"\bin\s+\d+\s+weeks?\b",
    r"\bin\s+\d+\s+days?\b",
    r"\bsame\s+day\b",
    r"\basap\b",
    r"\bas\s+soon\s+as\s+possible\b",
    r"\bnext\s+available\b",
    r"\b\d{4}-\d{2}-\d{2}\b",
    r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|"
    r"dec(?:ember)?)\s+\d{1,2}(?:st|nd|rd|th)?\b",
]

_TIME_PATTERNS = [
    # Clock times first so they win over vague "evening" when both appear
    r"\b\d{1,2}:\d{2}\s*(?:a\.?m\.?|p\.?m\.?)\b",
    r"\b\d{1,2}\s*(?:a\.?m\.?|p\.?m\.?)\b",
    r"\b\d{1,2}:\d{2}\b",
    r"\bmorning\b",
    r"\bafternoon\b",
    r"\bevening\b",
    r"\bnoon\b",
    r"\bnight\b",
    r"\bafter\s+work\b",
    r"\bafter\s+\d{1,2}\s*(?:am|pm)?\b",
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
    "medi-cal",
    "medi cal",
    "denti-cal",
    "denti cal",
    "tricare",
    "anthem",
    "oscar",
    "molina",
]

_EMERGENCY_SYMPTOMS = [
    "chest pain",
    "chest pressure",
    "chest tightness",
    "chest hurts",
    "tight pressure",
    "pain in my chest",
    "pain in chest",
    "pressure in his chest",
    "pressure in her chest",
    "pressure in my chest",
    "radiating down his arm",
    "radiating down her arm",
    "radiating down my arm",
    "radiating to my arm",
    "left arm numbness",
    "arm numbness",
    "severe shortness of breath",
    "hard to swallow",
    "trouble swallowing",
    "tongue feels huge",
    "tongue swelling",
    "lips are tingling",
    "dizzy and faint",
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
    r"\b(and also|also tell|plus|in addition|as well as|and can|and do)\b",
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
    if _COMPOUND_RE.search(text or ""):
        return True
    # Distinct question clauses only; ignore polite tails like "hours? please"
    pieces = [c.strip() for c in re.split(r"\?", text or "") if c.strip()]
    if len(pieces) >= 2:
        trailing_fillers = {
            "please",
            "pls",
            "thanks",
            "thank you",
            "thx",
            "ok",
            "okay",
        }
        if len(pieces) == 2 and pieces[1].lower() in trailing_fillers:
            return False
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


def has_symptom_cues(text: str) -> bool:
    """True when message contains emergency/soft-symptom language."""
    return bool(_SYMPTOM_CUE_RE.search(text or ""))


def extract_emergency_symptoms(text: str) -> list[str]:
    lower = text.lower()
    found: list[str] = []
    for symptom in _EMERGENCY_SYMPTOMS:
        if symptom in lower and symptom not in found:
            found.append(symptom)
    if not found and has_symptom_cues(text):
        if "chest" in lower:
            found.append("chest symptoms")
        if "arm" in lower:
            found.append("arm symptoms")
        if not found:
            found.append("emergency symptoms")
    return found


_DOCTOR_NAME_STOPWORDS = frozenset(
    {
        "available", "availability", "is", "are", "the", "a", "an", "please",
        "here", "there", "near", "for", "me", "my", "our", "your",
        "today", "tomorrow", "yesterday", "tonight", "now",
        "who", "that", "this", "with", "and", "or", "to", "from", "about",
        "list", "find", "help", "need", "want", "looking", "good", "best",
        "free", "open", "any", "some", "all", "on", "in", "at", "by",
        "morning", "afternoon", "evening", "slot", "slots",
        "appointment", "appointments", "schedule", "scheduling",
        "asap", "instantly", "immediately", "earliest", "soonest",
        "whenever", "anytime", "away",
        "dr", "doctor", "doc", "doctors",
    }
)

_DOCTOR_NAME_PHRASE_NOISE = (
    r"\bright\s+away\b",
    r"\bas\s+soon\s+as\s+possible\b",
    r"\bnext\s+available\b",
)


def clean_doctor_name(value: str | None) -> str | None:
    """Drop temporal/ASAP tokens the model glued onto a doctor name.

    'maya yesterday' / 'maya instantly' still mention Maya; the extra
    tokens must not survive into SQL `icontains` filters.
    """
    text = str(value or "").strip()
    if not text:
        return None
    for phrase in _DOCTOR_NAME_PHRASE_NOISE:
        text = re.sub(phrase, " ", text, flags=re.I)
    tokens = re.findall(r"[A-Za-z][A-Za-z'-]*", text)
    kept = [t for t in tokens if t.lower() not in _DOCTOR_NAME_STOPWORDS]
    if not kept:
        return None
    return " ".join(kept)


def _extract_doctors(text: str) -> list[str] | None:
    names: list[str] = []
    for match in _DOCTOR_RE.finditer(text):
        first = match.group(1)
        last = match.group(2)
        # Skip common non-name tokens after Dr./doctor
        if first.lower() in _DOCTOR_NAME_STOPWORDS:
            continue
        name = first if not last else f"{first} {last}"
        cleaned = clean_doctor_name(name)
        if cleaned and cleaned.lower() not in {n.lower() for n in names}:
            names.append(cleaned)
    return names or None


def _extract_insurance(lower: str) -> list[str] | None:
    """Extract insurance brand names only — never trailing context words."""
    found: list[str] = []
    # Longest-first so "blue cross blue shield" wins over "blue cross"
    for brand in sorted(_INSURANCE_BRANDS, key=len, reverse=True):
        if re.search(rf"\b{re.escape(brand)}\b", lower):
            display = {
                "bluecross": "Blue Cross",
                "blue cross": "Blue Cross",
                "blue cross blue shield": "Blue Cross Blue Shield",
                "united healthcare": "United Healthcare",
                "unitedhealthcare": "United Healthcare",
            }.get(brand, " ".join(w.capitalize() for w in brand.split()))
            # Skip if a longer brand already covers this
            if any(display.lower() in existing.lower() for existing in found):
                continue
            # Remove shorter brands already added that are substrings
            found = [f for f in found if f.lower() not in display.lower()]
            found.append(display)
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
