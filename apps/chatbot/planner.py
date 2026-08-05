"""Deterministic planner: semantics + runtime facts → ExecutionPlan.

Hard boundary: this module never calls SQL, vector search, or booking APIs.
It only decides WHAT should happen. ChatEngine (executor) performs the work.

LLM orchestration fields (needs_sql, needs_vector, needs_llm, sql_tool,
document_needed) are deprecated: parser may still accept them, but this
planner ignores them when choosing tasks.
"""
#give me 3 lines about this file? this file is used to decide what the executor should do this turn. 
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from apps.chatbot.nlu.schemas import Intent, NLUResult, Route
from apps.chatbot.routing.lanes import Lane

# ── Capability tables (Python source of truth) ───────────────────────────────

_INTENT_SQL_TASKS: dict[Intent, list[str]] = {
    Intent.CLINIC_HOURS: ["hours"],
    Intent.CLINIC_LOCATION: ["location"],
    Intent.INSURANCE_ACCEPTED: ["insurance"],
    Intent.INSURANCE_VERIFICATION: ["insurance"],
    Intent.DOCTOR_SEARCH: ["doctors"],
    Intent.DOCTOR_AVAILABILITY: ["doctors"],
    Intent.SERVICES_OFFERED: ["services"],
    Intent.PRICING: ["pricing"],
    Intent.CANCEL_APPOINTMENT: ["appointments"],
    Intent.RESCHEDULE_APPOINTMENT: ["appointments"],
}

_TOPIC_SQL_TASKS: dict[str, list[str]] = {
    "hours": ["hours"],
    "location": ["location"],
    "insurance": ["insurance"],
    "doctors": ["doctors"],
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


@dataclass(frozen=True)
class PlannerScores:
    emergency: float = 0.0
    direct: float = 0.0
    booking: float = 0.0
    sql: float = 0.0
    vector: float = 0.0
    clarify: float = 0.0

    def to_dict(self) -> dict[str, float]:
        return {
            "emergency": self.emergency,
            "direct": self.direct,
            "booking": self.booking,
            "sql": self.sql,
            "vector": self.vector,
            "clarify": self.clarify,
        }


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
    scores: PlannerScores = field(default_factory=PlannerScores)
    facts: dict[str, Any] = field(default_factory=dict)
    # Soft medical → specialty discovery without RAG
    soft_medical: bool = False
    doctor_followup: bool = False

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
            "scores": self.scores.to_dict(),
            "facts": self.facts,
            "primary_lane": self.primary_lane.value,
            "lane": self.primary_lane.value,
            "soft_medical": self.soft_medical,
            "doctor_followup": self.doctor_followup,
        }

    def to_planner_decision(self) -> PlannerDecision:
        """Compatibility projection for existing callers/tests."""
        return PlannerDecision(
            lane=self.primary_lane,
            scores=self.scores,
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
    scores: PlannerScores
    sql_tool: str | None = None
    reason: str = ""
    direct_mode: str | None = None
    degraded: bool = False
    facts: dict[str, Any] = field(default_factory=dict)
    execution_plan: ExecutionPlan | None = None

    def to_dict(self) -> dict[str, Any]:
        base = {
            "lane": self.lane.value,
            "scores": self.scores.to_dict(),
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
    booking_commit: bool = False
    soft_medical: bool = False
    knowledge_q: bool = False
    specialty_list: bool = False
    service_list: bool = False
    has_catalog: bool = False
    doc_match: bool = False
    matched_doc_ids: tuple[str, ...] = ()
    service_hit: bool = False
    prefer_vector: bool = False
    prefer_clarify: bool = False
    allow_hybrid: bool = False
    degraded: bool = False
    doctor_ranking_request: bool = False
    instruction_injection: bool = False
    unknown_doctor_requested: bool = False
    doctor_followup: bool = False
    topic: str | None = None
    confidence_band: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_booking_intent": self.is_booking_intent,
            "booking_commit": self.booking_commit,
            "soft_medical": self.soft_medical,
            "knowledge_q": self.knowledge_q,
            "specialty_list": self.specialty_list,
            "service_list": self.service_list,
            "has_catalog": self.has_catalog,
            "doc_match": self.doc_match,
            "matched_doc_ids": list(self.matched_doc_ids),
            "service_hit": self.service_hit,
            "prefer_vector": self.prefer_vector,
            "prefer_clarify": self.prefer_clarify,
            "allow_hybrid": self.allow_hybrid,
            "degraded": self.degraded,
            "doctor_ranking_request": self.doctor_ranking_request,
            "instruction_injection": self.instruction_injection,
            "unknown_doctor_requested": self.unknown_doctor_requested,
            "doctor_followup": self.doctor_followup,
            "topic": self.topic,
            "confidence_band": self.confidence_band,
        }


def build_planner_facts(
    *,
    message: str,
    nlu: NLUResult,
    is_booking_intent: bool = False,
    booking_commit: bool = False,
    soft_medical: bool = False,
    knowledge_q: bool = False,
    specialty_list: bool = False,
    service_list: bool = False,
    has_catalog: bool = False,
    doc_match: bool = False,
    matched_doc_ids: list[str] | None = None,
    service_hit: bool = False,
    prefer_vector: bool = False,
    prefer_clarify: bool = False,
    allow_hybrid: bool = False,
    degraded: bool = False,
    doctor_ranking_request: bool = False,
    instruction_injection: bool = False,
    unknown_doctor_requested: bool = False,
    doctor_followup: bool = False,
    confidence_band: str = "",
) -> PlannerFacts:
    """Assemble runtime facts for the planner. No I/O."""
    topic = _resolve_topic(nlu, message)
    return PlannerFacts(
        message=message or "",
        is_booking_intent=is_booking_intent,
        booking_commit=booking_commit,
        soft_medical=soft_medical,
        knowledge_q=knowledge_q,
        specialty_list=specialty_list,
        service_list=service_list,
        has_catalog=has_catalog,
        doc_match=doc_match,
        matched_doc_ids=tuple(matched_doc_ids or ()),
        service_hit=service_hit,
        prefer_vector=prefer_vector,
        prefer_clarify=prefer_clarify,
        allow_hybrid=allow_hybrid,
        degraded=degraded,
        doctor_ranking_request=doctor_ranking_request,
        instruction_injection=instruction_injection,
        unknown_doctor_requested=unknown_doctor_requested,
        doctor_followup=doctor_followup,
        topic=topic,
        confidence_band=confidence_band,
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
        scores = PlannerScores(emergency=1.0, direct=1.0)
        return ExecutionPlan(
            emergency=True,
            direct=True,
            direct_mode="emergency",
            reason="planner_emergency_override",
            scores=scores,
            facts=fact_dict,
        )

    if facts.doctor_ranking_request:
        return ExecutionPlan(
            direct=True,
            direct_mode="doctor_ranking_refusal",
            reason="planner_doctor_ranking_refusal",
            scores=PlannerScores(direct=0.98),
            facts=fact_dict,
        )

    if facts.instruction_injection:
        return ExecutionPlan(
            direct=True,
            direct_mode="prompt_injection_refusal",
            reason="planner_prompt_injection_refusal",
            scores=PlannerScores(direct=0.99),
            facts=fact_dict,
        )

    if facts.unknown_doctor_requested:
        return ExecutionPlan(
            direct=True,
            direct_mode="unknown_doctor_refusal",
            reason="planner_unknown_doctor_refusal",
            scores=PlannerScores(direct=0.97),
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
            scores=PlannerScores(direct=0.96),
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
                scores=PlannerScores(direct=0.92 + min(0.08, conf * 0.08)),
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
    if topic in _TOPIC_SQL_TASKS:
        add_sql(*_TOPIC_SQL_TASKS[topic])
    if topic in _TOPIC_VECTOR_TASKS:
        add_vector(*_TOPIC_VECTOR_TASKS[topic])

    for intent in intents:
        for task in _INTENT_SQL_TASKS.get(intent, []):
            add_sql(task)
        if intent in _VECTOR_INTENTS:
            add_vector(_vector_task_for_intent(intent, message, topic))

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

    # Insurance entity on a booking/compound turn → insurance SQL + billing docs
    if getattr(nlu.entities, "insurance_provider", None) or any(
        i in {Intent.INSURANCE_ACCEPTED, Intent.INSURANCE_VERIFICATION}
        for i in intents
    ):
        add_sql("insurance")
        if _BILLING_POLICY_RE.search(message) or facts.is_booking_intent:
            if _BILLING_POLICY_RE.search(message):
                add_vector("billing_policy")

    # Soft medical with docs may want vector; without → soft medical direct
    if facts.soft_medical and facts.doc_match and facts.has_catalog:
        add_vector("general_faq")

    booking = bool(facts.is_booking_intent) and not facts.unknown_doctor_requested

    # Check / reschedule my appointment → booking/auth workflow (not clarify)
    if _CHECK_APPOINTMENT_RE.search(message) or nlu.intent in {
        Intent.RESCHEDULE_APPOINTMENT,
        Intent.CANCEL_APPOINTMENT,
    }:
        if not facts.knowledge_q or nlu.intent in {
            Intent.RESCHEDULE_APPOINTMENT,
            Intent.CANCEL_APPOINTMENT,
        }:
            booking = True
            if nlu.intent == Intent.CANCEL_APPOINTMENT and facts.knowledge_q:
                booking = False  # cancel FEE / policy stays vector

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

    # Prefer clarify when confidence policy says so and no grounded tasks
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
            scores=PlannerScores(direct=0.9),
            facts=fact_dict,
        )

    # Soft medical without tasks → direct specialty guidance
    if facts.soft_medical and not sql_tasks and not vector_tasks and not booking:
        return ExecutionPlan(
            direct=True,
            direct_mode="soft_medical",
            soft_medical=True,
            reason="planner_soft_medical_direct",
            scores=PlannerScores(direct=0.85),
            facts=fact_dict,
        )

    use_response_llm = bool(vector_tasks) and facts.has_catalog

    # If vector requested but no catalog, fall back to clarify/sql
    if vector_tasks and not facts.has_catalog:
        vector_tasks = []
        use_response_llm = False
        if not sql_tasks and not booking:
            clarify = True

    scores = PlannerScores(
        emergency=0.0,
        direct=0.2 if (not sql_tasks and not vector_tasks and not booking) else 0.0,
        booking=0.90 + min(0.08, conf * 0.08) if booking else 0.0,
        sql=0.65 + min(0.25, conf * 0.25) if sql_tasks else 0.0,
        vector=0.70 + min(0.25, conf * 0.20) if vector_tasks else 0.0,
        clarify=0.60 + (0.12 if facts.degraded else 0.0) if clarify else 0.0,
    )

    reason_parts = ["planner_execution_plan"]
    if booking:
        reason_parts.append("booking")
    if sql_tasks:
        reason_parts.append("sql:" + ",".join(sql_tasks))
    if vector_tasks:
        reason_parts.append("vector:" + ",".join(vector_tasks))
    if clarify:
        reason_parts.append("clarify")

    return ExecutionPlan(
        clarify=clarify and not (booking or sql_tasks or vector_tasks),
        direct=False,
        booking=booking,
        sql_tasks=sql_tasks,
        vector_tasks=vector_tasks,
        use_response_llm=use_response_llm,
        reason="|".join(reason_parts),
        scores=scores,
        facts=fact_dict,
        soft_medical=facts.soft_medical,
        doctor_followup=facts.doctor_followup,
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
    service_hit: bool = False,
    allow_hybrid: bool = False,
    doctor_followup: bool = False,
    confidence_band: str = "",
) -> PlannerDecision:
    """Compatibility wrapper: build ExecutionPlan, project PlannerDecision.

    ``needs_vector`` is accepted for call-site compat but ignored for task
    selection (deprecated LLM orchestration path).
    """
    del needs_vector  # deprecated — planner derives vector from capability tables
    facts = build_planner_facts(
        message=message,
        nlu=nlu,
        is_booking_intent=is_booking_intent,
        booking_commit=booking_commit,
        soft_medical=soft_medical,
        knowledge_q=knowledge_q,
        specialty_list=specialty_list,
        service_list=service_list,
        has_catalog=has_catalog,
        doc_match=doc_match,
        matched_doc_ids=matched_doc_ids,
        service_hit=service_hit,
        prefer_vector=prefer_vector,
        prefer_clarify=prefer_clarify,
        allow_hybrid=allow_hybrid,
        degraded=degraded,
        doctor_ranking_request=doctor_ranking_request,
        instruction_injection=instruction_injection,
        unknown_doctor_requested=unknown_doctor_requested,
        doctor_followup=doctor_followup,
        confidence_band=confidence_band,
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
