"""Clinic Capability Resolver.

Maps a patient's expressed need to the clinic's own real, active
specialties/services via one focused LLM call, validated against the
database before any id is trusted. Wired into the live request path as
one end-to-end vertical slice (see `apply_capability_resolution` in
`planner.py`, called from `engine.py`) for exactly two states:
`direct_mode is None` (Intent.UNKNOWN) and `direct_mode == "soft_medical"`
(a medical_question-classified concern) -- every other direct_mode, and
every existing SQL-handler resolution chain (`_CONCERN_MAP`,
`specialty_category_hint`, `match_services_in_message`, `catalog_match`),
remains fully intact for rollback. See the approved "Clinic Capability
Resolver" plan for why:
`_CONCERN_MAP`/`specialty_category_hint`/`match_services_in_message` are
proven-fragile lexical/taxonomy proxies; this call replaces the function
they approximate, once its real output is proven on real clinic data.

Governing principle (do not weaken when integrating later): the resolver
may rank a capability as relevant, but its output must never by itself
authorize a booking, prescribe a service, determine medical necessity, or
override the user's original intent. A "concern" call surfaces
possibilities for a downstream decision-maker to weigh -- it does not
decide anything on its own.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Literal

from django.conf import settings

from apps.chatbot.nlu.base import NLUError
from apps.chatbot.nlu.json_utils import parse_json_response
from apps.chatbot.response_llm import _call_response_llm

logger = logging.getLogger(__name__)

CapabilityType = Literal["service", "specialty"]
ResolverContext = Literal["explicit", "concern"]
ResolverOutcome = Literal["ok", "provider_error"]

# Own timeout budget, not the response-synthesis lane's default -- Phase A
# measured real calls up to ~4.8s against a full-catalog + reasoning
# prompt, and the default CHAT_RESPONSE_TIMEOUT_SECONDS (8.0, split across
# 2 providers = 4.0s each) clipped some of them, silently producing an
# empty candidate list indistinguishable from a genuine no-match. This is
# a distinct concern from the response-synthesis lane's budget and must
# not silently inherit its value if that default is ever tuned for a
# different (shorter, chattier) kind of call. A second diagnostic rerun
# after raising this from an earlier, tighter value still measured one
# double-provider-timeout (both OpenAI and its Gemini fallback exhausting
# their split share of the budget) on the heaviest 5-6 candidate concern
# response, out of 75 real calls -- widened again in response to that
# measurement, not asserted from a guess.
_DEFAULT_TIMEOUT_SECONDS = 15.0


@dataclass(frozen=True)
class CapabilityCandidate:
    target_type: CapabilityType
    id: str
    name: str
    confidence: float  # raw model-reported relevance, 0..1 -- inspection
    #                    only in this phase, no policy is built on it yet.
    reasoning: str


@dataclass(frozen=True)
class CapabilityResolution:
    candidates: list[CapabilityCandidate] = field(default_factory=list)
    # Deliberately no `status` (resolved/ambiguous/no_match/unresolved) --
    # that bucketing rule is designed after real numbers exist to justify
    # it, not asserted before any exist.
    outcome: ResolverOutcome = "ok"
    # "provider_error" means the call itself failed or returned unparsable
    # output -- an empty `candidates` list here is NOT a semantic "no
    # matching capability" result and must never be treated as one by a
    # caller. Phase A's own diagnostic run surfaced this exact confusion:
    # ~5 of 75 calls returned an empty list at 2-3x normal latency because
    # the provider chain failed, indistinguishable in the old return shape
    # from a genuine, confident "nothing here matches."


def resolver_context_for_nlu(nlu_result: Any) -> ResolverContext | None:
    """Which resolver `context` a message plausibly needs, derived only
    from fields the NLU already produces today -- `None` means "no
    capability-resolution relevance at all" (a greeting, hours question,
    insurance check, emergency, etc.), the signal both shadow-mode
    logging (`capability_shadow.py`) and the live vertical slice
    (`engine.py`, via `planner.apply_capability_resolution`) use to decide
    whether to call this module at all. One shared function so the two
    never drift into deciding "is this relevant" differently.

    `Intent.UNKNOWN` is included (using the raw message, since there are
    no entities to prefer) specifically because it has no other resolution
    path today at all -- live-confirmed: "I want braces for my kid"
    classified `unknown` with every entity null, and previously had
    nothing to reach for. Giving it a shot at the resolver is a strict
    improvement with low risk: if the resolver also finds nothing, this is
    no worse than today's existing unknown-intent handling.

    A message with genuinely nothing to resolve -- a bare "Help me find a
    doctor" browse (no symptom/specialty/service at all), or "what
    services do you offer" (service_filter_mode == "none", a deliberate
    browse) -- must return None, not "explicit": live-confirmed bug found
    running the full test suite after wiring this in, an early version of
    this function returned "explicit" for a plain doctor_search with zero
    entities, firing a real LLM call (and a real DB query) for an ordinary
    browse that already works correctly without any help from this
    resolver."""
    from apps.chatbot.nlu.schemas import Intent

    intent = nlu_result.intent
    entities = nlu_result.entities

    if intent == Intent.UNKNOWN:
        return "concern"
    if intent in (Intent.SERVICES_OFFERED, Intent.PRICING):
        if getattr(nlu_result, "service_filter_mode", None) == "none" and not getattr(
            entities, "service", None
        ):
            return None
        return "explicit"
    if intent in (Intent.DOCTOR_SEARCH, Intent.DOCTOR_AVAILABILITY):
        symptom = getattr(entities, "symptom", None)
        specialty = getattr(entities, "specialty", None)
        service = getattr(entities, "service", None)
        if not symptom and not specialty and not service:
            return None
        if symptom and not specialty and not service:
            return "concern"
        return "explicit"
    if intent == Intent.MEDICAL_QUESTION:
        # Deliberately `medical_question_mode` ALONE -- never OR'd with
        # entities.symptom. Live-confirmed bug: an earlier version checked
        # `mode == "personal" or entities.symptom`, and entities.symptom
        # gets set for almost any body-part/condition word regardless of
        # mode (an existing, separate NLU rule: "any body-part/injury/
        # illness word always sets entities.symptom, even when intent
        # ends up off_topic"). That let a purely definitional question
        # ("What causes bleeding gums?") reach the resolver as a
        # "concern" in 2 of 3 repeated live calls, returning a doctor list
        # instead of the correct educational answer -- reproducing,
        # inside this new module, the exact "lexical symptom detection
        # overriding an explicit medical_question_mode classification"
        # bug this session already found and explicitly forbade
        # elsewhere (see planner.py's soft_medical narrowing and its own
        # governing-invariant comment). `medical_question_mode` is the
        # semantic classification of intent; entities.symptom is a
        # lexical fact about the message text -- the former must win
        # outright, not merely be OR'd with the latter.
        mode = getattr(nlu_result, "medical_question_mode", None)
        if mode == "personal":
            return "concern"
        return None
    return None


def expressed_need_for_nlu(
    nlu_result: Any, message: str, *, context: ResolverContext | None = None
) -> str:
    """The text to feed the resolver -- prefers entities.symptom (the
    already-reliable signal for a *concern*), else the raw message.

    `context="explicit"` always uses the raw message instead, never the
    extracted symptom -- live-confirmed gap (capability-family reliability
    phase): "I cut my hand and need stitches" is a specific, explicit ask
    ("stitches"), but the NLU's own separate, existing rule ("any body-
    part/injury/illness word always sets entities.symptom") extracted just
    "hand" 2 of 3 repeated real calls, discarding the one word ("stitches")
    that would have resolved it and instead feeding the resolver a bare
    body-part token it correctly found nothing for -- a real capability
    (Simple Wound Laceration Repair (Sutures)) silently regressed to the
    generic "Pick a service below." An explicit ask, by construction, is
    already the fuller and more informative signal than a single stray
    symptom word can ever be, so there is no case where preferring the
    truncated extraction over the full message helps here -- unlike a
    genuine concern, where the symptom is often the actually-relevant
    signal buried inside a longer, less relevant sentence. `context`
    defaults to None only for the (nonexistent today, kept for backward
    compatibility) case a caller doesn't know its context yet, which
    preserves the original always-prefer-symptom behavior."""
    if context == "explicit":
        return message
    symptom = getattr(nlu_result.entities, "symptom", None)
    if isinstance(symptom, list):
        symptom = symptom[0] if symptom else None
    return symptom or message


def is_nlu_degraded(nlu_result: Any) -> bool:
    """True when this NLUResult did not come from a genuine, healthy LLM
    classification -- a rules-based fallback (the provider chain failed
    entirely) or the classifier's own `_degraded` marker (set on timeout/
    fallback, see nlu/classifier.py). Reuses the exact existing detection
    engine.py already uses for `ui_meta["degraded"]` (engine.py's
    `source in {"rules_fallback"} or (nlu_result.raw or {}).get("_degraded")`)
    rather than inventing a second one.

    Bug found writing this function's own unit tests: `NLUResult` has no
    top-level `.source` attribute at all -- the real signal lives at
    `nlu_result.timings.classifier_source` (see nlu/timings.py). The
    original version of this function checked `getattr(nlu_result,
    "source", None)`, which was always None -- the rules_fallback half of
    this check silently never fired since it was written; only the
    `.raw["_degraded"]` half ever actually worked. Fixed to read the same
    attribute engine.py itself reads.

    Live-confirmed reason this matters: a provider failure that leaves
    NLU classifying `intent=unknown` with every entity null must not be
    treated as "the patient genuinely has an ambiguous concern" -- the
    resolver has no real semantic signal to work with in that case, only
    the absence of one, and (live-confirmed) can respond to it with
    generic, weakly-relevant candidates that read as a real answer. A
    provider failure must produce the existing safe degraded fallback,
    never a semantic capability decision."""
    timings = getattr(nlu_result, "timings", None)
    source = str(getattr(timings, "classifier_source", "") or "")
    if source == "rules_fallback":
        return True
    raw = getattr(nlu_result, "raw", None)
    if isinstance(raw, dict) and raw.get("_degraded"):
        return True
    return False


def live_resolver_context_for_nlu(
    nlu_result: Any, message: str = ""
) -> ResolverContext | None:
    """The live vertical slice's own gate -- narrower than
    `resolver_context_for_nlu` in exactly one deliberate way:
    **`Intent.UNKNOWN` is excluded**, live-confirmed dangerous (a provider
    hiccup or genuine NLU miss producing `unknown` with every entity null
    fed the resolver a "concern" with no real semantic signal, which
    surfaced generic, weakly-relevant candidates dressed up as a real
    answer -- "I have an MRI" at a clinic with no imaging capability
    returning "Found 5 doctors"). `is_nlu_degraded` closes the same class
    of failure for a rules-fallback classification, regardless of intent.

    `Intent.MEDICAL_QUESTION` IS included here (Phase 2 boundary fix) --
    unlike `unknown`, it is a real, specific classification, not a
    degraded fallback, and excluding it was the actual cause of care-
    navigation concerns phrased as a medical question ("my teeth are a
    bit yellow", no "who should I see" tail) dead-ending at the old
    soft_medical canned reply instead of reaching real doctors. The NLU's
    job is "what is the user trying to accomplish" -- a concern is a
    concern whether it happens to classify doctor_search or
    medical_question; the resolver and routing policy don't need to care
    which, and already handle both identically via the shared "concern"
    context (see resolver_context_for_nlu's MEDICAL_QUESTION branch,
    unchanged by this widening).

    Phase 3 boundary fix, live-confirmed gap: `resolver_context_for_nlu`
    returns None for a doctor_search/doctor_availability message with
    zero extracted entities -- correct for a genuine browse ("Help me
    find a doctor"), but also incorrectly excludes an explicit capability
    question the NLU couldn't map to a literal catalog name ("which
    doctor handles root canals?" -- "root canal" is a real, resolvable
    concept, but isn't a listed specialty/service name for the NLU to
    extract verbatim, so entities.specialty/service/symptom all stay
    null, per the NLU's own "don't invent, leave null" rule). Both the
    old resolver chain AND the un-widened new one failed this exact
    message identically ("I couldn't find matching doctors for that").

    A regex pre-filter was tried and deliberately abandoned here: the
    existing `is_doctor_browse_query` (built for a different, narrower
    purpose -- stripping stray entities on a *confirmed* browse) actually
    classifies "which doctor handles root canals?" as a browse too, since
    it starts with the same "which doctor..." opener as a genuine "which
    doctors do you have" -- confirmed by direct testing, not assumed.
    Patching that regex to also exclude this phrasing would mean adding
    another hand-curated keyword list on top of the mechanism this whole
    resolver exists to replace. Simplest and most consistent with the
    architecture: let the resolver itself judge every zero-entity
    doctor_search/doctor_availability message as "explicit" (using the
    raw message `expressed_need_for_nlu` already falls back to), and
    trust its own semantic reasoning to return no candidates for a
    genuine browse. This is safe by construction, not by luck:
    `apply_capability_resolution` makes a "decline" on an already-SQL-
    dispatching plan (which every doctor_search/doctor_availability plan
    already is) a no-op -- the existing unfiltered browse still runs
    untouched. The accepted cost is one extra LLM call for a common,
    genuine browse phrasing -- the same kind of latency tradeoff already
    accepted for every other case this live slice covers, bounded to
    only when the flag is explicitly enabled."""
    from apps.chatbot.nlu.schemas import Intent

    if is_nlu_degraded(nlu_result):
        return None
    intent = nlu_result.intent
    if intent not in (
        Intent.SERVICES_OFFERED,
        Intent.PRICING,
        Intent.DOCTOR_SEARCH,
        Intent.DOCTOR_AVAILABILITY,
        Intent.MEDICAL_QUESTION,
    ):
        return None
    if intent in (Intent.DOCTOR_SEARCH, Intent.DOCTOR_AVAILABILITY):
        entities = nlu_result.entities
        nothing_extracted = not (
            getattr(entities, "symptom", None)
            or getattr(entities, "specialty", None)
            or getattr(entities, "service", None)
        )
        if nothing_extracted:
            return "explicit" if message.strip() else None
    return resolver_context_for_nlu(nlu_result)


_EXPLICIT_INSTRUCTIONS = (
    "The patient named a specific thing they want. From the clinic's real "
    "capabilities listed below, decide which one(s) exactly match what "
    "they asked for. Be decisive when the wording clearly matches one "
    "item -- do not hedge on an obvious match.\n\n"
    "Hard rule: before picking a single winner, check whether the "
    "clinic's list has 2+ items that could equally fit the patient's "
    "wording with NOTHING in their message that favors one over another "
    "(no age given, no patient-type stated, no other distinguishing "
    "detail). If so, you MUST return every one of those equally-plausible "
    "items as separate candidates -- do not silently pick just one of "
    "them, even if one happens to be a more common assumption. Only "
    "return a single candidate when the wording itself, or another "
    "detail in the message, actually distinguishes it from the others. "
    "Concretely: a bare 'I need a checkup'/'I need a physical' with no "
    "age or patient-type mentioned, at a clinic listing both an adult "
    "physical and a pediatric/child exam, MUST return both -- neither an "
    "adult nor a child is implied, so guessing either one alone is "
    "guessing. 'I need a checkup for my son'/'my daughter needs a "
    "physical' (patient-type given) or 'flu test'/'stitches' (only one "
    "real catalog item is even plausible) are NOT ambiguous and must "
    "still return exactly the one real match."
)

_CONCERN_INSTRUCTIONS = (
    "The patient described a concern or symptom, not a request for a "
    "specific procedure. Rank which of the clinic's real capabilities "
    "listed below (specialties and services both) are potentially "
    "relevant to help them reach the right kind of care. Do not assume "
    "any one service is what they need -- you are surfacing possibilities "
    "for a human/system to weigh, not deciding a treatment. This is never "
    "a diagnosis and never a treatment decision.\n\n"
    "Only include a capability if this clinic could directly provide "
    "meaningful care for the concern itself, right now, as ordinary "
    "primary/urgent/wellness care. Do NOT include a specialty or service "
    "merely because it could theoretically play some role somewhere in a "
    "longer treatment or referral chain for a condition or procedure this "
    "clinic does not itself perform -- a family or internal medicine "
    "doctor being loosely 'involved in ongoing management' of a serious "
    "condition is not the same as this clinic offering care for it. If "
    "the concern names (or clearly implies) hospital-level, tertiary, or "
    "specialist-surgical care that a primary/urgent care clinic like this "
    "one structurally does not provide -- for example an organ "
    "transplant, chemotherapy or other oncology treatment, major/"
    "inpatient surgery, dialysis, ICU-level care, or radiation therapy -- "
    "return an empty candidates array for it, even though a general "
    "specialty name might sound loosely related. Example: concern 'heart "
    "transplant' -> empty candidates (transplant surgery is hospital-"
    "level care, not something this clinic provides or meaningfully "
    "refers via a 'may be involved' rationale). Example: concern 'knee "
    "pain' -> Family Medicine/Orthopedics if listed (ordinary first-line "
    "care this clinic can actually give today)."
)

_SYSTEM_PROMPT = """You are a clinic capability matcher. Your only job: given what a patient expressed and the list of capabilities THIS SPECIFIC CLINIC actually offers, decide which listed capabilities are relevant.

Hard rules:
- You may ONLY reference capabilities from the list you are given. Never invent a capability, a name, or an id that isn't in the list.
- If nothing in the list is relevant, return an empty candidates array. Do not force a match.
- A capability is only "relevant" if this clinic could directly give the patient meaningful care for their concern -- not merely a plausible, tangential link somewhere in a larger care pathway for something this clinic doesn't itself provide. When a concern names or implies hospital-level/tertiary/specialist-surgical care this clinic does not perform (e.g. organ transplant, chemotherapy, major surgery, dialysis, ICU care, radiation therapy), return an empty candidates array even if a general specialty sounds loosely related.
- Your job is relevance ranking against what this clinic actually has -- never a medical necessity judgment, never a diagnosis, never a treatment recommendation, never a decision about what the patient "should" get.
- Copy `id` values verbatim from the list. Never alter, guess, or partially reproduce an id.

Output strict JSON only, no prose, no markdown fences, matching exactly:
{"candidates": [{"type": "service"|"specialty", "id": "<exact id from the list>", "confidence": <0.0-1.0>, "reasoning": "<one short sentence>"}]}

Order candidates by relevance, most relevant first. If nothing is relevant: {"candidates": []}"""


def _catalog_rows(clinic: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Real active Specialty/Service rows for this clinic -- id, name,
    description, category. Tenant-scoped by construction: only this
    clinic's active, non-deleted rows are ever built, so the model is
    structurally never shown another clinic's data or an inactive row."""
    from apps.services.models import Service
    from apps.specialties.models import Specialty

    clinic_id = getattr(clinic, "id", None)
    if clinic_id is None:
        return [], []

    specialties = [
        {
            "id": str(s.id),
            "name": s.name,
            "description": (s.description or "").strip(),
            "category": s.category or "",
        }
        for s in Specialty.objects.filter(
            clinic_id=clinic_id, is_deleted=False, is_active=True
        ).order_by("name")
    ]
    services = [
        {
            "id": str(s.id),
            "name": s.name,
            "description": (s.description or "").strip(),
            "category": s.category or "",
        }
        for s in Service.objects.filter(
            clinic_id=clinic_id, is_deleted=False, is_active=True
        ).order_by("name")
    ]
    return specialties, services


def _render_catalog_block(
    specialties: list[dict[str, Any]], services: list[dict[str, Any]]
) -> str:
    lines: list[str] = []
    lines.append("SPECIALTIES:")
    if specialties:
        for s in specialties:
            desc = f" -- {s['description']}" if s["description"] else ""
            lines.append(f"- id={s['id']} name={s['name']}{desc}")
    else:
        lines.append("(none)")
    lines.append("")
    lines.append("SERVICES:")
    if services:
        for s in services:
            desc = f" -- {s['description']}" if s["description"] else ""
            lines.append(f"- id={s['id']} name={s['name']}{desc}")
    else:
        lines.append("(none)")
    return "\n".join(lines)


def _validate_candidates(
    raw_candidates: list[dict[str, Any]],
    specialties: list[dict[str, Any]],
    services: list[dict[str, Any]],
) -> list[CapabilityCandidate]:
    """Real tenant+active+exists+type check -- mirrors
    nlu/resolvers.py::resolve_catalog_match's exact discipline, extended
    from one id to a ranked list. Anything not in the exact list shown to
    the model is dropped, never trusted, regardless of how plausible it
    looks or how high its self-reported confidence is."""
    specialty_ids = {s["id"]: s["name"] for s in specialties}
    service_ids = {s["id"]: s["name"] for s in services}

    validated: list[CapabilityCandidate] = []
    for raw in raw_candidates:
        if not isinstance(raw, dict):
            continue
        target_type = raw.get("type")
        raw_id = str(raw.get("id") or "")
        if target_type == "specialty" and raw_id in specialty_ids:
            name = specialty_ids[raw_id]
        elif target_type == "service" and raw_id in service_ids:
            name = service_ids[raw_id]
        else:
            # Either the type/id combination doesn't match any real row
            # shown to the model, or the model invented/mistyped something
            # -- discard silently rather than guessing at intent.
            continue
        try:
            confidence = float(raw.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))
        reasoning = str(raw.get("reasoning") or "").strip()[:300]
        validated.append(
            CapabilityCandidate(
                target_type=target_type,
                id=raw_id,
                name=name,
                confidence=confidence,
                reasoning=reasoning,
            )
        )
    return validated


def resolve_capability(
    clinic: Any,
    expressed_need: str,
    *,
    context: ResolverContext,
    deadline_seconds: float | None = None,
) -> CapabilityResolution:
    """Rank this clinic's real capabilities against `expressed_need`.

    `context="explicit"` for a message naming a specific thing the patient
    wants; `context="concern"` for a symptom/concern description where no
    specific procedure was requested. Both query the same full catalog --
    only the prompt framing differs (see module docstring's governing
    principle: a "concern" call never implies a decision was made).
    """
    expressed_need = (expressed_need or "").strip()
    specialties, services = _catalog_rows(clinic)
    if not expressed_need or (not specialties and not services):
        # A genuine, well-formed "nothing to resolve" case -- not a
        # provider failure, so outcome stays "ok".
        return CapabilityResolution(candidates=[])

    instructions = (
        _EXPLICIT_INSTRUCTIONS if context == "explicit" else _CONCERN_INSTRUCTIONS
    )
    catalog_block = _render_catalog_block(specialties, services)
    user_block = (
        f"{instructions}\n\n"
        f"Patient's message: \"{expressed_need}\"\n\n"
        f"{catalog_block}"
    )
    budget = float(
        deadline_seconds
        if deadline_seconds is not None
        else getattr(
            settings,
            "CHAT_CAPABILITY_RESOLVER_TIMEOUT_SECONDS",
            _DEFAULT_TIMEOUT_SECONDS,
        )
    )

    try:
        text = _call_response_llm(
            system=_SYSTEM_PROMPT,
            user_block=user_block,
            deadline_seconds=budget,
            # A rich concern response can rank 5-6 candidates, each with
            # its own id (full UUID) and a reasoning sentence -- Phase A's
            # own diagnostic run measured real JSON parse failures from
            # the module default (400) truncating exactly these
            # responses mid-string. Sized generously, not tightly, since
            # a truncated response here was indistinguishable from a
            # genuine provider outage until this was found.
            max_tokens=1000,
            # Own circuit-breaker namespace ("openai:capability" /
            # "gemini:capability") -- this call is measurably heavier/
            # slower than a typical response-LLM prose reply, and must
            # never be able to trip the same circuit NLU classification
            # or plain response synthesis depend on, or vice versa.
            workload="capability",
        )
    except Exception as exc:
        # The provider chain itself failed (timeout, network error, both
        # providers down) -- this is NOT "the clinic has no matching
        # capability" and must never be reported as such to a caller.
        logger.warning("capability_resolver provider_error: %s", exc)
        return CapabilityResolution(candidates=[], outcome="provider_error")

    try:
        data = parse_json_response(text)
        raw_candidates = data.get("candidates")
        if not isinstance(raw_candidates, list):
            raise NLUError("candidates field missing or not a list")
    except NLUError as exc:
        # A response came back but wasn't usable -- same "not a real
        # semantic signal" bucket as a provider failure, not a match result.
        logger.warning("capability_resolver unparsable_response: %s", exc)
        return CapabilityResolution(candidates=[], outcome="provider_error")

    validated = _validate_candidates(raw_candidates, specialties, services)
    return CapabilityResolution(candidates=validated, outcome="ok")
