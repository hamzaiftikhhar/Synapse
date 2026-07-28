"""Deterministic NLU rules — fast path before LLM, fallback after LLM failure."""

from __future__ import annotations

import re
from typing import Any

from apps.chatbot.nlu.entity_extract import (
    extract_emergency_symptoms,
    extract_entities,
    has_negation_near,
    looks_like_compound,
    merge_entities,
)
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
        "hi how are you",
        "hi how are you doing",
        "hello how are you",
        "hey how are you",
        "how are you",
        "how are you doing",
        "how r you",
        "whats up",
        "what's up",
        "sup",
    }
)

_GREETING_RE = re.compile(
    r"^(hi|hello|hey|hiya|howdy)"
    r"(?:\s*,?\s*(?:there|folks|everyone|all))?"
    r"(?:\s*[,!]?\s*(?:how\s+are\s+you(?:\s+doing)?(?:\s+today)?)?)?"
    r"[!.?]*$",
    re.IGNORECASE,
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

_THANKS_EXACT = frozenset({"thanks", "thank you", "thx", "ty", "thanks!", "thank you!"})

_EMERGENCY_RE = re.compile(
    r"\b("
    r"chest pain|can't breathe|cannot breathe|heart attack|stroke|"
    r"suicidal|kill myself|severe bleeding|unconscious|"
    r"difficulty breathing|choking|left arm numbness"
    r")\b",
    re.IGNORECASE,
)

_OFF_TOPIC_RE = re.compile(
    r"\b(fuck|shit|damn|asshole|bitch)\b",
    re.IGNORECASE,
)


def _empty_entities() -> dict[str, Any]:
    return {
        "doctor_name": None,
        "specialty": None,
        "service": None,
        "insurance_provider": None,
        "date": None,
        "time": None,
        "patient_name": None,
        "location": None,
        "symptom": None,
    }


def _base_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "intent": Intent.UNKNOWN.value,
        "secondary_intents": [],
        "confidence": 0.85,
        "entities": _empty_entities(),
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


def _with_entities(message: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Attach local entity extraction onto a rule hit."""
    extracted = extract_entities(message)
    payload["entities"] = merge_entities(payload.get("entities"), extracted)
    return payload


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
        # Compound multi-intent → do not force a single strong rule
        if tier != "fallback" and looks_like_compound(message):
            return None
        hit = _match_strong(message, text, broad=(tier == "fallback"))
        if hit:
            return _with_entities(message, hit)

    return None


def _match_fast(text: str) -> dict[str, Any] | None:
    if text in _GREETING_EXACT or _GREETING_RE.fullmatch(text):
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

    if text.rstrip("!.?") in _THANKS_EXACT or text in _THANKS_EXACT:
        return _base_payload(
            intent=Intent.GREETING.value,
            confidence=0.99,
            can_respond_directly=True,
            reasoning_short="Thanks (rule)",
            _classifier_source="rules_fast",
        )

    return None


def _match_strong(
    original: str,
    text: str,
    *,
    broad: bool = False,
) -> dict[str, Any] | None:
    if _EMERGENCY_RE.search(text):
        symptoms = extract_emergency_symptoms(original)
        return _base_payload(
            intent=Intent.EMERGENCY.value,
            confidence=0.99,
            is_emergency=True,
            can_respond_directly=True,
            entities={
                **_empty_entities(),
                "symptom": symptoms or None,
            },
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

    # Negated action verbs must not fire positive intent rules
    if has_negation_near(text, "reschedule") or has_negation_near(text, "cancel"):
        # Fall through — let LLM / fallback decide (often follow-up / clarify)
        if not broad:
            return None

    if (
        re.search(r"\b(cancel|cancellation)\b", text)
        and re.search(r"\b(appointment|visit|meeting)\b", text)
        and not has_negation_near(text, "cancel")
    ):
        return _base_payload(
            intent=Intent.CANCEL_APPOINTMENT.value,
            confidence=0.9,
            needs_sql=True,
            needs_llm=True,
            reasoning_short="Cancel appointment (rule)",
            _classifier_source="rules_strong",
        )

    if re.search(r"\b(reschedule|re-?schedule)\b", text) and not has_negation_near(
        text, "reschedule"
    ):
        return _base_payload(
            intent=Intent.RESCHEDULE_APPOINTMENT.value,
            confidence=0.9,
            needs_sql=True,
            needs_llm=True,
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
            reasoning_short="Book appointment (rule)",
            _classifier_source="rules_strong",
        )

    if re.search(r"\b(slot|slots|available|availability)\b", text) and re.search(
        r"\b(tomorrow|today|monday|tuesday|wednesday|thursday|friday|"
        r"saturday|sunday|morning|afternoon|evening|doctor|dr)\b",
        text,
    ):
        return _base_payload(
            intent=Intent.DOCTOR_AVAILABILITY.value,
            confidence=0.9,
            needs_sql=True,
            needs_llm=True,
            reasoning_short="Availability (rule)",
            _classifier_source="rules_strong",
        )

    if re.search(r"\b(hours?|open|close|closing)\b", text) and not broad:
        return _base_payload(
            intent=Intent.CLINIC_HOURS.value,
            confidence=0.88,
            needs_sql=True,
            needs_vector=True,
            needs_llm=True,
            reasoning_short="Clinic hours (rule)",
            _classifier_source="rules_strong",
        )

    if re.search(
        r"\b(what services|which services|services do you|list (?:of )?services|"
        r"services (?:do you )?(?:offer|provide|have)|medical spa)\b",
        text,
    ):
        return _base_payload(
            intent=Intent.SERVICES_OFFERED.value,
            confidence=0.9,
            needs_sql=True,
            needs_vector=True,
            needs_llm=True,
            reasoning_short="Services offered (rule)",
            _classifier_source="rules_strong",
        )

    if re.search(
        r"\b(referral|referrals|do i need|policy|policies|how does|"
        r"what (?:is|are) your)\b",
        text,
    ) and re.search(
        r"\b(specialists?|referral|referrals|insurance|visit|appointment)\b",
        text,
    ):
        return _base_payload(
            intent=Intent.FAQ.value,
            confidence=0.85,
            needs_vector=True,
            needs_llm=True,
            reasoning_short="FAQ / policy (rule)",
            _classifier_source="rules_strong",
        )

    # Insurance: require accept/coverage/take OR explicit brand — avoid pediatric false positives
    has_insurance_word = bool(re.search(r"\binsurance\b", text))
    has_accept_frame = bool(
        re.search(r"\b(accept|take|cover|covered|coverage|insured)\b", text)
    )
    has_brand = bool(
        re.search(
            r"\b(blue\s*cross|aetna|cigna|humana|kaiser|medicare|medicaid|"
            r"united\s*health|anthem|oscar|molina)\b",
            text,
        )
    )
    if (has_insurance_word and has_accept_frame) or (has_insurance_word and has_brand) or (
        has_accept_frame and has_brand
    ):
        # Pediatric / "insurance related to age" is usually services/faq — skip strong rule
        if re.search(r"\b(years?\s+old|child|son|daughter|pediatric)\b", text) and not has_brand:
            return None
        intent = (
            Intent.INSURANCE_VERIFICATION.value
            if re.search(r"\b(id|number|member|policy|my plan)\b", text)
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
        if re.search(r"\b(appointment|visit|slot|available)\b", text):
            return _base_payload(
                intent=Intent.BOOK_APPOINTMENT.value,
                confidence=0.7,
                needs_sql=True,
                needs_llm=True,
                clarification_needed=True,
                clarification_question=(
                    "I'm having trouble retrieving availability right now. "
                    "Are you looking to book an appointment or check doctor availability?"
                ),
                reasoning_short="Appointment fallback (rule)",
                _classifier_source="rules_fallback",
            )

    return None
