"""
Soft symptom → specialty suggestions.

Never diagnoses. Language must stay advisory:
"Based on what you described, you may want to start with…"
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from core.care_categories import HINT_TO_CATEGORY

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
    # Live-confirmed gap: this table was written for a general/multi-
    # specialty medical clinic's vocabulary and had zero dental terms, so a
    # dental-only clinic's own patients asking about dental things ("give
    # me teh tooth doctor", "I want to remove hte root canal") got told the
    # clinic doesn't have a specialist for it -- wrong at a clinic whose
    # entire business is dentistry. This does not generalize to every
    # niche a clinic might have (aesthetics, labs, spas); see ROADMAP.md's
    # "Tier 2" entry for the longer-term fix for terms nobody thought to
    # hardcode yet.
    (
        (
            "tooth", "teeth", "toothache", "tooth pain", "cavity", "cavities",
            "root canal", "wisdom tooth", "crown", "filling", "gum", "gums",
            "braces", "tooth extraction", "dental",
        ),
        (
            "dentistry", "dental", "general dentistry", "cosmetic dentistry",
            "restorative dentistry", "family dentistry",
        ),
    ),
]


def _hint_names_and_categories(text: str) -> tuple[list[str], set[str]]:
    """`_SYMPTOM_MAP` keyword hits in `text`, as (raw hint words, canonical
    categories). Shared by `suggest_specialties` (which also fuzzy-matches
    the raw hint words against specialty name/slug) and
    `resolve_symptom_service_ids` (which only needs the canonical
    categories -- service names are procedures, not specialty words, so
    fuzzy name matching doesn't apply there).

    Deterministic, not fuzzy: hint words translate to a canonical category
    via a fixed lookup table (core.care_categories), then a clinic's
    `category` field is compared by plain equality -- no string-similarity
    guessing for this half of the match.
    """
    hinted_names: list[str] = []
    for keywords, specialty_hints in _SYMPTOM_MAP:
        if any(k in text for k in keywords):
            hinted_names.extend(specialty_hints)
    hinted_categories = {
        HINT_TO_CATEGORY[h] for h in hinted_names if h in HINT_TO_CATEGORY
    }
    return hinted_names, hinted_categories


def suggest_specialties(
    clinic: Any,
    *,
    message: str = "",
    reason: str = "",
    category_hint: str = "",
    limit: int = 4,
) -> tuple[list[dict[str, Any]], str]:
    """
    Return (suggested_specialty_dicts, guidance_text).

    Suggestions are intersected with the clinic's active specialties.

    `category_hint`: the NLU's constrained `specialty_category_hint` guess
    (see nlu/schemas.py), consulted ONLY when `_SYMPTOM_MAP` has no keyword
    hint at all for this message -- same resolution order and same "never
    fuzzy, exact match only" rule as `resolve_symptom_specialty_ids`, which
    this function's category-fallback branch was factored out of so both
    the SQL-handler resolution chain and this function's other caller
    (`_soft_medical_reply`, engine.py) share one implementation instead of
    two independently-evolving ones. Without this, a symptom with no
    _SYMPTOM_MAP entry (e.g. "kidney stones" -- not in any keyword group)
    could never resolve to a specialty via this function even when the
    clinic has a matching one, live-confirmed as a real gap: the bare-
    symptom soft_medical reply never benefited from the LLM-hint fallback
    that search_doctors/doctor_availability/services_offered already had.
    """
    from apps.specialties.models import Specialty

    text = f"{message} {reason}".lower().strip()
    clinic_specs = list(
        Specialty.objects.filter(clinic=clinic, is_deleted=False, is_active=True).order_by("name")
    )
    if not clinic_specs:
        return [], "I can help you book an appointment. Let's get started."

    hinted_names, hinted_categories = _hint_names_and_categories(text)

    matched: list[Any] = []
    if hinted_names:
        for spec in clinic_specs:
            name_l = spec.name.lower()
            slug_l = (spec.slug or "").lower()
            # Word-boundary matching, not substring containment -- live-
            # confirmed bug: short hints like "ent" match inside unrelated
            # clinic-authored specialty names ("General Dentistry"), the
            # same class of bug already fixed in _plain_label below and in
            # response_templates.py's off-topic keyword lists.
            name_match = any(
                re.search(rf"\b{re.escape(h)}\b", name_l)
                or re.search(rf"\b{re.escape(h)}\b", slug_l.replace("-", " "))
                for h in hinted_names
            )
            category_match = bool(spec.category) and spec.category in hinted_categories
            if (name_match or category_match) and spec not in matched:
                matched.append(spec)
    elif category_hint:
        # No deterministic keyword hint at all -- fall back to the LLM's
        # canonical-category guess, exact match only, never fuzzy.
        matched = [s for s in clinic_specs if s.category == category_hint]

    # No keyword hint matched (or none of the hinted names exist at this
    # clinic) -- leave `matched` empty rather than substituting whichever
    # specialties happen to sort first. `_soft_medical_reply` (engine.py)
    # already has an honest generic fallback for an empty `suggested`
    # list; silently returning unrelated specialties here used to get
    # framed as "these areas may help" regardless of whether they had
    # anything to do with what was said.
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

    if (hinted_names or category_hint) and rows:
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


@dataclass(frozen=True)
class SymptomResolution:
    """Discriminated result of resolving a patient's symptom/concern to
    clinic entity IDs -- clinic Specialty ids (`resolve_symptom_specialty_ids`)
    or clinic Service ids (`resolve_symptom_service_ids`), same shape either
    way since both are "a symptom resolved to some category-matched rows."

    `matched_ids`: matching clinic Specialty or Service ids -- possibly empty.
    `understood`: False only when *nothing* -- not the deterministic
    symptom/category map, not the NLU category-hint fallback -- could
    categorize the concern at all. The caller should ask a targeted
    clarification in that case rather than declaring "we don't have that,"
    which presumes a category was identified when none was.
    """

    matched_ids: list[str]
    understood: bool


def symptom_no_match_result(handler: str, resolution: "SymptomResolution", *, kind: str = "doctor") -> Any:
    """Shared "we couldn't find a match for that symptom" SQLResult,
    honoring the resolution chain's understood/not-understood distinction:
    a confidently-categorized concern the clinic doesn't offer gets an
    honest decline; a concern nothing (deterministic map or NLU fallback)
    could categorize gets a targeted clarification instead of a
    presumptuous "we don't have that."

    `kind` picks the noun in the decline/clarification copy -- "doctor" for
    search_doctors/doctor_availability (originally the only caller), or
    "service" for services_offered.
    """
    from apps.chatbot.sql_tool.base import SQLResult

    noun = "specialist" if kind == "doctor" else "service"
    directly = "a doctor or specialty" if kind == "doctor" else "a service"
    listing = "our doctors or specialties" if kind == "doctor" else "our services"
    seeing = "who's available" if kind == "doctor" else "what's available"
    if resolution.understood:
        summary = (
            f"We don't have a {noun} for that here. Ask me to "
            f"list {listing} if you'd like to see {seeing}."
        )
    else:
        summary = (
            f"I'm not sure which kind of {noun} that calls for — could "
            f"you say a bit more about the concern, or name {directly} directly?"
        )
    return SQLResult(
        handler=handler,
        found=False,
        rows=[],
        summary=summary,
        # engine.py's soft_medical fallback and formatter.py's search_doctors
        # branch both used to blindly override any "not found" SQL summary
        # with generic copy -- this flag (same contract already used by
        # doctor_availability's temporal refusal) tells the composer this
        # text was deliberately chosen and must not be swapped out.
        meta={"authoritative_summary": True},
    )


def resolve_symptom_specialty_ids(
    clinic: Any, nlu: Any, message: str = ""
) -> SymptomResolution | None:
    """Resolve `entities.symptom` to matching clinic specialty IDs, for SQL
    handlers that filter doctors by specialty but have no idea what to do
    with a bare symptom mention ("doctor related to cardiac").

    Live-confirmed bug this fixes: `search_doctors`/`doctor_availability`
    only ever filter by `resolved_ids.specialty_id` or `entities.specialty`
    -- neither gets populated when the message names a symptom rather than
    an actual specialty (NLU deliberately keeps these separate, see
    nlu/prompts.py). With no specialty filter applied at all, the query
    silently falls through to every active doctor at the clinic, so "is
    there a cardiac doctor here" at a dental clinic returned the full
    dentist roster framed as a good fit for "cardiac."

    Resolution order (never guesses -- each step is either a deterministic
    lookup or an exact match against real clinic data), all delegated to
    `suggest_specialties` (see its docstring for the category_hint branch):
      1. `_SYMPTOM_MAP` keyword match, checking both specialty name/slug
         (fuzzy, word-boundary safe) and canonical `category` (exact
         match, via `HINT_TO_CATEGORY`).
      2. Only when step 1 found no keyword hint *at all* for this symptom
         (not "found a hint but no clinic specialty matched it" --
         genuinely unrecognized vocabulary): fall back to
         `nlu.entities.specialty_category_hint`, an LLM-supplied guess
         constrained to the same canonical category list (validated at
         parse time, see nlu/schemas.py) -- consulted only because the
         deterministic table has nothing to say, and still matched by
         plain equality against `Specialty.category`, never trusted to
         mean the clinic actually offers it.
      3. If neither step resolves any category at all, `understood=False`.

    Returns `None` when no symptom entity is present at all, OR when the
    clinic has zero `Specialty` rows configured (caller falls through to
    its existing behavior unchanged in both cases -- a clinic with no
    specialty data at all is no evidence it lacks the relevant one, so it
    must not be treated the same as a clinic that has specialties and
    genuinely doesn't have a matching one).
    """
    from apps.chatbot.sql_tool.utils import entity_list
    from apps.specialties.models import Specialty

    symptoms = entity_list(getattr(nlu.entities, "symptom", None))
    if not symptoms:
        return None
    clinic_specs = list(
        Specialty.objects.filter(clinic=clinic, is_deleted=False, is_active=True)
    )
    if not clinic_specs:
        return None

    reason = " ".join(symptoms)
    text = f"{message} {reason}".lower().strip()
    category_hint = getattr(nlu.entities, "specialty_category_hint", None) or ""
    suggested, _ = suggest_specialties(
        clinic, message=message, reason=reason, category_hint=category_hint
    )
    if suggested:
        return SymptomResolution(
            matched_ids=[s["id"] for s in suggested], understood=True
        )

    keyword_hint_found = any(any(k in text for k in keywords) for keywords, _ in _SYMPTOM_MAP)
    return SymptomResolution(
        matched_ids=[], understood=keyword_hint_found or bool(category_hint)
    )


def resolve_symptom_service_ids(
    clinic: Any, nlu: Any, message: str = ""
) -> SymptomResolution | None:
    """Resolve `entities.symptom` to matching clinic Service ids, via
    canonical category only -- for `services_offered`'s category-mode
    fallback when a message describes a concern rather than naming a
    service or a recognized category phrase.

    Unlike `resolve_symptom_specialty_ids`, this never fuzzy-matches
    `_SYMPTOM_MAP` hint words against `Service.name`/slug: specialty names
    often literally are specialty words ("Cardiology"), but service names
    are procedure names ("Root Canal", "Annual Physical") with no reliable
    relationship to symptom vocabulary -- only the canonical `category`
    field (exact match) is a safe signal here.

    Resolution order (mirrors resolve_symptom_specialty_ids exactly, minus
    the name/slug fuzzy step):
      1. `_SYMPTOM_MAP` keyword match -> canonical category
         (`HINT_TO_CATEGORY`) -> exact match against `Service.category`.
      2. Only when step 1 found no keyword hint at all: fall back to
         `nlu.entities.specialty_category_hint`, same exact-match rule.
      3. If neither resolves any category at all, `understood=False`.

    Returns `None` when no symptom entity is present, or when the clinic
    has zero `Service` rows at all (no evidence services lack the relevant
    category if there's no service data to check against).
    """
    from apps.chatbot.sql_tool.utils import entity_list
    from apps.services.models import Service

    symptoms = entity_list(getattr(nlu.entities, "symptom", None))
    if not symptoms:
        return None
    clinic_services = list(
        Service.objects.filter(clinic=clinic, is_deleted=False, is_active=True)
    )
    if not clinic_services:
        return None

    reason = " ".join(symptoms)
    text = f"{message} {reason}".lower().strip()
    _, hinted_categories = _hint_names_and_categories(text)
    keyword_hint_found = any(any(k in text for k in keywords) for keywords, _ in _SYMPTOM_MAP)
    if keyword_hint_found:
        matches = [s for s in clinic_services if s.category and s.category in hinted_categories]
        return SymptomResolution(
            matched_ids=[str(s.id) for s in matches], understood=True
        )

    category_hint = getattr(nlu.entities, "specialty_category_hint", None)
    if category_hint:
        matches = [s for s in clinic_services if s.category == category_hint]
        return SymptomResolution(
            matched_ids=[str(s.id) for s in matches], understood=True
        )

    return SymptomResolution(matched_ids=[], understood=False)


def _plain_label(name: str) -> str:
    """Map a specialty name to a plain-English patient-facing label.

    Word-boundary matching, not substring containment — live-confirmed bug:
    "ent" (the ENT/otolaryngology key) is a literal substring of "dentistry",
    so every specialty at a dental clinic ("Cosmetic Dentistry", "General
    Dentistry", "Restorative Dentistry") collapsed to "Ear, Nose & Throat
    Doctor" via naive `k in key` containment. Same class of bug already
    fixed once in response_templates.py's off-topic keyword lists
    ("trip" inside "strip") — same fix here: `\\bkey\\b` regex instead of
    `in`.
    """
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
        if re.search(rf"\b{re.escape(k)}\b", key):
            return v
    return name
