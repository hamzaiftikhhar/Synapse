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

from apps.chatbot.models import ChatSession, ChatVisitor
from apps.patients.models import Patient


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
