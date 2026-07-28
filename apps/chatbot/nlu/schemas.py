"""Intent, entity, and routing schemas for clinic NLU."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


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


@dataclass
class ExtractedEntities:
    doctor_name: str | None = None
    specialty: str | None = None
    service: str | None = None
    insurance_provider: str | None = None
    date: str | None = None
    time: str | None = None
    patient_name: str | None = None
    location: str | None = None
    symptom: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return asdict(self)


@dataclass
class ResolvedIds:
    doctor_id: str | None = None
    specialty_id: str | None = None
    service_id: str | None = None
    insurance_plan_id: str | None = None

    def to_dict(self) -> dict[str, str | None]:
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
    provider: str = ""
    model: str = ""
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
            "provider": self.provider,
            "model": self.model,
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
            key: _optional_str(entity_data.get(key))
            for key in ENTITY_KEYS
        }
    )

    confidence = data.get("confidence", 0.0)
    try:
        confidence_f = float(confidence)
    except (TypeError, ValueError):
        confidence_f = 0.0
    confidence_f = max(0.0, min(1.0, confidence_f))

    return NLUResult(
        intent=intent,
        secondary_intents=secondary,
        confidence=confidence_f,
        entities=entities,
        needs_sql=bool(data.get("needs_sql", False)),
        needs_vector=bool(data.get("needs_vector", False)),
        needs_llm=bool(data.get("needs_llm", False)),
        can_respond_directly=bool(data.get("can_respond_directly", False)),
        is_emergency=bool(data.get("is_emergency", False)),
        is_off_topic=bool(data.get("is_off_topic", False)),
        clarification_needed=bool(data.get("clarification_needed", False)),
        clarification_question=_optional_str(data.get("clarification_question")),
        reasoning_short=str(data.get("reasoning_short") or "")[:500],
        provider=provider,
        model=model,
        raw=data,
    )


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
