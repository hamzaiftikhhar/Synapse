"""ChatVisitor <-> Patient identity linking — the anonymous-to-identified
bridge (ROADMAP.md's persistent-chat-history phase, Step 3).

Two independent call sites resolve a Patient onto a ChatSession today —
otp_service.verify_otp and booking/service.py's confirm() — and both need
the same visitor-level backfill, so the logic lives here once rather than
being duplicated in each.

Conversation rows (ChatSession, ChatMessage) are never recreated, copied,
or have their id/session_token touched by anything in this module — only
the `patient` FK on rows that already exist gets backfilled. `is_
authenticated` is deliberately never touched here: it records whether a
given session itself completed a verification, which is a session-level
fact this module has no business overwriting for a visitor's *other*
sessions just because one of them got linked.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from apps.chatbot.models import ChatSession, ChatVisitor
from apps.patients.models import Patient

if TYPE_CHECKING:
    from apps.clinics.models import Clinic


def link_visitor_to_patient(visitor: ChatVisitor | None, patient: Patient) -> bool:
    """Core linking primitive. Links `visitor` to `patient` once and
    backfills `patient` onto every ChatSession already belonging to that
    visitor. No-ops (returns False) if `visitor` is None (session has no
    visitor — legacy path) or the visitor is already linked, to a patient
    other than or the same as this one — an established identity is never
    silently reassigned by a later contact/verification event.
    """
    if visitor is None or visitor.patient_id is not None:
        return False
    visitor.patient = patient
    visitor.save(update_fields=["patient"])
    ChatSession.objects.filter(visitor=visitor).exclude(patient=patient).update(patient=patient)
    return True


def link_session_visitor_to_patient(session: ChatSession, patient: Patient) -> bool:
    """Convenience wrapper for call sites that already have a ChatSession
    in hand (OTP verification, booking confirm()) rather than a bare
    visitor."""
    return link_visitor_to_patient(getattr(session, "visitor", None), patient)


def list_other_verified_sessions(
    clinic: "Clinic", patient: Patient, *, exclude: ChatSession
) -> list[dict]:
    """Read-only summaries of the patient's *other* conversations, for the
    cross-device "you have a previous conversation" affordance shown after
    OTP verification on a new browser/device.

    `is_authenticated=True` is the hard security boundary, same as
    everywhere else in this module: it only ever matches a session that
    itself completed a real verification, never a same-visitor sibling
    that only got `patient` passively backfilled by
    `link_visitor_to_patient` (which deliberately never touches
    `is_authenticated` — see its docstring above). Callers must never
    merge a listed session's messages into their own live session; opening
    one is a separate, explicit read via the existing per-session messages
    endpoint.
    """
    from django.db.models import Count

    from apps.chatbot.models import ChatMessage, MessageRole, MessageType

    sessions = list(
        ChatSession.objects.filter(clinic=clinic, patient=patient, is_authenticated=True)
        .exclude(id=exclude.id)
        .order_by("-last_active_at")[:20]
    )
    if not sessions:
        return []

    session_ids = [s.id for s in sessions]
    # Tool calls/results and system/error rows are internal plumbing, not
    # something a patient should see previewed as "their last message."
    visible = (MessageRole.USER, MessageRole.ASSISTANT)
    counts = {
        row["session_id"]: row["n"]
        for row in ChatMessage.objects.filter(
            session_id__in=session_ids, role__in=visible, message_type=MessageType.TEXT,
        )
        .values("session_id")
        .annotate(n=Count("id"))
    }
    last_messages = {
        m.session_id: m
        for m in ChatMessage.objects.filter(
            session_id__in=session_ids, role__in=visible, message_type=MessageType.TEXT,
        )
        .order_by("session_id", "-sequence_number")
        .distinct("session_id")
    }

    return [
        {
            "session_token": s.session_token,
            "last_active_at": s.last_active_at,
            "message_count": counts.get(s.id, 0),
            "preview": last_messages[s.id].content[:140] if s.id in last_messages else "",
        }
        for s in sessions
    ]
