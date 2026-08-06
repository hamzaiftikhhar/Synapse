"""Intent prioritization and compound-turn decomposition."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from apps.chatbot.conversation_state import ConversationTimeline
from apps.chatbot.nlu.schemas import Intent, NLUResult
from apps.chatbot.routing.signals import (
    has_symptom_cues,
    is_doctor_availability_query,
    is_transactional_booking,
    is_urgent_availability_request,
)

_WEDDING_RE = re.compile(
    r"\b(wedding|event|big\s+day|before\s+(?:the\s+)?(?:wedding|ceremony))\b", re.I
)
_BRACES_FAMILY_RE = re.compile(
    r"\b(wife|husband|kid|child|son|daughter|mom|dad|parent)\b.*\b(braces|orthodont)\b|"
    r"\b(braces|orthodont)\b.*\b(wife|husband|kid|child|son|daughter|mom|dad|parent)\b",
    re.I,
)
_COSMETIC_RE = re.compile(
    r"\b(whitening|bleach|botox|filler|veneers|invisalign|braces|cosmetic)\b", re.I
)
_SOFT_SYMPTOM_RE = re.compile(
    r"\b(pain|ache|hurt|hurts|itch|fever|cough|dizzy|nausea|"
    r"headache|rash|swelling|molar|toothache|symptom|sick|sore|bleeding)\b",
    re.I,
)


def _has_soft_symptom(text: str) -> bool:
    return bool(_SOFT_SYMPTOM_RE.search(text or "")) or has_symptom_cues(text)


@dataclass
class SubIntent:
    kind: str
    priority: int
    label: str = ""


@dataclass
class PrioritizedTurn:
    primary_intent: Intent | None = None
    sub_intents: list[SubIntent] = field(default_factory=list)
    urgent_booking: bool = False
    timeline_sensitive: bool = False
    offer_earliest_slots: bool = False
    compound: bool = False
    notes: list[str] = field(default_factory=list)


def analyze_compound_turn(
    message: str,
    nlu: NLUResult,
    timeline: ConversationTimeline | None = None,
) -> PrioritizedTurn:
    """Break compound patient turns into prioritized sub-problems."""
    text = message or ""
    tl = timeline or ConversationTimeline()
    subs: list[SubIntent] = []
    notes: list[str] = []

    if nlu.is_emergency or nlu.intent == Intent.EMERGENCY or _has_soft_symptom(text):
        subs.append(SubIntent(kind="medical", priority=0, label="safety"))
        if re.search(r"\b(hurt|pain|ache|urgent|asap|emergency|molar|toothache)\b", text, re.I):
            subs.append(SubIntent(kind="booking", priority=1, label="urgent_slot"))

    if is_urgent_availability_request(text) or tl.urgent:
        subs.append(SubIntent(kind="booking", priority=1, label="urgent_availability"))
        notes.append("urgent_availability")

    if is_doctor_availability_query(text):
        subs.append(SubIntent(kind="availability", priority=1, label="doctor_time"))
        notes.append("doctor_availability")

    if is_transactional_booking(text) or nlu.intent in {
        Intent.BOOK_APPOINTMENT,
        Intent.RESCHEDULE_APPOINTMENT,
    }:
        subs.append(SubIntent(kind="booking", priority=2, label="book"))

    if nlu.intent in {Intent.INSURANCE_ACCEPTED, Intent.INSURANCE_VERIFICATION} or getattr(
        nlu.entities, "insurance_provider", None
    ):
        subs.append(SubIntent(kind="insurance", priority=3, label="insurance"))

    if nlu.intent in {Intent.DOCTOR_SEARCH, Intent.DOCTOR_AVAILABILITY} or getattr(
        nlu.entities, "doctor_name", None
    ):
        subs.append(SubIntent(kind="doctor", priority=3, label="provider"))

    if nlu.intent in {Intent.FAQ, Intent.MEMBERSHIP}:
        subs.append(SubIntent(kind="faq", priority=4, label="info"))
    elif nlu.intent == Intent.MEDICAL_QUESTION and not _has_soft_symptom(text):
        subs.append(SubIntent(kind="faq", priority=4, label="info"))

    subs.sort(key=lambda s: s.priority)
    compound = len({s.kind for s in subs}) > 1

    urgent = is_urgent_availability_request(text) or bool(
        re.search(r"\b(asap|squeeze\s+me\s+in|urgent|emergency\s+appointment)\b", text, re.I)
    )
    timeline_sensitive = bool(_WEDDING_RE.search(text)) or tl.timeline_sensitive
    offer_earliest = urgent or timeline_sensitive or bool(
        re.search(r"\b(hurt|pain|molar|toothache)\b", text, re.I)
    )

    primary = _pick_primary_intent(nlu, subs, text)

    if _BRACES_FAMILY_RE.search(text):
        notes.append("family_braces_qualifier")

    if _COSMETIC_RE.search(text) and timeline_sensitive:
        notes.append("cosmetic_timeline")

    return PrioritizedTurn(
        primary_intent=primary,
        sub_intents=subs,
        urgent_booking=urgent,
        timeline_sensitive=timeline_sensitive,
        offer_earliest_slots=offer_earliest,
        compound=compound,
        notes=notes,
    )


def _pick_primary_intent(
    nlu: NLUResult, subs: list[SubIntent], message: str
) -> Intent | None:
    if not subs:
        return nlu.intent

    top = subs[0].kind
    if top == "medical" and any(s.kind == "booking" for s in subs):
        return nlu.intent if nlu.intent != Intent.UNKNOWN else Intent.MEDICAL_QUESTION
    if top == "availability" or is_doctor_availability_query(message):
        return Intent.DOCTOR_AVAILABILITY
    if top == "booking" or is_urgent_availability_request(message):
        if is_doctor_availability_query(message):
            return Intent.DOCTOR_AVAILABILITY
        return Intent.BOOK_APPOINTMENT
    if top == "insurance":
        return Intent.INSURANCE_ACCEPTED
    if top == "doctor":
        return Intent.DOCTOR_SEARCH
    return nlu.intent


def apply_priority_to_nlu(nlu: NLUResult, turn: PrioritizedTurn) -> NLUResult:
    """Adjust NLU intent/secondary intents from prioritizer output."""
    from dataclasses import replace

    if turn.primary_intent is None or turn.primary_intent == nlu.intent:
        secondaries = list(nlu.secondary_intents)
        for sub in turn.sub_intents[1:3]:
            mapped = _sub_to_intent(sub.kind)
            if mapped and mapped not in secondaries and mapped != nlu.intent:
                secondaries.append(mapped)
        if secondaries != nlu.secondary_intents:
            return replace(nlu, secondary_intents=secondaries)
        return nlu

    secondaries = [i for i in nlu.secondary_intents if i != turn.primary_intent]
    if nlu.intent not in secondaries and nlu.intent != turn.primary_intent:
        secondaries.insert(0, nlu.intent)
    return replace(
        nlu,
        intent=turn.primary_intent,
        secondary_intents=secondaries[:3],
        confidence=max(float(nlu.confidence or 0), 0.88),
    )


def _sub_to_intent(kind: str) -> Intent | None:
    return {
        "medical": Intent.MEDICAL_QUESTION,
        "booking": Intent.BOOK_APPOINTMENT,
        "availability": Intent.DOCTOR_AVAILABILITY,
        "insurance": Intent.INSURANCE_ACCEPTED,
        "doctor": Intent.DOCTOR_SEARCH,
        "faq": Intent.FAQ,
    }.get(kind)
