"""
Soft symptom → specialty suggestions.

Never diagnoses. Language must stay advisory:
"Based on what you described, you may want to start with…"
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from core.care_categories import HINT_TO_CATEGORY


@dataclass(frozen=True)
class ConcernEntry:
    """One named concern in `_CONCERN_MAP`: a set of alias phrases that all
    mean roughly the same thing, plus the specialty-hint words that concern
    implies.

    `specific`: False marks a genuinely generic, could-mean-anything token
    ("pain", "general", "checkup" -- not "fever"/"cough", which are
    specific-enough complaints on their own and don't collide with any
    other entry). A `specific=False` entry's `hints` are never used to
    resolve a category on their own, under any path -- see
    `_hint_names_and_categories`. This is what makes "chest pain" resolve
    to Cardiology alone instead of also hinting Primary Care purely
    because the word "pain" is a substring of the phrase.
    """

    name: str
    phrases: tuple[str, ...]
    hints: tuple[str, ...]
    specific: bool = True


# Concern phrases -> specialty name hints (matched via word-boundary regex
# against the message, not substring containment -- see `_phrase_matches`).
_CONCERN_MAP: list[ConcernEntry] = [
    ConcernEntry(
        name="headache",
        phrases=("headache", "migraine", "head pain", "dizziness", "seizure", "numbness"),
        hints=("neurology", "neurologist", "primary care", "general practice", "internal medicine"),
    ),
    ConcernEntry(
        name="chest_pain",
        phrases=("chest pain", "chest", "heart", "palpitation", "blood pressure", "cardiac", "shortness of breath"),
        hints=("cardiology", "cardiologist", "primary care", "general practice"),
    ),
    ConcernEntry(
        name="stomach",
        phrases=("stomach", "abdomen", "nausea", "diarrhea", "constipation", "acid reflux"),
        hints=("gastroenterology", "primary care", "general practice", "internal medicine"),
    ),
    ConcernEntry(
        name="skin",
        phrases=("skin", "rash", "acne", "eczema", "mole", "itch", "itching", "scalp"),
        hints=("dermatology", "dermatologist", "primary care", "general practice"),
    ),
    ConcernEntry(
        name="mental_health",
        phrases=("anxiety", "depression", "sleep", "insomnia", "mental"),
        hints=("psychiatry", "psychiatrist", "primary care", "psychology"),
    ),
    ConcernEntry(
        name="obgyn",
        phrases=("pregnancy", "period", "obgyn", "gynecolog"),
        hints=("ob-gyn", "obstetrics", "gynecology", "women"),
    ),
    ConcernEntry(
        name="orthopedic",
        phrases=("joint", "back pain", "knee", "shoulder", "fracture", "sports", "leg pain", "leg", "hip"),
        hints=("orthopedic", "orthopedics", "sports medicine", "primary care", "general practice"),
    ),
    ConcernEntry(
        name="ent",
        phrases=("ear", "nose", "throat", "sinus", "hearing"),
        hints=("ent", "otolaryngology", "primary care"),
    ),
    ConcernEntry(
        name="eye",
        phrases=("eye", "vision", "blurry"),
        hints=("ophthalmology", "optometry", "eye"),
    ),
    ConcernEntry(
        name="primary_care_symptom",
        # Specific-enough on their own -- none of these are a substring of
        # any other entry's phrases, so they don't have the "pain" collision
        # problem and can safely resolve Primary Care by themselves.
        phrases=("fever", "cold", "flu", "cough"),
        hints=("primary care", "general practice", "internal medicine", "family"),
    ),
    ConcernEntry(
        name="generic_vague",
        # Genuinely generic, could-mean-anything tokens -- must never
        # resolve a category on their own (round-three review finding).
        # "pain" specifically is also a bare substring of many other
        # entries' phrases ("chest pain", "tooth pain", "back pain", "leg
        # pain", "head pain") -- word-boundary matching stops it being
        # mistaken for those, but it still must not independently imply
        # Primary Care just because nothing more specific was said.
        phrases=("checkup", "check-up", "general", "pain"),
        hints=("primary care", "general practice", "internal medicine", "family"),
        specific=False,
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
    ConcernEntry(
        name="dental",
        phrases=(
            # "toothace" is a real, already-tested typo (missing "h") --
            # listed explicitly because word-boundary matching, unlike the
            # old substring check, can no longer find "tooth" *inside* a
            # single malformed token; same explicit-typo precedent already
            # used in nlu/emergency_patterns.py's self-harm phrase list.
            "tooth", "teeth", "toothache", "toothace", "tooth pain", "cavity", "cavities",
            "root canal", "wisdom tooth", "crown", "filling", "gum", "gums",
            "braces", "tooth extraction", "dental", "jaw", "jaw pain",
        ),
        hints=(
            "dentistry", "dental", "general dentistry", "cosmetic dentistry",
            "restorative dentistry", "family dentistry",
        ),
    ),
]

_PHRASE_PATTERN_CACHE: dict[str, re.Pattern[str]] = {}


def _phrase_matches(phrase: str, text: str) -> bool:
    """Word-boundary match, not substring containment -- the actual fix for
    the "pain" bug: a generic catch-all's bare-word phrase must not fire
    just because it's a substring of a longer, more specific phrase
    ("chest pain" contains "pain"), and a real word must not fire inside an
    unrelated longer word ("painting", "painful")."""
    pattern = _PHRASE_PATTERN_CACHE.get(phrase)
    if pattern is None:
        pattern = re.compile(rf"\b{re.escape(phrase)}\b")
        _PHRASE_PATTERN_CACHE[phrase] = pattern
    return bool(pattern.search(text))


def _matched_entries(text: str) -> list[ConcernEntry]:
    return [e for e in _CONCERN_MAP if any(_phrase_matches(p, text) for p in e.phrases)]


def _hint_names_and_categories(text: str) -> tuple[list[str], set[str]]:
    """Concern-phrase hits in `text`, as (raw hint words, canonical
    categories) -- but only from `specific=True` entries. A `specific=False`
    (generic catch-all) entry's hints are never included here, under any
    path: a message where the *only* thing that matches is a generic token
    like bare "pain" must fall through to the "not understood" clarification
    path (see resolve_symptom_specialty_ids/resolve_symptom_service_ids),
    never silently resolve to Primary Care.

    Shared by `suggest_specialties` (which also fuzzy-matches the raw hint
    words against specialty name/slug) and `resolve_symptom_service_ids`
    (which only needs the canonical categories -- service names are
    procedures, not specialty words, so fuzzy name matching doesn't apply
    there).

    Deterministic, not fuzzy: hint words translate to a canonical category
    via a fixed lookup table (core.care_categories), then a clinic's
    `category` field is compared by plain equality -- no string-similarity
    guessing for this half of the match.
    """
    hinted_names: list[str] = []
    for entry in _matched_entries(text):
        if entry.specific:
            hinted_names.extend(entry.hints)
    hinted_categories = {
        HINT_TO_CATEGORY[h] for h in hinted_names if h in HINT_TO_CATEGORY
    }
    return hinted_names, hinted_categories


def _categories_available_at_clinic(clinic: Any, categories: set[str]) -> set[str]:
    """Which of `categories` the clinic actually has at least one real,
    active Specialty or Service tagged with.

    Round-three review finding: a message can lexically imply two
    categories while the clinic only genuinely offers one of them --
    asking the patient to pick between a real option and one the clinic
    can't act on isn't a real choice. Only consulted when there's a
    potential ambiguity to resolve (2+ lexical categories); the ordinary
    single-category path is untouched by this check, so a specialty whose
    `category` field happens to be blank (relying on name-fuzzy matching
    instead, which this check doesn't see) never regresses -- it simply
    never had a second category to disambiguate against in the first
    place.
    """
    if not categories:
        return set()
    from apps.services.models import Service
    from apps.specialties.models import Specialty

    spec_cats = set(
        Specialty.objects.filter(
            clinic=clinic, is_deleted=False, is_active=True, category__in=categories
        ).values_list("category", flat=True)
    )
    service_cats = set(
        Service.objects.filter(
            clinic=clinic, is_deleted=False, is_active=True, category__in=categories
        ).values_list("category", flat=True)
    )
    return spec_cats | service_cats


def ambiguous_categories_for(clinic: Any, text: str) -> list[str]:
    """The clinic-real ambiguous-category set for `text`, or `[]` when
    there's no genuine 2+-category ambiguity worth a quick-reply
    clarification (message implies fewer than 2 categories, or the clinic
    doesn't actually offer 2+ of what it lexically implies -- see
    `_categories_available_at_clinic`).

    Shared by both the SQL-handler path (`resolve_symptom_specialty_ids`/
    `resolve_symptom_service_ids`, for doctor_search/services_offered-intent
    messages) and the soft_medical direct-reply path (engine.py's
    `_soft_medical_reply`, for medical_question-intent messages) -- live-
    verified via ChatEngine.process() that a bare concern description
    ("chest and stomach pain") is classified medical_question far more
    often than doctor_search, so without this shared entry point the
    SQL-handler path's ambiguity check would almost never actually fire in
    practice.
    """
    _, lexical_categories = _hint_names_and_categories(text)
    if len(lexical_categories) < 2:
        return []
    real_categories = _categories_available_at_clinic(clinic, lexical_categories)
    if len(real_categories) < 2:
        return []
    return sorted(real_categories)


def ambiguous_category_chips(categories: list[str]) -> list[dict[str, Any]]:
    """One quick-reply chip per ambiguous category, no mandatory catch-all
    (round-three review: the chat's own free-text input is already the
    escape hatch for "none of these"). Shared chip-shape builder so the
    soft_medical path and `symptom_no_match_result` never drift apart."""
    return [
        {
            "id": f"concern_category_{i}",
            "label": category,
            "icon": "Stethoscope",
            "behavior": "message",
            "filled": False,
            "message": f"I think it's related to {category}",
        }
        for i, category in enumerate(categories)
    ]


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
    concern map, not the NLU category-hint fallback -- could categorize the
    concern at all. The caller should ask a targeted clarification in that
    case rather than declaring "we don't have that," which presumes a
    category was identified when none was.
    `ambiguous_categories`: non-empty only when the message's concern
    phrases lexically imply 2+ distinct categories AND the clinic actually
    offers 2+ of them (see `_categories_available_at_clinic`) -- a genuine,
    actionable choice, not a phantom one. When set, `matched_ids` is always
    empty and `understood` is always True: the concern *was* understood,
    just not to one specific route yet.
    """

    matched_ids: list[str]
    understood: bool
    ambiguous_categories: list[str] = field(default_factory=list)


def symptom_no_match_result(handler: str, resolution: "SymptomResolution", *, kind: str = "doctor") -> Any:
    """Shared "we couldn't find a match for that symptom" SQLResult,
    honoring the resolution chain's understood/not-understood/ambiguous
    distinction:
      - ambiguous_categories set -> a quick-reply clarification, one chip
        per genuinely clinic-available category (no mandatory catch-all
        chip -- the chat's own free-text input is already the escape hatch
        for "none of these").
      - understood, not ambiguous -> an honest decline (the concern was
        categorized, the clinic just doesn't offer it).
      - not understood -> a targeted, free-text clarification.

    `kind` picks the noun in the decline/clarification copy -- "doctor" for
    search_doctors/doctor_availability (originally the only caller), or
    "service" for services_offered.
    """
    from apps.chatbot.sql_tool.base import SQLResult

    noun = "specialist" if kind == "doctor" else "service"
    directly = "a doctor or specialty" if kind == "doctor" else "a service"
    listing = "our doctors or specialties" if kind == "doctor" else "our services"
    seeing = "who's available" if kind == "doctor" else "what's available"

    if resolution.ambiguous_categories:
        names = " or ".join(resolution.ambiguous_categories)
        summary = f"That could point to a couple of different things — {names}. Which one fits best?"
        chips = ambiguous_category_chips(resolution.ambiguous_categories)
        return SQLResult(
            handler=handler,
            found=False,
            rows=[],
            summary=summary,
            meta={"authoritative_summary": True, "clarify_chips": chips},
        )

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
    lookup or an exact match against real clinic data):
      1. `_CONCERN_MAP` phrase match -> canonical categories. If 2+ distinct
         categories are implied AND the clinic actually offers 2+ of them
         (`_categories_available_at_clinic`), that's a genuine ambiguity --
         return it as `ambiguous_categories` for a quick-reply
         clarification instead of guessing or dumping every matching
         specialty across categories together.
      2. Otherwise, delegate to `suggest_specialties` (see its docstring for
         the category_hint branch): phrase match, checking both specialty
         name/slug (fuzzy, word-boundary safe) and canonical `category`
         (exact match, via `HINT_TO_CATEGORY`).
      3. Only when step 2 found no keyword hint *at all* for this symptom
         (not "found a hint but no clinic specialty matched it" --
         genuinely unrecognized vocabulary): fall back to
         `nlu.entities.specialty_category_hint`, an LLM-supplied guess
         constrained to the same canonical category list (validated at
         parse time, see nlu/schemas.py) -- consulted only because the
         deterministic table has nothing to say, and still matched by
         plain equality against `Specialty.category`, never trusted to
         mean the clinic actually offers it.
      4. If neither step resolves any category at all, `understood=False`.

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

    ambiguous = ambiguous_categories_for(clinic, text)
    if ambiguous:
        return SymptomResolution(matched_ids=[], understood=True, ambiguous_categories=ambiguous)

    suggested, _ = suggest_specialties(
        clinic, message=message, reason=reason, category_hint=category_hint
    )
    if suggested:
        return SymptomResolution(
            matched_ids=[s["id"] for s in suggested], understood=True
        )

    _, lexical_categories = _hint_names_and_categories(text)
    return SymptomResolution(
        matched_ids=[], understood=bool(lexical_categories) or bool(category_hint)
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
      1. `_CONCERN_MAP` phrase match -> canonical categories. If 2+ distinct
         categories are implied AND the clinic actually offers 2+ of them,
         that's `ambiguous_categories` -- same rule and same reasoning as
         resolve_symptom_specialty_ids.
      2. Otherwise, phrase match -> canonical category (`HINT_TO_CATEGORY`)
         -> exact match against `Service.category`.
      3. Only when step 2 found no keyword hint at all: fall back to
         `nlu.entities.specialty_category_hint`, same exact-match rule.
      4. If neither resolves any category at all, `understood=False`.

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

    ambiguous = ambiguous_categories_for(clinic, text)
    if ambiguous:
        return SymptomResolution(matched_ids=[], understood=True, ambiguous_categories=ambiguous)

    _, lexical_categories = _hint_names_and_categories(text)
    if lexical_categories:
        matches = [s for s in clinic_services if s.category and s.category in lexical_categories]
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
