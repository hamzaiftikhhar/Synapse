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
_STRONG_CANCEL_MAX_WORDS = 15
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
    # Working context (Phase 39) — Python-owned session memory the planner
    # reads to answer "what did we discuss" honestly, from structured facts
    # this session actually produced, instead of asking the Large LLM to
    # "recall" from a small recent-messages window. That was reproduced as
    # a real hallucination: a genuine fever question that got "I couldn't
    # verify that doctor" as its actual answer was later "recalled" by the
    # LLM as "I recommended Dr. Omar Haddad" — invented, not remembered.
    # See ROADMAP.md.
    shown_doctors: list[dict[str, Any]] = field(default_factory=list)
    last_recommendation: dict[str, Any] | None = None
    last_slots: list[dict[str, Any]] = field(default_factory=list)
    problem: str | None = None
    preview_only: bool = False

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

    # Strong-cancel phrases ("not anymore", "don't need") are meant to catch
    # a short, cancel-dominant utterance ("Actually no, never mind") — not a
    # clause buried inside an unrelated multi-sentence message. Real
    # patient-question data (Phase 40) showed "it used to hurt but not
    # anymore" (a ~70-word symptom description, "not anymore" modifying
    # "used to hurt", zero cancel intent) firing this and swallowing the
    # patient's actual question behind a generic "what would you like to do
    # instead?" reverse reply. Same word-count-gate pattern already used for
    # _OFF_TOPIC_ABUSE_RE below, at a slightly longer bound since a genuine
    # cancel utterance runs a bit longer than an abusive aside.
    if len(text.split()) <= _STRONG_CANCEL_MAX_WORDS and _STRONG_CANCEL_RE.search(text):
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


_MAX_SHOWN_DOCTORS = 6
_MAX_LAST_SLOTS = 8


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
    shown_doctors: list[dict[str, Any]] | None = None,
    last_recommendation: dict[str, Any] | None = None,
    last_slots: list[dict[str, Any]] | None = None,
    problem: str | None = None,
    preview_only: bool | None = None,
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
    # Working context (Phase 39) — see ConversationTimeline's own comment.
    # shown_doctors/last_slots overwrite (not append) each turn a doctor
    # list/availability result is actually composed — this is "what did we
    # just show," not an accumulating log, so a later "the second doctor"
    # always means the second doctor *of the list still on screen*.
    if shown_doctors is not None:
        timeline.shown_doctors = [
            d for d in shown_doctors if isinstance(d, dict) and d.get("id")
        ][:_MAX_SHOWN_DOCTORS]
    if last_recommendation is not None:
        timeline.last_recommendation = last_recommendation
    if last_slots is not None:
        timeline.last_slots = [
            s for s in last_slots if isinstance(s, dict) and s.get("doctor_id")
        ][:_MAX_LAST_SLOTS]
    if problem:
        timeline.problem = problem
    if preview_only is not None:
        timeline.preview_only = preview_only
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


# Short turns that take up a pending offer rather than starting a new request.
# Whole-message only: "yes, Thursday morning" is a new date, not uptake.
_AFFIRM_RE = re.compile(
    r"^\s*(?:yes|yeah|yep|yup|ya|sure|ok|okay|"
    r"go\s+ahead|sounds\s+good|that\s+works|please\s+do|"
    r"do\s+it|alright|all\s+right|of\s+course|definitely|"
    r"absolutely|please)\s*[.!?]*\s*$",
    re.I,
)
# A second, narrower affirm pattern: a confirmation word paired only with a
# *pronoun/generic reference* to what was just offered ("her", "it", "that
# doctor") — never with anything that could be new information. This must
# stay a fixed, small vocabulary of reference words, not "yes + anything" —
# "yes, Thursday morning" or "yes, Dr. Priya" (a *named* doctor, a fresh
# request) must keep going through ordinary NLU classification, not this
# shortcut. Reproduced against a real transcript: "yes i want her" and
# "yes sure" after a booking offer both fell through to being classified
# from zero context and reached RAG (see ROADMAP.md).
_AFFIRM_REFERENCE_RE = re.compile(
    r"^\s*(?:"
    r"yes,?\s+i\s+want\s+(?:her|him|it|them)|"
    r"yes,?\s+(?:sure|please|okay|ok)|"
    r"book\s+(?:it|her|him|them)|"
    r"(?:that|this)\s+(?:one|doctor)"
    r")\s*[.!?]*\s*$",
    re.I,
)
_DECLINE_RE = re.compile(
    r"^\s*(?:no|nope|nah|no\s+thanks|no\s+thank\s+you|"
    r"not\s+now|not\s+really|maybe\s+later)\s*[.!?]*\s*$",
    re.I,
)


def classify_uptake(message: str) -> str | None:
    """'affirm', 'decline', or None.

    This is a speech-act on the whole turn, not an intent classifier. A
    pending offer is what gives 'Yep.' its meaning; without one these
    strings are ignored.
    """
    text = (message or "").strip()
    if not text or len(text) > 48:
        return None
    if _AFFIRM_RE.match(text) or _AFFIRM_REFERENCE_RE.match(text):
        return "affirm"
    if _DECLINE_RE.match(text):
        return "decline"
    return None


def apply_pending_uptake(nlu: Any, pending: dict[str, Any]) -> Any:
    """Rewrite NLU so the planner executes the pending offer, not a hallucinated intent."""
    from dataclasses import replace

    from apps.chatbot.nlu.schemas import ExtractedEntities, Intent, ResolvedIds

    kind = str(pending.get("type") or "")
    entities = nlu.entities or ExtractedEntities()
    resolved = nlu.resolved_ids or ResolvedIds()
    raw = dict(nlu.raw or {})
    raw["_pending_uptake"] = "affirm"
    raw["_pending_type"] = kind

    if kind == "availability_alternative":
        return replace(
            nlu,
            intent=Intent.DOCTOR_AVAILABILITY,
            confidence=max(float(nlu.confidence or 0), 0.9),
            clarification_needed=False,
            is_off_topic=False,
            entities=replace(
                entities,
                date=None,
                time=None,
                insurance_provider=None,
            ),
            resolved_ids=replace(
                resolved,
                doctor_id=pending.get("doctor_id") or resolved.doctor_id,
            ),
            raw=raw,
        )

    if kind == "slot_confirmation":
        # "yes i want her" / "yes sure" / "book it" taking up a just-
        # offered specific slot. Resolves the doctor so the booking lane
        # launches pre-filled with the right person — the wizard still
        # asks for the exact time itself (it has no slot-prefill concept
        # yet), which is a real, separate gap noted where this is called
        # from, not silently pretended away here.
        return replace(
            nlu,
            intent=Intent.BOOK_APPOINTMENT,
            confidence=max(float(nlu.confidence or 0), 0.9),
            clarification_needed=False,
            is_off_topic=False,
            resolved_ids=replace(
                resolved,
                doctor_id=pending.get("doctor_id") or resolved.doctor_id,
            ),
            raw=raw,
        )

    if kind == "service_followup":
        service_name = pending.get("service_name")
        return replace(
            nlu,
            intent=Intent.DOCTOR_AVAILABILITY,
            confidence=max(float(nlu.confidence or 0), 0.9),
            clarification_needed=False,
            is_off_topic=False,
            entities=replace(
                entities,
                date=None,
                service=service_name or entities.service,
                insurance_provider=None,
            ),
            resolved_ids=replace(
                resolved,
                service_id=pending.get("service_id") or resolved.service_id,
            ),
            raw=raw,
        )
    return nlu


def mark_pending_decline(nlu: Any) -> Any:
    from dataclasses import replace

    from apps.chatbot.nlu.schemas import Intent

    raw = dict(nlu.raw or {})
    raw["_pending_uptake"] = "decline"
    return replace(
        nlu,
        intent=Intent.OFF_TOPIC,
        confidence=0.9,
        clarification_needed=False,
        is_off_topic=True,
        raw=raw,
    )


def pending_offer_from_turn(
    *,
    sql_rows: list[dict[str, Any]] | None,
    nlu: Any,
    last_doctor: dict[str, Any] | None,
    matched_services: list[dict[str, Any]] | None,
) -> dict[str, Any] | None:
    """What this turn just offered the patient, if anything.

    Recorded so a later short 'yes' executes this offer instead of being
    classified in a vacuum.
    """
    for block in sql_rows or []:
        if block.get("handler") != "doctor_availability":
            continue
        meta = block.get("meta") or {}
        if meta.get("temporal_searchable") and not block.get("found"):
            doctor = last_doctor or {}
            return {
                "type": "availability_alternative",
                "action": "forward_scan",
                "doctor_id": doctor.get("id"),
                "doctor_name": doctor.get("name"),
            }
        if block.get("found") and block.get("rows"):
            # A real, specific slot was just offered ("Earliest opening:
            # Dr Priya Chandrasekaran at 12 PM") — the most common
            # confirmation moment in the whole system, and until now the
            # one case this function didn't cover at all. A bare "yes i
            # want her"/"yes sure" next turn had nothing to attach to and
            # fell through to being classified from zero context (reached
            # RAG, found nothing — reproduced against a real transcript,
            # see ROADMAP.md). One offer per turn: the first row is
            # whatever the response actually presented as "the" slot.
            slot = block["rows"][0]
            return {
                "type": "slot_confirmation",
                "action": "confirm_slot",
                "doctor_id": slot.get("doctor_id"),
                "doctor_name": slot.get("doctor"),
                "start": slot.get("start"),
                "date": slot.get("date"),
                "time": slot.get("time"),
            }

    intent = getattr(nlu, "intent", None)
    intent_val = intent.value if hasattr(intent, "value") else str(intent or "")
    if intent_val in {"services_offered", "medical_question", "faq", "pricing"}:
        services = [s for s in (matched_services or []) if s.get("id")]
        if services:
            svc = services[0]
            return {
                "type": "service_followup",
                "action": "show_availability",
                "service_id": svc.get("id"),
                "service_name": svc.get("name"),
            }
    return None


# ── Working context (Phase 39) ────────────────────────────────────────────
# Reproduced as a real hallucination: "Based on what we already discussed,
# who did you recommend?" — a question this session's own history could
# not honestly answer — reached the Large LLM anyway, which invented "Dr.
# Omar Haddad" from nothing. These four classifiers keep that class of
# question out of the LLM/RAG lane entirely: recall is answered from
# ConversationTimeline facts this session actually produced (via a
# template, not a second model pass); a bare date/time correction or an
# ordinal doctor reference is resolved against the same real state instead
# of being independently (re-)classified from zero context. See
# ROADMAP.md's Phase 39 for the full reasoning and root cause.

_SESSION_RECALL_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bwhat (?:insurance|plan) did i (?:tell|give) you\b", re.I), "insurance"),
    (re.compile(r"\bwhat insurance (?:do i have|did i (?:say|mention))\b", re.I), "insurance"),
    (re.compile(r"\b(?:which|what) doctor did you recommend\b", re.I), "recommendation"),
    (re.compile(r"\bwho did you recommend\b", re.I), "recommendation"),
    (re.compile(r"\bwhat (?:were we|was i) (?:just )?talking about\b", re.I), "topic"),
    (re.compile(r"\bwhat was the (?:appointment )?time you found\b", re.I), "time"),
    (re.compile(r"\bwhat (?:time|appointment) did you find\b", re.I), "time"),
    (
        re.compile(r"\bbased on what we(?:'ve| have)? (?:already )?discussed\b", re.I),
        "recommendation",
    ),
)


def classify_session_recall(message: str) -> str | None:
    """'insurance' | 'recommendation' | 'topic' | 'time' | None.

    Whole-message *contains* match (not whole-message-only like
    classify_uptake) — these are typically full sentences, not one-word
    replies, and the recall phrasing itself is what identifies the intent
    regardless of what else is in the sentence.
    """
    text = (message or "").strip()
    if not text:
        return None
    for pattern, field_name in _SESSION_RECALL_PATTERNS:
        if pattern.search(text):
            return field_name
    return None


def compose_session_recall(field_name: str, timeline: ConversationTimeline) -> str:
    """Honest, template-composed answer from real session state — never a
    second LLM pass. An unset pin says so plainly instead of guessing."""
    if field_name == "insurance":
        if timeline.insurance and timeline.insurance.get("name"):
            return f"You told me you have {timeline.insurance['name']}."
        return "You haven't told me your insurance yet — what plan do you have?"
    if field_name == "recommendation":
        rec = timeline.last_recommendation
        if rec and rec.get("name"):
            verb = "I recommended" if rec.get("reason") != "listed" else "I listed"
            return f"{verb} {rec['name']}. Would you like to see their availability?"
        return "I haven't recommended a specific doctor yet — would you like me to find one?"
    if field_name == "time":
        if timeline.last_slots:
            slot = timeline.last_slots[0]
            when = f"{slot.get('date', '')} at {slot.get('time', '')}".strip()
            who = slot.get("doctor_name") or "the provider"
            return f"The earliest time I found was {when} with {who}."
        return "I haven't found an appointment time yet — would you like me to check availability?"
    # "topic" — the closest thing to a recap this timeline can honestly give.
    parts = []
    if timeline.problem:
        parts.append(f"a doctor for {timeline.problem}")
    if timeline.doctor and timeline.doctor.get("name"):
        parts.append(f"{timeline.doctor['name']}")
    if timeline.insurance and timeline.insurance.get("name"):
        parts.append(f"with {timeline.insurance['name']}")
    if parts:
        return "We were looking for " + ", ".join(parts) + ". How can I help further?"
    return "We haven't discussed anything specific yet — what can I help you with?"


_PIN_AMEND_RE = re.compile(
    r"^\s*(?:actually,?\s+)?(?:"
    r"(?:on\s+)?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)|"
    r"tomorrow|today|tonight|"
    r"no,?\s+\w+\s+was\s+better|"
    r"make\s+it\s+(?:tomorrow|today|\w+day)|"
    r"keep\s+everything\s+else\s+the\s+same"
    r")\b.*$",
    re.I,
)


def classify_pin_amendment(message: str, timeline: ConversationTimeline) -> bool:
    """A short date/time retarget on a search already in progress ("Actually
    Tuesday", "No, Monday was better", "make it tomorrow") — never a
    reschedule of a real, confirmed appointment (that path requires
    identity verification and is intentionally left alone: this only
    fires when there's an open doctor/availability thread and no
    confirmed booking to protect)."""
    text = (message or "").strip()
    if not text or len(text) > 80:
        return False
    if not (timeline.availability_target or timeline.doctor):
        return False
    if timeline.booking_stage == "confirmed":
        return False
    return bool(_PIN_AMEND_RE.match(text))


_ORDINAL_WORDS = {
    "first": 0, "1st": 0,
    "second": 1, "2nd": 1,
    "third": 2, "3rd": 2,
    "fourth": 3, "4th": 3,
}
_ORDINAL_DOCTOR_RE = re.compile(
    r"\b(first|1st|second|2nd|third|3rd|fourth|4th)\b.{0,20}\b(doctor|one|provider)\b",
    re.I,
)


def resolve_ordinal_doctor_ref(
    message: str, timeline: ConversationTimeline
) -> dict[str, Any] | None:
    """"the second doctor you mentioned" -> shown_doctors[1], if that many
    were actually shown. List-index coreference only — deliberately not
    general pronoun resolution ("him", "that one"), which stays out of
    scope (see the "Deferred — Conversation state / coreference" entry in
    ROADMAP.md)."""
    match = _ORDINAL_DOCTOR_RE.search(message or "")
    if not match:
        return None
    index = _ORDINAL_WORDS.get(match.group(1).lower())
    if index is None or index >= len(timeline.shown_doctors):
        return None
    return timeline.shown_doctors[index]


_PREVIEW_ONLY_RE = re.compile(
    r"\b(?:"
    r"don'?t\s+book\s+(?:it|anything|yet)|"
    r"wait,?\s+don'?t\s+book|"
    r"just\s+show\s+me|"
    r"show\s+me\s+first|"
    r"before\s+you\s+book"
    r")\b",
    re.I,
)


def classify_preview_only(message: str) -> bool:
    """"don't book anything until you show me..." / "just show me the
    available times" — show availability without committing to a booking
    action this turn."""
    return bool(_PREVIEW_ONLY_RE.search(message or ""))
