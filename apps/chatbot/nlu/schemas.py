"""Intent, entity, and routing schemas for clinic NLU."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from apps.chatbot.nlu.timings import NLUTimings


class Intent(str, Enum):
    GREETING = "greeting"
    FAREWELL = "farewell"
    BOOK_APPOINTMENT = "book_appointment"
    CANCEL_APPOINTMENT = "cancel_appointment"
    RESCHEDULE_APPOINTMENT = "reschedule_appointment"
    DOCTOR_AVAILABILITY = "doctor_availability"
    DOCTOR_SEARCH = "doctor_search"
    INSURANCE_VERIFICATION = "insurance_verification"
    INSURANCE_ACCEPTED = "insurance_accepted"
    CLINIC_HOURS = "clinic_hours"
    CLINIC_LOCATION = "clinic_location"
    SERVICES_OFFERED = "services_offered"
    PRICING = "pricing"
    MEMBERSHIP = "membership"
    PRESCRIPTION_REFILL = "prescription_refill"
    LAB_INFO = "lab_info"
    PATIENT_REGISTRATION = "patient_registration"
    FAQ = "faq"
    MEDICAL_QUESTION = "medical_question"
    EMERGENCY = "emergency"
    HANDOFF_HUMAN = "handoff_human"
    FOLLOW_UP = "follow_up"
    MULTI_INTENT = "multi_intent"
    OFF_TOPIC = "off_topic"
    UNKNOWN = "unknown"


class Route(str, Enum):
    DIRECT_RESPONSE = "direct_response"
    SQL_ONLY = "sql_only"
    VECTOR_ONLY = "vector_only"
    SQL_VECTOR = "sql_vector"
    LLM_ONLY = "llm_only"
    SQL_LLM = "sql_llm"
    VECTOR_LLM = "vector_llm"
    SQL_VECTOR_LLM = "sql_vector_llm"
    EMERGENCY = "emergency"
    CLARIFY = "clarify"


VALID_INTENTS = frozenset(i.value for i in Intent)

# How SQL services/pricing should filter catalog rows
VALID_SERVICE_FILTER_MODES = frozenset({"none", "named", "category"})
VALID_SQL_TOOLS = frozenset(
    {
        "hours",
        "location",
        "insurance",
        "doctors",
        "specialties",
        "services",
        "pricing",
        "appointments",
        "null",
    }
)

ENTITY_KEYS = (
    "doctor_name",
    "specialty",
    "service",
    "insurance_provider",
    "date",
    "time",
    "patient_name",
    "location",
    "symptom",
)

# Fields that may be a single string or a list of strings
MULTI_ENTITY_KEYS = frozenset(
    {
        "doctor_name",
        "specialty",
        "insurance_provider",
        "date",
        "time",
        "symptom",
    }
)


@dataclass
class ExtractedEntities:
    doctor_name: list[str] | str | None = None
    specialty: list[str] | str | None = None
    service: str | None = None
    insurance_provider: list[str] | str | None = None
    date: list[str] | str | None = None
    time: list[str] | str | None = None
    patient_name: str | None = None
    location: str | None = None
    symptom: list[str] | str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ResolvedIds:
    doctor_id: list[str] | str | None = None
    specialty_id: list[str] | str | None = None
    service_id: str | None = None
    insurance_plan_id: list[str] | str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class NLUResult:
    intent: Intent
    secondary_intents: list[Intent] = field(default_factory=list)
    confidence: float = 0.0
    entities: ExtractedEntities = field(default_factory=ExtractedEntities)
    resolved_ids: ResolvedIds = field(default_factory=ResolvedIds)
    needs_sql: bool = False
    needs_vector: bool = False
    needs_llm: bool = False
    can_respond_directly: bool = False
    is_emergency: bool = False
    is_off_topic: bool = False
    clarification_needed: bool = False
    clarification_question: str | None = None
    reasoning_short: str = ""
    # Router contract extras (Small-LLM-first)
    service_filter_mode: str = "none"  # none | named | category
    sql_tool: str | None = None
    document_needed: bool = False
    provider: str = ""
    model: str = ""
    timings: NLUTimings = field(default_factory=NLUTimings)
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent.value,
            "secondary_intents": [i.value for i in self.secondary_intents],
            "confidence": self.confidence,
            "entities": self.entities.to_dict(),
            "resolved_ids": self.resolved_ids.to_dict(),
            "needs_sql": self.needs_sql,
            "needs_vector": self.needs_vector,
            "needs_llm": self.needs_llm,
            "can_respond_directly": self.can_respond_directly,
            "is_emergency": self.is_emergency,
            "is_off_topic": self.is_off_topic,
            "clarification_needed": self.clarification_needed,
            "clarification_question": self.clarification_question,
            "reasoning_short": self.reasoning_short,
            "service_filter_mode": self.service_filter_mode,
            "sql_tool": self.sql_tool,
            "document_needed": self.document_needed,
            "provider": self.provider,
            "model": self.model,
            "timings": self.timings.to_dict(),
        }


@dataclass(frozen=True)
class RouteDecision:
    route: Route
    needs_sql: bool
    needs_vector: bool
    needs_llm: bool
    nlu: NLUResult
    safety_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "route": self.route.value,
            "needs_sql": self.needs_sql,
            "needs_vector": self.needs_vector,
            "needs_llm": self.needs_llm,
            "safety_message": self.safety_message,
            "nlu": self.nlu.to_dict(),
        }


def parse_nlu_payload(
    data: dict[str, Any],
    *,
    provider: str = "",
    model: str = "",
) -> NLUResult:
    """Normalize provider JSON into an NLUResult with safe fallbacks."""
    intent_raw = str(data.get("intent") or Intent.UNKNOWN.value).strip().lower()
    if intent_raw not in VALID_INTENTS:
        intent = Intent.UNKNOWN
    else:
        intent = Intent(intent_raw)

    secondary: list[Intent] = []
    for item in data.get("secondary_intents") or []:
        value = str(item).strip().lower()
        if value in VALID_INTENTS and value != intent.value:
            secondary.append(Intent(value))

    entity_data = data.get("entities") or {}
    if not isinstance(entity_data, dict):
        entity_data = {}
    entities = ExtractedEntities(
        **{
            key: _normalize_entity_value(entity_data.get(key), multi=(key in MULTI_ENTITY_KEYS))
            for key in ENTITY_KEYS
        }
    )

    confidence = data.get("confidence", 0.0)
    try:
        confidence_f = float(confidence)
    except (TypeError, ValueError):
        confidence_f = 0.0
    confidence_f = max(0.0, min(1.0, confidence_f))

    filter_mode = str(data.get("service_filter_mode") or "none").strip().lower()
    if filter_mode not in VALID_SERVICE_FILTER_MODES:
        filter_mode = "none"

    sql_tool_raw = data.get("sql_tool")
    sql_tool = _optional_str(sql_tool_raw)
    if sql_tool:
        sql_tool = sql_tool.lower()
        if sql_tool not in VALID_SQL_TOOLS or sql_tool == "null":
            sql_tool = None

    document_needed = bool(data.get("document_needed", False))
    needs_vector = bool(data.get("needs_vector", False)) or document_needed
    needs_llm = bool(data.get("needs_llm", False))
    if document_needed:
        needs_llm = True

    return NLUResult(
        intent=intent,
        secondary_intents=secondary,
        confidence=confidence_f,
        entities=entities,
        needs_sql=bool(data.get("needs_sql", False)),
        needs_vector=needs_vector,
        needs_llm=needs_llm,
        can_respond_directly=bool(data.get("can_respond_directly", False)),
        is_emergency=bool(data.get("is_emergency", False)),
        is_off_topic=bool(data.get("is_off_topic", False)),
        clarification_needed=bool(data.get("clarification_needed", False)),
        clarification_question=_optional_str(data.get("clarification_question")),
        reasoning_short=str(data.get("reasoning_short") or "")[:500],
        service_filter_mode=filter_mode,
        sql_tool=sql_tool,
        document_needed=document_needed,
        provider=provider,
        model=model,
        raw=data,
    )


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_entity_value(value: Any, *, multi: bool) -> list[str] | str | None:
    """Normalize entity values; multi fields become lists when multiple items present."""
    if value is None:
        return None
    if isinstance(value, list):
        items = [str(v).strip() for v in value if str(v).strip()]
        if not items:
            return None
        return items if multi else items[0]
    text = str(value).strip()
    if not text:
        return None
    if multi and ("," in text or " or " in text.lower()):
        parts = re.split(r"\s*,\s*|\s+or\s+", text, flags=re.IGNORECASE)
        items = [p.strip() for p in parts if p.strip()]
        return items or None
    return text
