"""Conversation timeline, booking draft, and recovery helpers."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

_STRONG_CANCEL_RE = re.compile(
    r"\b("
    r"never\s*mind|nevermind|changed?\s+my\s+mind|"
    r"actually\s+no|forget\s+(?:it|that)|not\s+anymore|"
    r"don'?t\s+(?:want|need)\b|scratch\s+that"
    r")\b",
    re.I,
)
_WEAK_CANCEL_RE = re.compile(r"\b(nah|nope)\b", re.I)
_RHETORICAL_NAH_RE = re.compile(r"\bor\s+nah\b", re.I)
_CONTINUE_RE = re.compile(
    r"\b("
    r"actually\s+continue|keep\s+going|go\s+on|"
    r"yes\s+continue|let'?s\s+continue|continue\s+booking"
    r")\b",
    re.I,
)
_SAME_DOCTOR_RE = re.compile(
    r"\b("
    r"same\s+doctor|that\s+doctor\s+again|book\s+(?:him|her|them)\s+again|"
    r"book\s+same\s+doctor"
    r")\b",
    re.I,
)
_BOOK_AGAIN_RE = re.compile(r"\bbook\s+(?:him|her|them|that\s+doctor)\s+again\b", re.I)


@dataclass
class ConversationTimeline:
    """Parallel threads the concierge keeps straight across turns."""

    service: dict[str, Any] | None = None
    insurance: dict[str, Any] | None = None
    doctor: dict[str, Any] | None = None
    availability_target: dict[str, Any] | None = None
    booking_stage: str | None = None
    intent_thread: str | None = None
    medical_flags: list[str] = field(default_factory=list)
    pending_clarification: dict[str, Any] | None = None
    last_reversed_thread: str | None = None
    timeline_sensitive: bool = False
    urgent: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ConversationTimeline:
        if not isinstance(data, dict):
            return cls()
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)


@dataclass(frozen=True)
class RecoveryAction:
    kind: str  # reverse | continue | same_doctor | none
    thread: str | None = None
    message_hint: str | None = None
    strong_cancel: bool = False


def load_timeline(ctx: dict[str, Any] | None) -> ConversationTimeline:
    if not isinstance(ctx, dict):
        return ConversationTimeline()
    raw = ctx.get("timeline")
    if isinstance(raw, dict):
        return ConversationTimeline.from_dict(raw)
    # Legacy flat keys
    tl = ConversationTimeline()
    if isinstance(ctx.get("last_doctor"), dict):
        tl.doctor = ctx["last_doctor"]
    if isinstance(ctx.get("last_specialty"), dict):
        tl.service = tl.service or {}
    if ctx.get("current_intent"):
        tl.intent_thread = str(ctx["current_intent"])
    if isinstance(ctx.get("last_service"), dict):
        tl.service = ctx["last_service"]
    if isinstance(ctx.get("last_insurance"), dict):
        tl.insurance = ctx["last_insurance"]
    return tl


def save_timeline(ctx: dict[str, Any], timeline: ConversationTimeline) -> dict[str, Any]:
    out = dict(ctx or {})
    out["timeline"] = timeline.to_dict()
    if timeline.doctor:
        out["last_doctor"] = timeline.doctor
    if timeline.service and timeline.service.get("specialty_id"):
        out["last_specialty"] = {
            "id": timeline.service.get("specialty_id"),
            "name": timeline.service.get("specialty_name") or "",
        }
    if timeline.service:
        out["last_service"] = timeline.service
    if timeline.insurance:
        out["last_insurance"] = timeline.insurance
    if timeline.intent_thread:
        out["current_intent"] = timeline.intent_thread
    return out


def _active_thread(timeline: ConversationTimeline) -> str | None:
    if timeline.intent_thread:
        return timeline.intent_thread
    if timeline.booking_stage:
        return "booking"
    if timeline.insurance:
        return "insurance"
    if timeline.service:
        return "service"
    if timeline.pending_clarification:
        return timeline.pending_clarification.get("type") or "clarify"
    return None


def detect_recovery(message: str, timeline: ConversationTimeline) -> RecoveryAction:
    text = (message or "").strip()
    if not text:
        return RecoveryAction(kind="none")

    if _CONTINUE_RE.search(text):
        return RecoveryAction(
            kind="continue",
            thread=timeline.last_reversed_thread or timeline.intent_thread,
            message_hint="continue_prior_thread",
        )

    if _SAME_DOCTOR_RE.search(text) or _BOOK_AGAIN_RE.search(text):
        if timeline.doctor:
            return RecoveryAction(kind="same_doctor", thread="booking")

    thread = _active_thread(timeline)

    if _STRONG_CANCEL_RE.search(text):
        return RecoveryAction(kind="reverse", thread=thread, strong_cancel=True)

    if _WEAK_CANCEL_RE.search(text) and not _RHETORICAL_NAH_RE.search(text):
        if thread is not None:
            return RecoveryAction(kind="reverse", thread=thread, strong_cancel=False)

    return RecoveryAction(kind="none")


def apply_recovery(
    recovery: RecoveryAction, timeline: ConversationTimeline
) -> ConversationTimeline:
    if recovery.kind == "reverse":
        timeline.last_reversed_thread = recovery.thread
        if recovery.thread == "insurance":
            timeline.insurance = None
        elif recovery.thread == "booking":
            timeline.booking_stage = None
        elif recovery.thread == "service":
            timeline.service = None
    elif recovery.kind == "continue":
        timeline.last_reversed_thread = None
    return timeline


def should_apply_recovery_override(
    recovery: RecoveryAction,
    *,
    sql_found: bool,
) -> bool:
    """
    Whether recovery copy should replace the composed SQL/LLM response.

    Strong cancels always win. Weak cancels only override when there is an
    active thread, or when SQL did not produce a useful answer.
    """
    if recovery.kind != "reverse":
        return False
    if recovery.strong_cancel:
        return True
    if recovery.thread is not None:
        return True
    if sql_found:
        return False
    return True


def merge_turn_context(
    timeline: ConversationTimeline,
    *,
    doctor: dict[str, Any] | None = None,
    service: dict[str, Any] | None = None,
    insurance: dict[str, Any] | None = None,
    availability_target: dict[str, Any] | None = None,
    intent: str | None = None,
    medical_flags: list[str] | None = None,
    booking_stage: str | None = None,
    timeline_sensitive: bool = False,
    urgent: bool = False,
    pending_clarification: dict[str, Any] | None = None,
) -> ConversationTimeline:
    if doctor and doctor.get("id"):
        timeline.doctor = doctor
        timeline.pending_clarification = None
    if service:
        timeline.service = {**(timeline.service or {}), **service}
    if insurance:
        timeline.insurance = insurance
    if availability_target:
        timeline.availability_target = availability_target
    if intent:
        timeline.intent_thread = intent
    if medical_flags:
        for flag in medical_flags:
            if flag and flag not in timeline.medical_flags:
                timeline.medical_flags.append(flag)
    if booking_stage is not None:
        timeline.booking_stage = booking_stage
    if timeline_sensitive:
        timeline.timeline_sensitive = True
    if urgent:
        timeline.urgent = True
    if pending_clarification is not None:
        timeline.pending_clarification = pending_clarification
    return timeline


def recovery_reply(recovery: RecoveryAction, timeline: ConversationTimeline) -> str | None:
    if recovery.kind == "reverse":
        if recovery.thread == "insurance":
            return "No problem — we can skip insurance for now. What would you like to do next?"
        if recovery.thread == "booking":
            return "Got it — I've cleared that booking path. How can I help?"
        return "Sure — what would you like to do instead?"
    if recovery.kind == "continue":
        if timeline.doctor:
            name = timeline.doctor.get("name") or "your doctor"
            return f"Sure — let's continue with {name}. When works for you?"
        return "Sure — let's pick up where we left off."
    if recovery.kind == "same_doctor" and timeline.doctor:
        name = timeline.doctor.get("name") or "that doctor"
        return f"I can book you with {name} again — checking openings."
    return None
