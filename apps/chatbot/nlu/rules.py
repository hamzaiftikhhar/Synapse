"""Deterministic NLU rules — fast path before LLM, fallback after LLM failure."""

from __future__ import annotations

import re
from typing import Any

from apps.chatbot.nlu.schemas import Intent

_GREETING_EXACT = frozenset(
    {
        "hi",
        "hello",
        "hey",
        "hiya",
        "howdy",
        "good morning",
        "good afternoon",
        "good evening",
        "hi there",
        "hello there",
        "hey there",
    }
)

_FAREWELL_EXACT = frozenset(
    {
        "bye",
        "goodbye",
        "good bye",
        "see you",
        "see ya",
        "take care",
    }
)

_THANKS_EXACT = frozenset({"thanks", "thank you", "thx", "ty"})

_EMERGENCY_RE = re.compile(
    r"\b("
    r"chest pain|can't breathe|cannot breathe|heart attack|stroke|"
    r"suicidal|kill myself|severe bleeding|unconscious|"
    r"difficulty breathing|choking"
    r")\b",
    re.IGNORECASE,
)

_OFF_TOPIC_RE = re.compile(
    r"\b(fuck|shit|damn|asshole|bitch)\b",
    re.IGNORECASE,
)

_DATE_RE = re.compile(
    r"\b(today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"next week|this week)\b",
    re.IGNORECASE,
)
_TIME_RE = re.compile(r"\b(morning|afternoon|evening|noon|night)\b", re.IGNORECASE)


def _base_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "intent": Intent.UNKNOWN.value,
        "secondary_intents": [],
        "confidence": 0.85,
        "entities": {
            "doctor_name": None,
            "specialty": None,
            "service": None,
            "insurance_provider": None,
            "date": None,
            "time": None,
            "patient_name": None,
            "location": None,
            "symptom": None,
        },
        "needs_sql": False,
        "needs_vector": False,
        "needs_llm": False,
        "can_respond_directly": False,
        "is_emergency": False,
        "is_off_topic": False,
        "clarification_needed": False,
        "clarification_question": None,
        "reasoning_short": "Rule-based classification",
    }
    payload.update(overrides)
    return payload


def _normalize(text: str) -> str:
    text = text.strip().lower()
    if text.startswith("message:"):
        text = text[8:].strip()
    text = re.sub(r"[^\w\s'?-]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _extract_date_time(text: str) -> dict[str, str | None]:
    date_m = _DATE_RE.search(text)
    time_m = _TIME_RE.search(text)
    return {
        "date": date_m.group(0) if date_m else None,
        "time": time_m.group(0) if time_m else None,
    }


def try_rule_classify(
    message: str,
    *,
    tier: str = "all",
) -> dict[str, Any] | None:
    """
    Deterministic classifier.

    tier: fast | strong | fallback | all
    """
    text = _normalize(message)
    if not text:
        return None

    if tier in {"fast", "all"}:
        hit = _match_fast(text)
        if hit:
            return hit

    if tier in {"strong", "all", "fallback"}:
        hit = _match_strong(text, broad=(tier == "fallback"))
        if hit:
            return hit

    return None


def _match_fast(text: str) -> dict[str, Any] | None:
    if text in _GREETING_EXACT or re.fullmatch(
        r"(hi|hello|hey)(\s+there)?[!.?]*", text
    ):
        return _base_payload(
            intent=Intent.GREETING.value,
            confidence=0.99,
            can_respond_directly=True,
            reasoning_short="Greeting (rule)",
            _classifier_source="rules_fast",
        )

    if text in _FAREWELL_EXACT:
        return _base_payload(
            intent=Intent.FAREWELL.value,
            confidence=0.99,
            can_respond_directly=True,
            reasoning_short="Farewell (rule)",
            _classifier_source="rules_fast",
        )

    if text in _THANKS_EXACT:
        return _base_payload(
            intent=Intent.GREETING.value,
            confidence=0.99,
            can_respond_directly=True,
            reasoning_short="Thanks (rule)",
            _classifier_source="rules_fast",
        )

    return None


def _match_strong(text: str, *, broad: bool = False) -> dict[str, Any] | None:
    if _EMERGENCY_RE.search(text):
        return _base_payload(
            intent=Intent.EMERGENCY.value,
            confidence=0.99,
            is_emergency=True,
            can_respond_directly=True,
            entities={**_base_payload()["entities"], "symptom": text[:120]},
            reasoning_short="Emergency keywords (rule)",
            _classifier_source="rules_strong",
        )

    if _OFF_TOPIC_RE.search(text) and len(text.split()) <= 6:
        return _base_payload(
            intent=Intent.OFF_TOPIC.value,
            confidence=0.95,
            is_off_topic=True,
            can_respond_directly=True,
            reasoning_short="Abusive/off-topic (rule)",
            _classifier_source="rules_strong",
        )

    dt = _extract_date_time(text)

    if re.search(r"\b(cancel|cancellation)\b", text) and "appointment" in text:
        return _base_payload(
            intent=Intent.CANCEL_APPOINTMENT.value,
            confidence=0.9,
            needs_sql=True,
            needs_llm=True,
            entities={**_base_payload()["entities"], **dt},
            reasoning_short="Cancel appointment (rule)",
            _classifier_source="rules_strong",
        )

    if re.search(r"\b(reschedule|re-?schedule)\b", text):
        return _base_payload(
            intent=Intent.RESCHEDULE_APPOINTMENT.value,
            confidence=0.9,
            needs_sql=True,
            needs_llm=True,
            entities={**_base_payload()["entities"], **dt},
            reasoning_short="Reschedule (rule)",
            _classifier_source="rules_strong",
        )

    if re.search(r"\b(book|schedule|make)\b", text) and re.search(
        r"\b(appointment|visit)\b", text
    ):
        return _base_payload(
            intent=Intent.BOOK_APPOINTMENT.value,
            confidence=0.92,
            needs_sql=True,
            needs_llm=True,
            entities={**_base_payload()["entities"], **dt},
            reasoning_short="Book appointment (rule)",
            _classifier_source="rules_strong",
        )

    if re.search(r"\b(hours?|open|close|closing)\b", text) and not broad:
        return _base_payload(
            intent=Intent.CLINIC_HOURS.value,
            confidence=0.88,
            needs_sql=True,
            needs_vector=True,
            needs_llm=True,
            entities={**_base_payload()["entities"], **dt},
            reasoning_short="Clinic hours (rule)",
            _classifier_source="rules_strong",
        )

    if re.search(r"\b(insurance|insured|coverage|accept)\b", text):
        intent = (
            Intent.INSURANCE_VERIFICATION.value
            if re.search(r"\b(id|number|plan|member|policy)\b", text)
            else Intent.INSURANCE_ACCEPTED.value
        )
        return _base_payload(
            intent=intent,
            confidence=0.88 if not broad else 0.75,
            needs_sql=True,
            needs_vector=True,
            needs_llm=True,
            reasoning_short="Insurance query (rule)",
            _classifier_source="rules_strong" if not broad else "rules_fallback",
        )

    if broad:
        if re.search(r"\b(doctor|physician|dr\.?)\b", text):
            return _base_payload(
                intent=Intent.DOCTOR_SEARCH.value,
                confidence=0.75,
                needs_sql=True,
                needs_llm=True,
                reasoning_short="Doctor query fallback (rule)",
                _classifier_source="rules_fallback",
            )
        if re.search(r"\b(appointment|visit)\b", text):
            return _base_payload(
                intent=Intent.BOOK_APPOINTMENT.value,
                confidence=0.75,
                needs_sql=True,
                needs_llm=True,
                entities={**_base_payload()["entities"], **dt},
                reasoning_short="Appointment fallback (rule)",
                _classifier_source="rules_fallback",
            )

    return None
