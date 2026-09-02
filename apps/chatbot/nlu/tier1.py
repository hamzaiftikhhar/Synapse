"""Conservative catalog-grounded deterministic pre-LLM routing ("Tier 1").

Contract (Phase 45):

    result = try_catalog_fast_path(clinic, message)

    CONFIDENT_MATCH -> dict payload, same shape try_rule_classify() already
        produces. Flows through the exact same parse_nlu_payload() +
        resolve_entities() pipeline as every other classification source —
        nothing downstream needs to know Tier 1 fired.
    NO_MATCH        -> None. Caller proceeds to the existing NLU pipeline
        unchanged (rules tiers -> LLM chain), exactly as if Tier 1 did not
        exist.

Only three categories, each a closed, narrow, whole-message-anchored
grammatical shape with at most one catalog entity — never an entity-plus-
keyword co-occurrence check:

  - insurance acceptance   ("do you accept <plan>")
  - single-service pricing ("how much is <service>")
  - doctor/specialty listing ("who are your doctors" / "which <specialty>s
    do you have")

No hardcoded doctor, insurer, service, or specialty name anywhere in this
module — every entity value comes from the clinic's own live catalog via
the existing resolvers (nlu/resolvers.py) and catalog builders
(routing/doc_catalog.py). No new fuzzy-matching system: catalog matching
is reused from resolvers.py/routing/signals.py; this module only adds a
strict, generic "did the candidate span name anything beyond the matched
catalog entry" guard on top, because Tier 1 has no LLM to fall back on for
an ambiguous case the way the assisted resolution pipeline does.

False negatives (falls through to the LLM) are always acceptable and are
the default whenever anything doesn't cleanly fit. False positives are
not — every category-specific check below exists to eliminate one.
"""

from __future__ import annotations

import re
from typing import Any

from apps.chatbot.nlu.entity_extract import looks_like_compound
from apps.chatbot.nlu.rules import try_rule_classify
from apps.chatbot.routing.signals import (
    STOPWORDS,
    is_doctor_ranking_request,
    looks_like_instruction_injection,
    mentions_doctor,
)

_FILLER_PREFIX_RE = re.compile(r"^\s*(?:hi|hello|hey)[,!]?\s*", re.I)
_LEADING_ARTICLE_RE = re.compile(r"^(?:a|an|the)\s+", re.I)


def try_catalog_fast_path(clinic: Any, message: str) -> dict[str, Any] | None:
    text = (message or "").strip()
    if not text:
        return None

    # Never claim confidence over a real emergency — an explicit, cheap,
    # unconditional guard, not an assumption that the templates below can
    # never coincide with an emergency phrase.
    if try_rule_classify(text, tier="safety") is not None:
        return None

    # Ambiguity / multi-intent must short-circuit Tier 1 before any
    # category-specific logic runs (Step 4). looks_like_compound() is the
    # same guard already gating the strong rules tier and the fast-tier
    # hours branch (Phase 44) — reused, not reimplemented.
    if looks_like_compound(text):
        return None
    if looks_like_instruction_injection(text):
        return None

    normalized = _FILLER_PREFIX_RE.sub("", text).strip()

    for matcher in (
        _try_insurance_acceptance,
        _try_service_pricing,
        _try_doctor_specialty_listing,
    ):
        hit = matcher(clinic, normalized)
        if hit is not None:
            return hit
    return None


# ── Shared helpers ────────────────────────────────────────────────────────


def _clean_candidate(text: str) -> str:
    t = text.strip().rstrip("?!. ").strip()
    t = _LEADING_ARTICLE_RE.sub("", t).strip()
    return t


def _significant_tokens(text: str) -> list[str]:
    return [
        w
        for w in re.findall(r"[a-z0-9']+", text.lower())
        if w not in STOPWORDS and len(w) >= 2
    ]


def _fully_explained_by(candidate: str, catalog_name: str) -> bool:
    """True only if every significant word in `candidate` also appears in
    `catalog_name` — the candidate names the catalog entry and nothing
    else. Blocks a single strong-token match (e.g. "physical") from
    dragging in an unrelated trailing clause ("...for my child") as if it
    were part of the entity being asked about."""
    cand_tokens = _significant_tokens(candidate)
    if not cand_tokens:
        return False
    name_tokens = set(re.findall(r"[a-z0-9']+", catalog_name.lower()))
    return all(t in name_tokens for t in cand_tokens)


def _payload(
    *,
    intent: str,
    entities: dict[str, Any],
    sql_tool: str,
    reasoning_short: str,
    source: str,
) -> dict[str, Any]:
    empty_entities = {
        "doctor_name": None,
        "specialty": None,
        "service": None,
        "insurance_provider": None,
        "date": None,
        "time": None,
        "patient_name": None,
        "location": None,
        "symptom": None,
        "language": None,
    }
    return {
        "intent": intent,
        "secondary_intents": [],
        "confidence": 0.97,
        "entities": {**empty_entities, **entities},
        "needs_sql": True,
        "needs_vector": False,
        "needs_llm": False,
        "can_respond_directly": False,
        "is_emergency": False,
        "is_off_topic": False,
        "clarification_needed": False,
        "clarification_question": None,
        "reasoning_short": reasoning_short,
        "service_filter_mode": "named",
        "sql_tool": sql_tool,
        "document_needed": False,
        "_classifier_source": source,
    }


# ── Category 1: insurance acceptance ────────────────────────────────────

_INSURANCE_ACCEPT_RE = re.compile(
    r"^(?:do|does)\s+(?:you|(?:the|this)\s+clinic|y'?all)\s+"
    r"(?:accept|take|cover)\s+(?P<plan1>.+?)\s*\??$"
    r"|"
    r"^is\s+(?P<plan2>.+?)\s+accepted\s*\??$",
    re.I,
)


def _try_insurance_acceptance(clinic: Any, text: str) -> dict[str, Any] | None:
    m = _INSURANCE_ACCEPT_RE.fullmatch(text)
    if not m:
        return None
    candidate_raw = next(
        (m.group(g) for g in ("plan1", "plan2") if m.group(g)),
        None,
    )
    if not candidate_raw:
        return None
    candidate = _clean_candidate(candidate_raw)
    if not candidate:
        return None
    # A doctor mention makes this "insurance for a specific doctor", a
    # different (compound) question — not a pure catalog acceptance check.
    if mentions_doctor(text):
        return None

    from apps.insurance.models import InsurancePlan

    clinic_id = getattr(clinic, "id", None)
    if clinic_id is None:
        return None
    plans = list(
        InsurancePlan.objects.filter(clinic_id=clinic_id, is_deleted=False).only(
            "id", "provider_name", "plan_name", "is_accepted"
        )
    )
    matches = [
        p
        for p in plans
        if _fully_explained_by(candidate, f"{p.provider_name} {p.plan_name or ''}")
    ]
    if len(matches) != 1:
        return None
    plan = matches[0]
    label = plan.provider_name + (f" {plan.plan_name}" if plan.plan_name else "")
    return _payload(
        intent="insurance_accepted",
        entities={"insurance_provider": label},
        sql_tool="insurance",
        reasoning_short="Catalog-matched single insurance acceptance question",
        source="tier1_insurance",
    )


# ── Category 2: single-service pricing ──────────────────────────────────

_PRICING_RE = re.compile(
    r"^how\s+much\s+(?:is|does|for)\s+(?P<svc1>.+?)(?:\s+cost)?\s*\??$"
    r"|"
    r"^what(?:'s|\s+is)\s+the\s+(?:cost|price)\s+of\s+(?P<svc2>.+?)\s*\??$"
    r"|"
    r"^(?:price|cost)\s+of\s+(?P<svc3>.+?)\s*\??$"
    r"|"
    r"^what\s+does\s+(?P<svc4>.+?)\s+cost\s*\??$",
    re.I,
)


def _try_service_pricing(clinic: Any, text: str) -> dict[str, Any] | None:
    m = _PRICING_RE.fullmatch(text)
    if not m:
        return None
    candidate_raw = next(
        (m.group(g) for g in ("svc1", "svc2", "svc3", "svc4") if m.group(g)),
        None,
    )
    if not candidate_raw:
        return None
    candidate = _clean_candidate(candidate_raw)
    if not candidate:
        return None

    from apps.chatbot.routing.doc_catalog import build_service_catalog

    catalog = build_service_catalog(clinic)
    if not catalog:
        return None
    # _fully_explained_by alone (every significant candidate token must be
    # in the catalog name) is already a strict containment test — deliberately
    # not routed through match_services_in_message's fuzzy-overlap heuristics,
    # which require a >=7-char single token or 2+ tokens >=5 chars and so can
    # never accept a genuine short single-word service name like "Botox" on
    # its own.
    matches = [s for s in catalog if _fully_explained_by(candidate, s.get("name") or "")]
    if len(matches) != 1:
        return None
    service = matches[0]
    return _payload(
        intent="pricing",
        entities={"service": service.get("name")},
        sql_tool="pricing",
        reasoning_short="Catalog-matched single named-service pricing question",
        source="tier1_pricing",
    )


# ── Category 3: doctor / specialty listing ──────────────────────────────

_DOCTOR_LIST_RE = re.compile(
    r"^(?:who\s+(?:are|is)\s+(?:your|the)\s+doctors?|"
    r"what\s+doctors?\s+do\s+you\s+have|"
    r"which\s+doctors?\s+do\s+you\s+have|"
    r"how\s+many\s+doctors?\s+do\s+you\s+have|"
    r"list\s+(?:of\s+)?(?:your\s+)?doctors?|"
    r"show\s+me\s+(?:your\s+)?doctors?|"
    r"do\s+you\s+have\s+any\s+doctors?)\s*\??$",
    re.I,
)

_SPECIALTY_LIST_BARE_RE = re.compile(
    r"^what\s+specialt(?:y|ies)\s+do\s+you\s+have\s*\??$"
    r"|^which\s+specialt(?:y|ies)\s+do\s+you\s+have\s*\??$"
    r"|^list\s+(?:of\s+)?specialt(?:y|ies)\s*\??$",
    re.I,
)

# "Which <role/specialty word>s do you have" — the filter itself must
# resolve to exactly one clinic specialty via the existing resolver (role
# nouns like "pediatrician" -> "pediatrics" alias handled there already).
_DOCTOR_LIST_FILTERED_RE = re.compile(
    r"^(?:which|what|do\s+you\s+have\s+any)\s+(?P<spec>[a-z][a-z\s-]*?)"
    r"(?:doctors?|specialists?)?\s+do\s+you\s+have\s*\??$",
    re.I,
)


def _try_doctor_specialty_listing(clinic: Any, text: str) -> dict[str, Any] | None:
    if is_doctor_ranking_request(text, clinic=clinic):
        return None

    if _SPECIALTY_LIST_BARE_RE.fullmatch(text):
        return _payload(
            intent="doctor_search",
            entities={},
            sql_tool="specialties",
            reasoning_short="Bare specialty-list browse request",
            source="tier1_doctors",
        )

    if _DOCTOR_LIST_RE.fullmatch(text):
        return _payload(
            intent="doctor_search",
            entities={},
            sql_tool="doctors",
            reasoning_short="Bare doctor-list browse request",
            source="tier1_doctors",
        )

    m = _DOCTOR_LIST_FILTERED_RE.fullmatch(text)
    if m and m.group("spec"):
        candidate = _clean_candidate(m.group("spec"))
        if not candidate:
            return None
        from apps.chatbot.nlu.resolvers import _match_specialty

        clinic_id = getattr(clinic, "id", None)
        if clinic_id is None:
            return None
        specialty_id = _match_specialty(clinic, candidate)
        if not specialty_id:
            return None
        from apps.specialties.models import Specialty

        specialty = Specialty.objects.filter(id=specialty_id).only("name").first()
        if not specialty:
            return None
        return _payload(
            intent="doctor_search",
            entities={"specialty": specialty.name},
            sql_tool="doctors",
            reasoning_short="Catalog-matched single-specialty doctor listing",
            source="tier1_doctors",
        )

    return None
