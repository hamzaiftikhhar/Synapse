"""Local regex entity extraction — used after rule matches and as LLM assist."""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

from apps.chatbot.nlu.emergency_patterns import SYMPTOM_CUE_RE as _SYMPTOM_CUE_RE
from apps.chatbot.nlu.emergency_patterns import (
    SYMPTOM_NARRATIVE_RE as _SYMPTOM_NARRATIVE_RE,
    is_informational_emergency_mention as _is_informational_emergency_mention,
)
from apps.chatbot.nlu.schemas import ExtractedEntities

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
    r"\b(?:and also|also tell|plus|in addition|as well as|and can|and do)\b"
    # "and is/are/what/..." plus a bare "s" (no apostrophe) for casual
    # contractions -- "and whats your address" doesn't match a plain
    # \bwhat\b (no boundary before the attached "s"), live-confirmed to
    # silently defeat compound detection for real patient phrasing.
    r"|\band (?:what|where|when|who|how|which|why|is|are)'?s?\b"
    # Comma-joined second question with no "and" at all -- "...cost of a
    # filling, do you offer root canals too" -- also live-confirmed to
    # slip through as a single, confidently-matched intent.
    r"|,\s*(?:do|does|is|are|can|will|whats|wheres|whens|what's|where's|when's)\b",
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
    """True when message contains emergency/soft-symptom language.

    Only consumer is classifier.py's hard emergency-override path (not
    routing/signals.py's own, separate has_symptom_cues), so the
    informational-question exception belongs here: "what causes a stroke"
    should not be treated as a live symptom cue (Phase 40).
    """
    text = text or ""
    if not _SYMPTOM_CUE_RE.search(text):
        return False
    if _is_informational_emergency_mention(text, _SYMPTOM_NARRATIVE_RE):
        return False
    return True


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


def _edit_distance_le(a: str, b: str, max_dist: int) -> bool:
    """True if the optimal-string-alignment distance between `a` and `b`
    (insert/delete/substitute, plus an adjacent-transposition operation)
    is <= max_dist. The transposition case matters here specifically: the
    live-confirmed bug this guards ("availabel"/"availalbe" for
    "available") is an adjacent-letter swap, which plain Levenshtein scores
    as distance 2 (two substitutions), not the single real-world typo it
    is -- silently defeating a distance-1 threshold for exactly the typo
    shape this check exists to catch. Early-exits on the length gap alone
    before running the DP table."""
    if abs(len(a) - len(b)) > max_dist:
        return False
    la, lb = len(a), len(b)
    d = [[0] * (lb + 1) for _ in range(la + 1)]
    for i in range(la + 1):
        d[i][0] = i
    for j in range(lb + 1):
        d[0][j] = j
    for i in range(1, la + 1):
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            d[i][j] = min(
                d[i - 1][j] + 1,
                d[i][j - 1] + 1,
                d[i - 1][j - 1] + cost,
            )
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[la][lb] <= max_dist


def _is_doctor_name_stopword(word: str) -> bool:
    """Exact stopword match, or a same-ballpark-length word within one
    character edit of a *longer* stopword (>= 6 chars on both sides) --
    catches common typos of high-frequency non-name words ("availabel" for
    "available") that would otherwise survive _DOCTOR_RE's capture and get
    misclassified as a doctor's name, live-confirmed in a rules_fallback
    trace. The length floor matters: fuzzy-matching against short
    stopwords ("a", "an", "is", "on") would risk dropping a real short
    name (e.g. "Ana" is one edit from "an") -- restricting the fuzzy check
    to long stopwords makes an accidental collision with a real name
    implausible while still catching realistic typos of longer words."""
    if word in _DOCTOR_NAME_STOPWORDS:
        return True
    if len(word) < 6:
        return False
    return any(
        len(stopword) >= 6 and _edit_distance_le(word, stopword, 1)
        for stopword in _DOCTOR_NAME_STOPWORDS
    )


def _extract_doctors(text: str) -> list[str] | None:
    names: list[str] = []
    for match in _DOCTOR_RE.finditer(text):
        first = match.group(1)
        last = match.group(2)
        # Skip common non-name tokens after Dr./doctor
        if _is_doctor_name_stopword(first.lower()):
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


# Fields the capability-resolution audit's live regression actually
# reproduced leaking from a prior turn's Recent: transcript text into the
# CURRENT turn's entities ("symptom", plus the same class of value:
# service/specialty/doctor/insurance a prior turn named). date/time/
# location/patient_name were a different, unaudited concern and
# deliberately left untouched here — smallest safe fix, not a general
# entity-hygiene pass.
#
# `language` was originally left out under that same "unaudited" call —
# but live-reproduced against a real Horizon Family Medicine transcript
# (ROADMAP.md): "please talk me in roman urdu" set entities.language=
# "Roman Urdu" once (a response-language preference, not a doctor-search
# request), and it then kept reappearing on every subsequent turn that
# never mentioned any language at all ("whats the speciality of dr
# marcus"). search_doctors's language filter (sql_tool/handlers/
# doctors.py) treats *any* entities.language value as "find a doctor who
# speaks this" and — correctly, on its own terms — filters to zero rows
# rather than silently ignoring an unresolvable language name ("Roman
# Urdu" has no ISO code of its own). The combination wiped out a real,
# otherwise-resolvable doctor lookup for a doctor ("Dr. Marcus Vance")
# that was named plainly in the current message. Same leak-detection
# mechanism as the other fields: only dropped when NOT grounded in the
# current message AND grounded in the recent-turns transcript, so a
# genuine "is there a Spanish-speaking doctor" (the word is right there
# in the current message) is completely unaffected.
_LEAK_PRONE_FIELDS = (
    "symptom",
    "service",
    "specialty",
    "doctor_name",
    "insurance_provider",
    "language",
)

_GROUNDING_TOKEN_RE = re.compile(r"[a-z0-9']+")


def _grounded_in(value_lower: str, text: str) -> bool:
    """True if `value_lower`'s content is substantiated by `text` — either
    verbatim, or (for multi-word values) via at least one non-trivial
    shared token. Deliberately loose (token overlap, not full-phrase
    match): the LLM may rephrase an entity slightly even when it IS
    grounded in the current message, and this only needs to distinguish
    "said again this turn" from "not said this turn at all", not do exact
    string matching."""
    if not value_lower or not text:
        return False
    if value_lower in text:
        return True
    tokens = [t for t in _GROUNDING_TOKEN_RE.findall(value_lower) if len(t) >= 4]
    if not tokens:
        return False
    return any(t in text for t in tokens)


def _leaked_from_history(value: str, message_lower: str, history_lower: str) -> bool:
    """An entity value counts as leaked only if it is NOT grounded in the
    current message AND IS grounded in the recent-turns transcript --
    i.e. it's provably copied from history, not some other, unrelated
    hallucination this function has no business touching."""
    value_lower = str(value or "").strip().lower()
    if not value_lower:
        return False
    if _grounded_in(value_lower, message_lower):
        return False
    return _grounded_in(value_lower, history_lower)


def scrub_entities_leaked_from_recent_turns(
    entities: ExtractedEntities,
    *,
    message: str,
    recent_turns: list[dict[str, Any]] | None,
) -> ExtractedEntities:
    """Enforce: recent conversation may give the model context, but must
    NEVER supply an entity value for the current message.

    The system prompt already tells the model this (nlu/prompts.py:
    "Never let recent turns override or supply an entity the current
    message doesn't itself state") — but live capability-resolution
    validation reproduced the model not reliably complying: a prior
    turn's symptom ("I cut my hand and need stitches") leaked into the
    very next, unrelated turn's entities.symptom in 4/10 real two-turn
    runs, derailing the response in 2/10. This is a deterministic
    backstop enforcing that same invariant in Python rather than trusting
    prompt compliance a second time — not a second classifier, no new
    ontology, no synonym system: a value is dropped only when it is (a)
    absent from the current message's own text and (b) traceable to the
    recent-turns transcript, so a genuinely restated entity ("stitches"
    mentioned again this turn) is never touched.
    """
    if not recent_turns:
        return entities
    history_lower = " ".join(
        str(turn.get("content") or "")
        for turn in recent_turns
        if isinstance(turn, dict)
    ).lower()
    if not history_lower:
        return entities
    message_lower = (message or "").lower()

    changes: dict[str, Any] = {}
    for field_name in _LEAK_PRONE_FIELDS:
        value = getattr(entities, field_name, None)
        if value in (None, "", [], ()):
            continue
        items = value if isinstance(value, list) else [value]
        kept = [
            item
            for item in items
            if not _leaked_from_history(item, message_lower, history_lower)
        ]
        if len(kept) == len(items):
            continue
        if isinstance(value, list):
            changes[field_name] = kept or None
        else:
            changes[field_name] = kept[0] if kept else None

    if not changes:
        return entities

    # specialty_category_hint is only ever a guess derived FROM
    # entities.symptom (see prompts.py: "When entities.symptom is set,
    # also set entities.specialty_category_hint..."). If the symptom it
    # was guessed from just got dropped as leaked, the guess has nothing
    # left to be about either — leaving it behind would let a stale
    # category hint alone re-trigger the same class of misrouting.
    if "symptom" in changes and not changes["symptom"]:
        changes["specialty_category_hint"] = None

    return replace(entities, **changes)


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
