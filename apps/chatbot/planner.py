"""Deterministic planner: semantics + runtime facts → ExecutionPlan.

Hard boundary: this module never calls SQL, vector search, or booking APIs.
It only decides WHAT should happen. ChatEngine (executor) performs the work.

LLM orchestration fields (needs_sql, needs_vector, needs_llm, sql_tool,
document_needed) are deprecated: parser may still accept them, but this
planner ignores them when choosing tasks.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from apps.chatbot.nlu.schemas import Intent, NLUResult, Route
from apps.chatbot.routing.lanes import Lane
from apps.chatbot.routing.signals import is_view_appointments_request

# ── Capability tables (Python source of truth) ───────────────────────────────

_INTENT_SQL_TASKS: dict[Intent, list[str]] = {
    Intent.CLINIC_HOURS: ["hours"],
    Intent.CLINIC_LOCATION: ["location"],
    Intent.INSURANCE_ACCEPTED: ["insurance"],
    Intent.INSURANCE_VERIFICATION: ["insurance"],
    Intent.DOCTOR_SEARCH: ["doctors"],
    Intent.DOCTOR_AVAILABILITY: ["availability"],
    Intent.SERVICES_OFFERED: ["services"],
    Intent.PRICING: ["pricing"],
    Intent.CANCEL_APPOINTMENT: ["appointments"],
    Intent.RESCHEDULE_APPOINTMENT: ["appointments"],
    Intent.VIEW_APPOINTMENTS: ["appointments"],
}

_TOPIC_SQL_TASKS: dict[str, list[str]] = {
    "hours": ["hours"],
    "location": ["location"],
    "insurance": ["insurance"],
    "doctors": ["doctors"],
    "availability": ["availability"],
    "specialties": ["specialties"],
    "services": ["services"],
    "pricing": ["pricing"],
}

_TOPIC_VECTOR_TASKS: dict[str, list[str]] = {
    "membership": ["membership"],
    "billing_policy": ["billing_policy"],
    "cancellation": ["cancellation"],
    "post_op": ["post_op"],
    "general_faq": ["general_faq"],
}

# Domains where an untrusted secondary signal (topic, or a *secondary* entry
# in secondary_intents — never the trusted primary nlu.intent) needs a real
# extracted entity to back it up before it's allowed to attach a live SQL
# task. The classifier prompt asks for "Compound → secondary_intents", but on
# low-signal/gibberish input it sometimes still fills topic/secondary_intents
# with a plausible-sounding guess that has no textual grounding — e.g. random
# text confidently tagged topic="insurance" with no insurance_provider entity
# extracted, which used to attach a real insurance SQL task + card. Domains
# with no natural entity counterpart (hours/location/pricing) are unaffected.
_TOPIC_ENTITY_FIELD: dict[str, str] = {
    "insurance": "insurance_provider",
    "doctors": "doctor_name",
    "services": "service",
}
_INTENT_TOPIC_DOMAIN: dict[Intent, str] = {
    Intent.INSURANCE_ACCEPTED: "insurance",
    Intent.INSURANCE_VERIFICATION: "insurance",
    Intent.DOCTOR_SEARCH: "doctors",
    Intent.SERVICES_OFFERED: "services",
}


def _entity_corroborates(domain: str | None, nlu: NLUResult) -> bool:
    field = _TOPIC_ENTITY_FIELD.get(domain or "")
    if not field:
        return True
    return bool(getattr(nlu.entities, field, None))


# ── Compound-message entity scoping (Phase 50) ──────────────────────────────
#
# Several SQL handlers apply a doctor/service entity as a "bonus" narrowing
# filter beyond their own primary purpose (e.g. insurance_accepted narrowing
# by doctor_id, search_doctors narrowing by service_id). That is correct for
# a genuine single-clause message ("does Dr. Smith accept Aetna") but wrong
# the moment the entity actually belongs to a *different* clause of a
# compound message ("do you accept Aetna and can I book with Dr. Vance" —
# live-confirmed to produce a false "not accepted" answer when the named
# doctor doesn't personally carry the same plan the clinic does).
#
# Each tier list is a priority ordering of which intents most plausibly
# "own" an entity field when 2+ different intents that could claim it are
# BOTH present in the same message. A single present intent is never
# contested (nothing to compare it against), so ordinary single-intent
# messages are entirely unaffected. This is intent-shape based, not
# entity-value based — no doctor/service/insurance name is hardcoded here.
_DOCTOR_ENTITY_TIERS: tuple[frozenset[Intent], ...] = (
    frozenset(
        {Intent.BOOK_APPOINTMENT, Intent.RESCHEDULE_APPOINTMENT, Intent.DOCTOR_AVAILABILITY}
    ),
    frozenset({Intent.DOCTOR_SEARCH}),
)
_SERVICE_ENTITY_TIERS: tuple[frozenset[Intent], ...] = (
    frozenset({Intent.BOOK_APPOINTMENT, Intent.PRICING}),
    frozenset({Intent.SERVICES_OFFERED, Intent.DOCTOR_SEARCH}),
)

# A losing intent's own SQL task(s) that the contested entity must be
# withheld from. Intents absent here (e.g. an intent that never reads this
# entity at all) simply have nothing to block.
_DOCTOR_BLOCKED_TASKS_BY_INTENT: dict[Intent, tuple[str, ...]] = {
    Intent.INSURANCE_ACCEPTED: ("insurance",),
    Intent.INSURANCE_VERIFICATION: ("insurance",),
    Intent.SERVICES_OFFERED: ("services", "pricing"),
    Intent.PRICING: ("services", "pricing"),
    Intent.DOCTOR_SEARCH: ("doctors",),
}
_SERVICE_BLOCKED_TASKS_BY_INTENT: dict[Intent, tuple[str, ...]] = {
    Intent.INSURANCE_ACCEPTED: ("insurance",),
    Intent.INSURANCE_VERIFICATION: ("insurance",),
    Intent.DOCTOR_SEARCH: ("doctors",),
}


def _winning_entity_tier(
    tiers: tuple[frozenset[Intent], ...], present: set[Intent]
) -> frozenset[Intent] | None:
    for tier in tiers:
        if tier & present:
            return tier
    return None


def _compute_blocked_entity_fields(nlu: NLUResult) -> dict[str, frozenset[str]]:
    present = {nlu.intent, *nlu.secondary_intents}
    blocked: dict[str, set[str]] = {}

    def _apply(
        entity_field: str,
        resolved_field: str,
        tiers: tuple[frozenset[Intent], ...],
        blocked_tasks_by_intent: dict[Intent, tuple[str, ...]],
    ) -> None:
        has_value = bool(getattr(nlu.entities, entity_field, None)) or bool(
            getattr(nlu.resolved_ids, resolved_field, None)
        )
        if not has_value:
            return
        winner = _winning_entity_tier(tiers, present)
        if winner is None:
            return
        for intent in present:
            if intent in winner:
                continue
            for task in blocked_tasks_by_intent.get(intent, ()):
                blocked.setdefault(task, set()).update((entity_field, resolved_field))

    _apply("doctor_name", "doctor_id", _DOCTOR_ENTITY_TIERS, _DOCTOR_BLOCKED_TASKS_BY_INTENT)
    _apply("service", "service_id", _SERVICE_ENTITY_TIERS, _SERVICE_BLOCKED_TASKS_BY_INTENT)

    return {k: frozenset(v) for k, v in blocked.items()}


_VECTOR_INTENTS = frozenset(
    {
        Intent.FAQ,
        Intent.MEMBERSHIP,
        Intent.LAB_INFO,
        Intent.PRESCRIPTION_REFILL,
        Intent.PATIENT_REGISTRATION,
    }
)

_DIRECT_INTENTS = frozenset(
    {
        Intent.GREETING,
        Intent.FAREWELL,
        Intent.OFF_TOPIC,
        Intent.EMERGENCY,
    }
)

_POLICY_FEE_RE = re.compile(
    r"\b(cancel(?:lation)?\s*fee|refund|membership|reactivat\w*|terminat\w*|"
    r"bill(?:ing)?\s+(?:medicare|insurance)|bill\s+\w+\s+directly|"
    r"accept(?:s|ed)?\s+medicare|superbill|direct\s+care|"
    r"policy|policies|deposit|dues|prorat\w*)\b",
    re.I,
)

_BILLING_POLICY_RE = re.compile(
    r"\b("
    r"bill(?:ing)?|medicare|superbill|insurance\s+(?:bill|claim|direct)|"
    r"accept(?:s|ed)?\s+medicare|direct\s+bill|out[- ]of[- ]pocket|"
    r"fee[- ]for[- ]service|membership\s+fee"
    r")\b",
    re.I,
)

_AESTHETIC_RE = re.compile(
    r"\b(botox|filler|fillers|laser|microneedl|chemical\s*peel|"
    r"tattoo\s*removal|facial|dysport|juvederm|skin\s*consult|"
    r"cheapest\s+facial)\b",
    re.I,
)

_MEDICAL_ADVICE_RE = re.compile(
    r"("
    r"\b(pregnant|pregnancy|lupus|blood\s*thinners?|warfarin|eliquis|"
    r"autoimmune)\b.{0,80}\b(botox|filler|laser|inject|procedure|safe)\b|"
    r"\b(botox|filler|laser|inject|procedure)\b.{0,80}\b("
    r"pregnant|pregnancy|lupus|blood\s*thinners?|warfarin|eliquis|safe\??)"
    r"\b"
    r")",
    re.I,
)

_CHECK_APPOINTMENT_RE = re.compile(
    r"\b("
    r"check\s+(?:my\s+)?appointment|"
    r"(?:is\s+)?(?:my\s+)?appointment\s+(?:still\s+)?(?:valid|confirmed|booked)|"
    r"do\s+i\s+have\s+an?\s+appointment|"
    r"look\s+up\s+my\s+appointment"
    r")\b",
    re.I,
)

# Soft scheduling language with date/time — route to availability, not FAQ RAG.
_SCHEDULING_CUE_RE = re.compile(
    r"\b("
    r"book|booking|slot|slots|appointment|appointments|"
    r"schedule|scheduling|come\s+in|available|availability|"
    r"opening|openings|see\s+(?:a|the)\s+doctor"
    r")\b",
    re.I,
)


def _nlu_has_schedule_entities(nlu: NLUResult) -> bool:
    ents = nlu.entities
    for attr in ("date", "time"):
        value = getattr(ents, attr, None)
        if value in (None, "", [], ()):
            continue
        return True
    return False

VALID_TOPICS = frozenset(
    {
        "hours",
        "location",
        "insurance",
        "doctors",
        "specialties",
        "services",
        "pricing",
        "membership",
        "billing_policy",
        "cancellation",
        "post_op",
        "general_faq",
    }
)


class UIPriority(str, Enum):
    """How much interactive chrome the renderer may attach this turn."""

    NONE = "none"
    INLINE = "inline"
    OPTIONAL = "optional"
    PRIMARY = "primary"
    BOOKING = "booking"
    EMERGENCY = "emergency"


@dataclass(frozen=True)
class ExecutionPlan:
    """Source of truth for what the executor should do this turn."""

    emergency: bool = False
    clarify: bool = False
    direct: bool = False
    direct_mode: str | None = None
    booking: bool = False
    sql_tasks: list[str] = field(default_factory=list)
    vector_tasks: list[str] = field(default_factory=list)
    use_response_llm: bool = False
    reason: str = ""
    facts: dict[str, Any] = field(default_factory=dict)
    # Soft medical → specialty discovery without RAG
    soft_medical: bool = False
    doctor_followup: bool = False
    # Pre-authorized SQL→vector fallback (see resolve_plan_after_sql below).
    # Decided once, upfront, alongside sql_tasks/vector_tasks — never
    # invented ad hoc after the fact. Empty unless this plan is SQL-only
    # and the intent/catalog shape makes a vector fallback appropriate if
    # that SQL comes back empty.
    fallback_vector_tasks: list[str] = field(default_factory=list)
    # Service IDs the message resolver matched (see compute_message_sensors /
    # routing.signals.match_services_in_message) — the single authority for
    # "which services does this turn refer to." SQL handlers filter by this
    # instead of independently re-matching the message themselves.
    resolved_service_ids: list[str] = field(default_factory=list)
    # Phase 50 — compound-message entity scoping. task name -> entity field
    # names that task must ignore this turn, because the entity plausibly
    # belongs to a *different* intent/task also present in this message
    # (see _compute_blocked_entity_fields below). Empty for every ordinary
    # single-intent message — this only ever narrows an already-planned
    # task's filters, never invents or removes a task.
    blocked_entity_fields: dict[str, frozenset[str]] = field(default_factory=dict)

    @property
    def primary_lane(self) -> Lane:
        if self.emergency or (self.direct and self.direct_mode in {
            "emergency",
            "doctor_ranking_refusal",
            "prompt_injection_refusal",
            "unknown_doctor_refusal",
        }):
            return Lane.DIRECT
        if self.direct and not self.booking and not self.sql_tasks and not self.vector_tasks:
            return Lane.DIRECT
        if self.booking:
            return Lane.BOOKING
        if self.vector_tasks or self.use_response_llm:
            return Lane.VECTOR_RAG
        if self.sql_tasks:
            return Lane.SQL_FAST
        if self.clarify:
            return Lane.CLARIFY
        if self.direct:
            return Lane.DIRECT
        return Lane.CLARIFY

    @property
    def lane(self) -> Lane:
        """Alias for callers that still expect .lane."""
        return self.primary_lane

    @property
    def ui_priority(self) -> UIPriority:
        """Backend-only UI density — cards/chips gated in ui_meta + message-parser."""
        if self.emergency or self.direct_mode == "emergency":
            return UIPriority.EMERGENCY
        if self.booking:
            return UIPriority.BOOKING
        intent = str(self.facts.get("intent") or "")
        if self.clarify and not (self.sql_tasks or self.vector_tasks or self.booking):
            return UIPriority.INLINE
        if intent in {
            Intent.INSURANCE_ACCEPTED.value,
            Intent.INSURANCE_VERIFICATION.value,
            Intent.CLINIC_HOURS.value,
            Intent.CLINIC_LOCATION.value,
            Intent.FAQ.value,
            Intent.PRICING.value,
            Intent.MEMBERSHIP.value,
        }:
            return UIPriority.NONE
        if intent in {
            Intent.DOCTOR_SEARCH.value,
            Intent.DOCTOR_AVAILABILITY.value,
        }:
            return UIPriority.PRIMARY
        if intent == Intent.SERVICES_OFFERED.value and "services" in self.sql_tasks:
            return UIPriority.NONE
        if self.sql_tasks and not self.vector_tasks:
            return UIPriority.OPTIONAL
        return UIPriority.OPTIONAL

    def to_route(self) -> Route:
        if self.emergency or self.direct_mode == "emergency":
            return Route.EMERGENCY
        if self.clarify and not (self.sql_tasks or self.vector_tasks or self.booking):
            return Route.CLARIFY
        if self.direct and not (self.sql_tasks or self.vector_tasks or self.booking):
            return Route.DIRECT_RESPONSE
        has_sql = bool(self.sql_tasks)
        has_vec = bool(self.vector_tasks) or self.use_response_llm
        if has_sql and has_vec:
            return Route.SQL_VECTOR_LLM
        if has_vec:
            return Route.VECTOR_LLM
        if has_sql:
            return Route.SQL_ONLY
        if self.booking:
            return Route.DIRECT_RESPONSE
        return Route.CLARIFY

    def to_dict(self) -> dict[str, Any]:
        return {
            "emergency": self.emergency,
            "clarify": self.clarify,
            "direct": self.direct,
            "direct_mode": self.direct_mode,
            "booking": self.booking,
            "sql_tasks": list(self.sql_tasks),
            "vector_tasks": list(self.vector_tasks),
            "use_response_llm": self.use_response_llm,
            "reason": self.reason,
            "facts": self.facts,
            "primary_lane": self.primary_lane.value,
            "lane": self.primary_lane.value,
            "soft_medical": self.soft_medical,
            "doctor_followup": self.doctor_followup,
            "ui_priority": self.ui_priority.value,
            "fallback_vector_tasks": list(self.fallback_vector_tasks),
            "resolved_service_ids": list(self.resolved_service_ids),
            "blocked_entity_fields": {
                k: sorted(v) for k, v in self.blocked_entity_fields.items()
            },
        }

    def to_planner_decision(self) -> PlannerDecision:
        """Compatibility projection for existing callers/tests."""
        return PlannerDecision(
            lane=self.primary_lane,
            sql_tool=self.sql_tasks[0] if self.sql_tasks else None,
            reason=self.reason,
            direct_mode=self.direct_mode,
            degraded=bool(self.facts.get("degraded")),
            facts=self.facts,
            execution_plan=self,
        )


@dataclass(frozen=True)
class PlannerDecision:
    """Compatibility wrapper over ExecutionPlan (migration)."""

    lane: Lane
    sql_tool: str | None = None
    reason: str = ""
    direct_mode: str | None = None
    degraded: bool = False
    facts: dict[str, Any] = field(default_factory=dict)
    execution_plan: ExecutionPlan | None = None

    def to_dict(self) -> dict[str, Any]:
        base = {
            "lane": self.lane.value,
            "sql_tool": self.sql_tool,
            "reason": self.reason,
            "direct_mode": self.direct_mode,
            "degraded": self.degraded,
            "facts": self.facts,
        }
        if self.execution_plan is not None:
            base["execution_plan"] = self.execution_plan.to_dict()
        return base


@dataclass(frozen=True)
class PlannerFacts:
    """Runtime facts collected outside the planner (sensors only)."""

    message: str = ""
    is_booking_intent: bool = False
    soft_medical: bool = False
    knowledge_q: bool = False
    specialty_list: bool = False
    service_list: bool = False
    has_catalog: bool = False
    doc_match: bool = False
    matched_service_ids: tuple[str, ...] = ()
    prefer_clarify: bool = False
    allow_hybrid: bool = False
    degraded: bool = False
    doctor_ranking_request: bool = False
    instruction_injection: bool = False
    unknown_doctor_requested: bool = False
    doctor_followup: bool = False
    doctor_availability_query: bool = False
    urgent_availability: bool = False
    topic: str | None = None
    # Working context (Phase 39) — DB-independent text classification;
    # the caller (engine.py) resolves the actual timeline-dependent parts
    # (which field to recall, which shown doctor an ordinal refers to)
    # since PlannerFacts/build_execution_plan stay pure, no I/O.
    session_recall_field: str | None = None
    pin_amendment: bool = False
    ordinal_doctor_id: str | None = None
    preview_only: bool = False
    # Phase 41 — same DB-independent/timeline-dependent split as above.
    gender_question: bool = False
    doctor_pronoun_ambiguous: bool = False
    doctor_pronoun_resolved: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_booking_intent": self.is_booking_intent,
            "soft_medical": self.soft_medical,
            "knowledge_q": self.knowledge_q,
            "specialty_list": self.specialty_list,
            "service_list": self.service_list,
            "has_catalog": self.has_catalog,
            "doc_match": self.doc_match,
            "matched_service_ids": list(self.matched_service_ids),
            "prefer_clarify": self.prefer_clarify,
            "allow_hybrid": self.allow_hybrid,
            "degraded": self.degraded,
            "doctor_ranking_request": self.doctor_ranking_request,
            "instruction_injection": self.instruction_injection,
            "unknown_doctor_requested": self.unknown_doctor_requested,
            "doctor_followup": self.doctor_followup,
            "doctor_availability_query": self.doctor_availability_query,
            "urgent_availability": self.urgent_availability,
            "topic": self.topic,
            "session_recall_field": self.session_recall_field,
            "pin_amendment": self.pin_amendment,
            "ordinal_doctor_id": self.ordinal_doctor_id,
            "preview_only": self.preview_only,
            "gender_question": self.gender_question,
            "doctor_pronoun_ambiguous": self.doctor_pronoun_ambiguous,
            "doctor_pronoun_resolved": self.doctor_pronoun_resolved,
        }


@dataclass(frozen=True)
class MessageSensors:
    """Pure, message+NLU+catalog-derived planner sensors — no I/O.

    Single source of truth for signal formulas that used to be
    independently duplicated (and drifted) between engine.py and
    eval/runner.py. Deliberately excludes anything that needs a live
    clinic/session — doctor resolution, unknown_doctor_requested,
    doctor_followup, resolved entity ids. Callers with real DB access
    compute those separately and pass them to build_planner_facts
    alongside this dataclass's fields.
    """

    nlu: NLUResult
    matched_services: list[dict[str, Any]]
    matched_service_ids: list[str]
    service_hit: bool
    knowledge_q: bool
    booking_commit: bool
    is_booking_intent: bool
    soft_medical: bool
    matched_docs: list[str]
    has_catalog: bool
    doc_match: bool
    degraded: bool
    doctor_ranking_request: bool
    instruction_injection: bool
    doctor_availability_query: bool
    urgent_availability: bool
    # Full ConfidencePolicyResult (apps.chatbot.routing.confidence) — kept
    # as one object, not flattened, so callers that need the whole shape
    # (e.g. engine.py's confidence_meta(sensors.policy) for ui_meta) don't
    # have to reconstruct it field-by-field. Typed loosely to avoid a
    # module-level import of routing.confidence from planner.py.
    policy: Any


def compute_message_sensors(
    *,
    message: str,
    nlu: NLUResult,
    document_catalog: list[dict[str, Any]] | None,
    service_catalog: list[dict[str, Any]] | None,
) -> MessageSensors:
    """Derive the shared, I/O-free planner sensors for one message.

    Called by both ChatEngine.process (production) and
    eval/runner.py::evaluate_routing_case (offline battery) so the two
    consume literally the same formulas instead of independently
    reimplementing them. Returns an nlu that may differ from the one
    passed in — apply_confidence_policy can rewrite it (e.g. clarify
    flags) — callers must use the returned .nlu from here on, the same
    way they already must use resolve_plan_after_sql's returned plan.
    """
    from apps.chatbot.routing.confidence import apply_confidence_policy
    from apps.chatbot.routing.doc_catalog import matching_document_ids
    from apps.chatbot.routing.signals import (
        is_booking_commit,
        is_doctor_availability_query,
        is_doctor_ranking_request,
        is_transactional_booking,
        is_typo_book_request,
        is_urgent_availability_request,
        looks_like_instruction_injection,
        looks_like_knowledge_question,
        looks_like_symptom,
        match_services_in_message,
    )

    matched_services = match_services_in_message(message, service_catalog)
    matched_service_ids = [s.get("id") for s in matched_services if s.get("id")]
    service_hit = bool(matched_services)
    knowledge_q = looks_like_knowledge_question(message)

    conf_policy = apply_confidence_policy(
        nlu, has_catalog=bool(document_catalog), service_hit=service_hit, knowledge_q=knowledge_q,
    )
    nlu = conf_policy.nlu

    doctor_availability_query = is_doctor_availability_query(message)
    urgent_availability = is_urgent_availability_request(message)

    booking_commit = is_booking_commit(
        message, doctor_name=getattr(nlu.entities, "doctor_name", None)
    )
    # A pending-offer uptake (apply_pending_uptake, conversation_state.py)
    # already resolved *what* this turn means from real conversation state
    # before this function ever ran — it rewrote nlu.intent to
    # BOOK_APPOINTMENT precisely because "yes i want her" is confirming a
    # just-offered slot. But is_transactional_booking/is_booking_commit
    # below only read the raw message text, which was never expected to
    # look like a booking command in the first place ("book it" happens to
    # contain "book" and passes; "yes i want her"/"yes sure" don't, and
    # silently fell through to clarify despite the correctly-resolved
    # intent — reproduced against a real transcript, see ROADMAP.md).
    # Trust the resolution instead of re-deriving it from text that was
    # never the point.
    pending_uptake_booking = (
        getattr(nlu, "raw", None) or {}
    ).get("_pending_type") == "slot_confirmation"
    is_booking_intent = (
        (
            nlu.intent in {Intent.BOOK_APPOINTMENT, Intent.RESCHEDULE_APPOINTMENT}
            and (is_transactional_booking(message) or booking_commit or pending_uptake_booking)
            and not knowledge_q
        )
        or (
            is_typo_book_request(message)
            and nlu.intent
            not in {Intent.CANCEL_APPOINTMENT, Intent.RESCHEDULE_APPOINTMENT, Intent.EMERGENCY}
            and not knowledge_q
        )
    )
    soft_medical = (
        (
            nlu.intent == Intent.MEDICAL_QUESTION
            or bool(getattr(nlu.entities, "symptom", None))
            or looks_like_symptom(message)
        )
        and not is_booking_intent
        and not knowledge_q
    )

    matched_docs = matching_document_ids(message, document_catalog)
    has_catalog = bool(document_catalog)
    doc_match = bool(matched_docs) or (
        has_catalog
        and (knowledge_q or nlu.intent in {Intent.FAQ, Intent.MEDICAL_QUESTION, Intent.MEMBERSHIP})
    )

    degraded = bool((nlu.raw or {}).get("_degraded")) or (
        getattr(nlu.timings, "classifier_source", "") == "rules_fallback"
        and float(nlu.confidence or 0) < 0.55
    )
    doctor_ranking_request = is_doctor_ranking_request(message)
    instruction_injection = looks_like_instruction_injection(message)

    return MessageSensors(
        nlu=nlu,
        matched_services=matched_services,
        matched_service_ids=matched_service_ids,
        service_hit=service_hit,
        knowledge_q=knowledge_q,
        booking_commit=booking_commit,
        is_booking_intent=is_booking_intent,
        soft_medical=soft_medical,
        matched_docs=matched_docs,
        has_catalog=has_catalog,
        doc_match=doc_match,
        degraded=degraded,
        doctor_ranking_request=doctor_ranking_request,
        instruction_injection=instruction_injection,
        doctor_availability_query=doctor_availability_query,
        urgent_availability=urgent_availability,
        policy=conf_policy,
    )


def build_planner_facts(
    *,
    message: str,
    nlu: NLUResult,
    is_booking_intent: bool = False,
    soft_medical: bool = False,
    knowledge_q: bool = False,
    specialty_list: bool = False,
    service_list: bool = False,
    has_catalog: bool = False,
    doc_match: bool = False,
    matched_service_ids: list[str] | None = None,
    prefer_clarify: bool = False,
    allow_hybrid: bool = False,
    degraded: bool = False,
    doctor_ranking_request: bool = False,
    instruction_injection: bool = False,
    unknown_doctor_requested: bool = False,
    doctor_followup: bool = False,
    doctor_availability_query: bool = False,
    urgent_availability: bool = False,
    session_recall_field: str | None = None,
    pin_amendment: bool = False,
    ordinal_doctor_id: str | None = None,
    preview_only: bool = False,
    gender_question: bool = False,
    doctor_pronoun_ambiguous: bool = False,
    doctor_pronoun_resolved: bool = False,
) -> PlannerFacts:
    """Assemble runtime facts for the planner. No I/O."""
    topic = _resolve_topic(nlu, message)
    return PlannerFacts(
        message=message or "",
        is_booking_intent=is_booking_intent,
        soft_medical=soft_medical,
        knowledge_q=knowledge_q,
        specialty_list=specialty_list,
        service_list=service_list,
        has_catalog=has_catalog,
        doc_match=doc_match,
        matched_service_ids=tuple(matched_service_ids or ()),
        prefer_clarify=prefer_clarify,
        allow_hybrid=allow_hybrid,
        degraded=degraded,
        doctor_ranking_request=doctor_ranking_request,
        instruction_injection=instruction_injection,
        unknown_doctor_requested=unknown_doctor_requested,
        doctor_followup=doctor_followup,
        doctor_availability_query=doctor_availability_query,
        urgent_availability=urgent_availability,
        topic=topic,
        session_recall_field=session_recall_field,
        pin_amendment=pin_amendment,
        ordinal_doctor_id=ordinal_doctor_id,
        preview_only=preview_only,
        gender_question=gender_question,
        doctor_pronoun_ambiguous=doctor_pronoun_ambiguous,
        doctor_pronoun_resolved=doctor_pronoun_resolved,
    )


def build_execution_plan(*, nlu: NLUResult, facts: PlannerFacts) -> ExecutionPlan:
    """Decide WHAT to run. Never calls SQL / vector / booking."""
    message = facts.message or ""
    conf = float(nlu.confidence or 0.0)
    fact_dict = {
        **facts.to_dict(),
        "intent": nlu.intent.value,
        "confidence": conf,
        "secondary_intents": [i.value for i in nlu.secondary_intents],
        "service_filter_mode": nlu.service_filter_mode,
        # Deprecated LLM fields recorded for debug only — not used for tasks
        "deprecated_llm_needs_sql": bool(nlu.needs_sql),
        "deprecated_llm_needs_vector": bool(nlu.needs_vector),
        "deprecated_llm_sql_tool": nlu.sql_tool,
        "deprecated_llm_document_needed": bool(nlu.document_needed),
    }

    # ── Safety overrides ────────────────────────────────────────────────────
    if nlu.is_emergency or nlu.intent == Intent.EMERGENCY:
        return ExecutionPlan(
            emergency=True,
            direct=True,
            direct_mode="emergency",
            reason="planner_emergency_override",
            facts=fact_dict,
        )

    # Working context (Phase 39) — a question about what THIS session
    # already discussed must never reach RAG/the Large LLM: with no real
    # history to ground it beyond a thin recent-messages window, it
    # reliably invents an answer instead of admitting it doesn't know
    # (reproduced directly — see ROADMAP.md). Composed from
    # ConversationTimeline facts in engine.py, not a second model pass.
    if facts.session_recall_field:
        return ExecutionPlan(
            direct=True,
            direct_mode="session_recall",
            reason="planner_session_recall",
            facts=fact_dict,
        )

    # Phase 41 — gender is never stored on Doctor; must never fall through
    # to a normal doctor_search that silently returns an unfiltered list as
    # if it answered the question (reproduced live). Checked ahead of
    # doctor_ranking_request/etc. since a gender-question message can also
    # otherwise read as a plain doctor_search.
    if facts.gender_question:
        return ExecutionPlan(
            direct=True,
            direct_mode="gender_unsupported",
            reason="planner_gender_unsupported",
            facts=fact_dict,
        )

    # Phase 41 — a doctor-pronoun reference ("can she see children?") that
    # resolved to 2+ possible antecedents (engine.py, from
    # timeline.shown_doctors) must ask which doctor rather than guess or
    # dump the full list.
    if facts.doctor_pronoun_ambiguous:
        return ExecutionPlan(
            direct=True,
            direct_mode="doctor_pronoun_ambiguous",
            reason="planner_doctor_pronoun_ambiguous",
            facts=fact_dict,
        )

    if facts.doctor_ranking_request:
        return ExecutionPlan(
            direct=True,
            direct_mode="doctor_ranking_refusal",
            reason="planner_doctor_ranking_refusal",
            facts=fact_dict,
        )

    if facts.instruction_injection:
        return ExecutionPlan(
            direct=True,
            direct_mode="prompt_injection_refusal",
            reason="planner_prompt_injection_refusal",
            facts=fact_dict,
        )

    if facts.unknown_doctor_requested and not facts.doctor_availability_query:
        return ExecutionPlan(
            direct=True,
            direct_mode="unknown_doctor_refusal",
            reason="planner_unknown_doctor_refusal",
            facts=fact_dict,
        )

    if _MEDICAL_ADVICE_RE.search(message) or (
        nlu.intent == Intent.MEDICAL_QUESTION
        and _AESTHETIC_RE.search(message)
        and re.search(
            r"\b(pregnant|pregnancy|lupus|blood\s*thinner|safe)\b", message, re.I
        )
    ):
        return ExecutionPlan(
            direct=True,
            direct_mode="medical_advice_refusal",
            reason="planner_medical_advice_refusal",
            facts=fact_dict,
        )

    # ── Direct phatic / off-topic ───────────────────────────────────────────
    if nlu.intent in _DIRECT_INTENTS or (
        nlu.can_respond_directly
        and nlu.intent in {Intent.GREETING, Intent.FAREWELL, Intent.OFF_TOPIC, Intent.HANDOFF_HUMAN}
    ):
        if nlu.intent != Intent.UNKNOWN:
            return ExecutionPlan(
                direct=True,
                direct_mode="template",
                reason=f"planner_direct:{nlu.intent.value}",
                facts=fact_dict,
            )

    # ── Collect tasks from capability tables (ignore LLM needs_*) ───────────
    sql_tasks: list[str] = []
    vector_tasks: list[str] = []

    def add_sql(*tasks: str) -> None:
        for t in tasks:
            if t and t not in sql_tasks:
                sql_tasks.append(t)

    def add_vector(*tasks: str) -> None:
        for t in tasks:
            if t and t not in vector_tasks:
                vector_tasks.append(t)

    intents = [nlu.intent, *nlu.secondary_intents]

    # Topic from LLM (semantic) or message heuristics
    topic = facts.topic
    if topic in _TOPIC_SQL_TASKS and _entity_corroborates(topic, nlu):
        add_sql(*_TOPIC_SQL_TASKS[topic])
    if topic in _TOPIC_VECTOR_TASKS:
        add_vector(*_TOPIC_VECTOR_TASKS[topic])

    for position, intent in enumerate(intents):
        # Primary intent (position 0) is always trusted; secondary_intents
        # need entity corroboration for domains that have one (see
        # _entity_corroborates docstring above).
        if position > 0 and not _entity_corroborates(
            _INTENT_TOPIC_DOMAIN.get(intent), nlu
        ):
            continue
        # VIEW_APPOINTMENTS is the exception: nano labels "koob me" as a
        # lookup at 0.95 or 0.2 at random. Require the utterance itself
        # to ask for existing appointments before attaching SQL.
        if intent == Intent.VIEW_APPOINTMENTS and not is_view_appointments_request(
            message
        ):
            continue
        for task in _INTENT_SQL_TASKS.get(intent, []):
            add_sql(task)
        if intent in _VECTOR_INTENTS:
            add_vector(_vector_task_for_intent(intent, message, topic))

    if facts.doctor_availability_query:
        add_sql("availability")
        sql_tasks = [t for t in sql_tasks if t != "hours"]
        if "doctors" in sql_tasks and "availability" in sql_tasks:
            sql_tasks = [t for t in sql_tasks if t != "doctors"]

    if facts.urgent_availability and "availability" not in sql_tasks:
        add_sql("availability")

    if facts.specialty_list:
        add_sql("specialties")
        # Prefer specialties over services dump for specialty browse
        if "services" in sql_tasks and nlu.intent in {
            Intent.SERVICES_OFFERED,
            Intent.FAQ,
            Intent.UNKNOWN,
        }:
            sql_tasks = [t for t in sql_tasks if t != "services"]
            if "specialties" not in sql_tasks:
                sql_tasks.insert(0, "specialties")

    if facts.service_list and not facts.specialty_list:
        add_sql("services")

    # Policy / membership / cancel-fee / billing → vector (not catalog pricing)
    if facts.knowledge_q or _POLICY_FEE_RE.search(message):
        if _BILLING_POLICY_RE.search(message):
            add_vector("billing_policy")
        elif re.search(r"\b(membership|direct\s+primary|dpc)\b", message, re.I):
            add_vector("membership")
        elif re.search(r"\b(cancel(?:lation)?|refund)\b", message, re.I):
            add_vector("cancellation")
        elif facts.knowledge_q:
            add_vector("general_faq")
        # Strip misleading pricing SQL when this is a policy fee question
        if _POLICY_FEE_RE.search(message) and nlu.intent in {
            Intent.PRICING,
            Intent.SERVICES_OFFERED,
            Intent.FAQ,
            Intent.UNKNOWN,
        }:
            sql_tasks = [t for t in sql_tasks if t not in {"pricing", "services"}]

    # Insurance entity on a booking/compound turn → insurance SQL + billing docs.
    # "insurance" in sql_tasks already covers the primary/corroborated-secondary
    # intent case via the loop above — this adds the entity-only trigger (e.g. a
    # booking turn that just names a plan by name without an insurance intent).
    if getattr(nlu.entities, "insurance_provider", None) or "insurance" in sql_tasks:
        add_sql("insurance")
        if _BILLING_POLICY_RE.search(message) or facts.is_booking_intent:
            if _BILLING_POLICY_RE.search(message):
                add_vector("billing_policy")

    # Soft medical with docs may want vector; without → soft medical direct
    if facts.soft_medical and facts.doc_match and facts.has_catalog:
        add_vector("general_faq")

    # Date/time + scheduling language → availability (even if NLU said faq).
    # Do not invent more regex intents — only override the dump-to-RAG path.
    if (
        _nlu_has_schedule_entities(nlu)
        and _SCHEDULING_CUE_RE.search(message)
        and not facts.knowledge_q
    ):
        add_sql("availability")
        sql_tasks = [t for t in sql_tasks if t != "hours"]
        if nlu.intent in {
            Intent.FAQ,
            Intent.UNKNOWN,
            Intent.FOLLOW_UP,
            Intent.MEDICAL_QUESTION,
        }:
            vector_tasks = [
                t
                for t in vector_tasks
                if t
                not in {
                    "general_faq",
                    "cancellation",
                    "membership",
                    "billing_policy",
                }
            ]

    booking = bool(facts.is_booking_intent) and not facts.unknown_doctor_requested

    # Working context (Phase 39) — "don't book anything until you show me
    # X" must not launch the booking wizard this turn even though the
    # message is otherwise booking-shaped; availability/SQL tasks below
    # are unaffected, so the patient still sees times, just not a booking
    # commit action attached to them.
    if facts.preview_only:
        booking = False

    # Check / reschedule my appointment → booking/auth workflow (not clarify)
    if _CHECK_APPOINTMENT_RE.search(message) or nlu.intent in {
        Intent.RESCHEDULE_APPOINTMENT,
        Intent.CANCEL_APPOINTMENT,
    }:
        # A bare "do I have an appointment" / "check my appointment" match
        # may not carry an appointment-management intent from the LLM (it
        # can land on unknown/faq/etc.) — always run the actual lookup so
        # the regex match has real data behind it instead of forcing
        # booking=True with nothing to show for it.
        add_sql("appointments")
        if not facts.knowledge_q or nlu.intent in {
            Intent.RESCHEDULE_APPOINTMENT,
            Intent.CANCEL_APPOINTMENT,
        }:
            booking = True
            if nlu.intent == Intent.CANCEL_APPOINTMENT and facts.knowledge_q:
                booking = False  # cancel FEE / policy stays vector

    # Viewing appointments is a pure lookup, not a booking-workflow entry —
    # never attach the "how would you like to book?" booking framing to it.
    if nlu.intent == Intent.VIEW_APPOINTMENTS:
        booking = False

    # Aesthetic / cosmetic SKUs questions → services SQL (+ booking if transactional)
    if _AESTHETIC_RE.search(message):
        add_sql("services")
        if facts.is_booking_intent or booking:
            booking = True
        # Prefer services over unrelated specialty discovery
        if "doctors" in sql_tasks and not getattr(nlu.entities, "doctor_name", None):
            sql_tasks = [t for t in sql_tasks if t != "doctors"]

    # Degraded UNKNOWN: do not invent SQL
    if facts.degraded and nlu.intent == Intent.UNKNOWN:
        sql_tasks = []
        if not (facts.knowledge_q and facts.has_catalog):
            vector_tasks = []

    # Prefer clarify when confidence policy says so and no grounded tasks.
    # Drop appointment SQL that survived from a hallucinated VIEW intent
    # when the message never asked to look appointments up.
    if "appointments" in sql_tasks and nlu.intent == Intent.VIEW_APPOINTMENTS:
        if not is_view_appointments_request(message) and not _CHECK_APPOINTMENT_RE.search(
            message
        ):
            sql_tasks = [t for t in sql_tasks if t != "appointments"]
    clarify = False
    if nlu.clarification_needed or nlu.intent == Intent.UNKNOWN:
        if not sql_tasks and not vector_tasks and not booking:
            clarify = True
    if facts.prefer_clarify and not sql_tasks and not vector_tasks and not booking:
        clarify = True
    if facts.degraded and not (sql_tasks or vector_tasks or booking):
        clarify = True

    # Doctor follow-up: template direct unless booking
    if facts.doctor_followup and not booking:
        return ExecutionPlan(
            direct=True,
            direct_mode="doctor_followup",
            doctor_followup=True,
            reason="planner_doctor_followup",
            facts=fact_dict,
        )

    # Soft medical without tasks → direct specialty guidance
    if facts.soft_medical and not sql_tasks and not vector_tasks and not booking:
        return ExecutionPlan(
            direct=True,
            direct_mode="soft_medical",
            soft_medical=True,
            reason="planner_soft_medical_direct",
            facts=fact_dict,
        )

    use_response_llm = bool(vector_tasks) and facts.has_catalog

    # If vector requested but no catalog, fall back to clarify/sql
    if vector_tasks and not facts.has_catalog:
        vector_tasks = []
        use_response_llm = False
        if not sql_tasks and not booking:
            clarify = True

    # Pre-authorize a SQL→vector fallback for SQL-only plans, so the engine
    # never has to invent one after the fact (see resolve_plan_after_sql).
    # Equivalent to the old _should_hybrid_rag's reachable conditions for
    # the "SQL came back empty" case — the separate "SQL found rows"
    # early-return in that function always returned False regardless of
    # allow_hybrid, so that branch contributed nothing and isn't
    # reproduced here; likewise its final 5-intent check was a strict
    # subset of HYBRID_SQL_INTENTS and never reachable on its own.
    fallback_vector_tasks: list[str] = []
    if sql_tasks and not vector_tasks and not booking and facts.has_catalog:
        from apps.chatbot.routing.lanes import HYBRID_SQL_INTENTS

        # Empty availability is a resolved answer ("nothing open that day"),
        # not a thin SQL miss that clinic documents might fill. RAG must not
        # invent slots. Insurance/services/FAQ empty still may hybrid.
        availability_is_authoritative = "availability" in sql_tasks
        if not availability_is_authoritative and (
            nlu.intent in HYBRID_SQL_INTENTS or facts.knowledge_q or facts.allow_hybrid
        ):
            fallback_vector_tasks = [_vector_task_for_intent(nlu.intent, message, topic)]

    reason_parts = ["planner_execution_plan"]
    if booking:
        reason_parts.append("booking")
    if sql_tasks:
        reason_parts.append("sql:" + ",".join(sql_tasks))
    if vector_tasks:
        reason_parts.append("vector:" + ",".join(vector_tasks))
    if clarify:
        reason_parts.append("clarify")
    if fallback_vector_tasks:
        reason_parts.append("fallback_vector:" + ",".join(fallback_vector_tasks))

    blocked_entity_fields = _compute_blocked_entity_fields(nlu) if sql_tasks else {}
    if blocked_entity_fields:
        reason_parts.append(
            "blocked:" + ",".join(f"{k}={'|'.join(sorted(v))}" for k, v in blocked_entity_fields.items())
        )

    return ExecutionPlan(
        clarify=clarify and not (booking or sql_tasks or vector_tasks),
        direct=False,
        booking=booking,
        sql_tasks=sql_tasks,
        vector_tasks=vector_tasks,
        use_response_llm=use_response_llm,
        reason="|".join(reason_parts),
        facts=fact_dict,
        soft_medical=facts.soft_medical,
        doctor_followup=facts.doctor_followup,
        fallback_vector_tasks=fallback_vector_tasks,
        resolved_service_ids=list(facts.matched_service_ids),
        blocked_entity_fields=blocked_entity_fields,
    )


def choose_plan(
    *,
    nlu: NLUResult,
    is_booking_intent: bool,
    soft_medical: bool,
    needs_vector: bool,
    doc_match: bool,
    has_catalog: bool,
    prefer_vector: bool,
    prefer_clarify: bool,
    degraded: bool,
    doctor_ranking_request: bool,
    instruction_injection: bool,
    unknown_doctor_requested: bool,
    message: str = "",
    booking_commit: bool = False,
    knowledge_q: bool = False,
    specialty_list: bool = False,
    service_list: bool = False,
    matched_doc_ids: list[str] | None = None,
    matched_service_ids: list[str] | None = None,
    service_hit: bool = False,
    allow_hybrid: bool = False,
    doctor_followup: bool = False,
    doctor_availability_query: bool = False,
    urgent_availability: bool = False,
    confidence_band: str = "",
) -> PlannerDecision:
    """Compatibility wrapper: build ExecutionPlan, project PlannerDecision.

    ``needs_vector``, ``booking_commit``, ``matched_doc_ids``, ``service_hit``,
    ``prefer_vector``, and ``confidence_band`` are accepted for call-site
    compat but no longer forwarded — build_execution_plan never read them
    off PlannerFacts (Phase 7 cleanup; see PlannerFacts' reduced field
    list above). Kept here only so existing callers don't need updating.
    """
    del needs_vector  # deprecated — planner derives vector from capability tables
    del booking_commit, matched_doc_ids, service_hit, prefer_vector, confidence_band
    facts = build_planner_facts(
        message=message,
        nlu=nlu,
        is_booking_intent=is_booking_intent,
        soft_medical=soft_medical,
        knowledge_q=knowledge_q,
        specialty_list=specialty_list,
        service_list=service_list,
        has_catalog=has_catalog,
        doc_match=doc_match,
        matched_service_ids=matched_service_ids,
        prefer_clarify=prefer_clarify,
        allow_hybrid=allow_hybrid,
        degraded=degraded,
        doctor_ranking_request=doctor_ranking_request,
        instruction_injection=instruction_injection,
        unknown_doctor_requested=unknown_doctor_requested,
        doctor_followup=doctor_followup,
        doctor_availability_query=doctor_availability_query,
        urgent_availability=urgent_availability,
    )
    plan = build_execution_plan(nlu=nlu, facts=facts)
    return plan.to_planner_decision()


def apply_plan_to_nlu(nlu: NLUResult, plan: ExecutionPlan) -> NLUResult:
    """Overwrite deprecated orchestration flags from ExecutionPlan (downstream compat)."""
    from dataclasses import replace

    sql_tool = plan.sql_tasks[0] if plan.sql_tasks else None
    return replace(
        nlu,
        needs_sql=bool(plan.sql_tasks),
        needs_vector=bool(plan.vector_tasks),
        needs_llm=bool(plan.use_response_llm),
        document_needed=bool(plan.vector_tasks),
        sql_tool=sql_tool,
        can_respond_directly=bool(plan.direct and not plan.booking),
        clarification_needed=bool(plan.clarify) or nlu.clarification_needed,
    )


def resolve_plan_after_sql(plan: ExecutionPlan, *, sql_found: bool) -> ExecutionPlan:
    """The only legitimate way an ExecutionPlan changes after SQL executes.

    Called exactly once, by the engine, immediately after running
    plan.sql_tasks — never for any other reason, and never based on
    anything other than whether those specific SQL tasks found rows.
    Activates the plan's own pre-authorized fallback_vector_tasks (decided
    upfront, at planning time, alongside sql_tasks/vector_tasks) when they
    came back empty. Still performs no I/O itself — sql_found is a fact
    the caller already observed by actually running the SQL.

    Returns a NEW ExecutionPlan via dataclasses.replace; the plan passed
    in is never mutated (it stays frozen). If there is nothing to
    activate, returns the exact same plan object, unchanged, so callers
    can safely reassign their local variable to the result either way.
    """
    if sql_found or not plan.fallback_vector_tasks:
        return plan
    from dataclasses import replace

    new_vector_tasks = list(plan.vector_tasks)
    for task in plan.fallback_vector_tasks:
        if task not in new_vector_tasks:
            new_vector_tasks.append(task)
    return replace(
        plan,
        vector_tasks=new_vector_tasks,
        use_response_llm=True,
        reason=plan.reason + "|hybrid_fallback_activated",
    )


def _resolve_topic(nlu: NLUResult, message: str) -> str | None:
    raw = nlu.raw if isinstance(nlu.raw, dict) else {}
    topic = str(raw.get("topic") or "").strip().lower()
    if topic in VALID_TOPICS:
        return topic
    # Light message fallbacks (sensors — not LLM orchestration)
    if _BILLING_POLICY_RE.search(message):
        return "billing_policy"
    if re.search(r"\b(membership|direct\s+primary|dpc)\b", message, re.I):
        return "membership"
    if re.search(r"\b(cancel(?:lation)?\s*fee|refund)\b", message, re.I):
        return "cancellation"
    if re.search(r"\b(post[- ]?op|aftercare|after\s+(?:surgery|procedure))\b", message, re.I):
        return "post_op"
    return None


def _vector_task_for_intent(intent: Intent, message: str, topic: str | None) -> str:
    if topic in _TOPIC_VECTOR_TASKS:
        return topic
    if intent == Intent.MEMBERSHIP:
        return "membership"
    if _BILLING_POLICY_RE.search(message):
        return "billing_policy"
    if re.search(r"\b(cancel(?:lation)?|refund)\b", message, re.I):
        return "cancellation"
    return "general_faq"
