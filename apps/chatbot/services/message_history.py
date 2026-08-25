"""Cursor pagination over one ChatSession's messages — shared between the
patient-facing widget endpoints (apps/api/widget/router.py) and the
staff-facing conversations endpoints (apps/api/chat/router.py) so both
sides page through history identically instead of maintaining two copies
of the same query shape."""

from __future__ import annotations

from typing import Any

from apps.chatbot.models import ChatMessage, ChatSession


def paginate_messages(
    session: ChatSession, *, before: int | None, limit: int
) -> tuple[list[ChatMessage], bool]:
    """One page of a session's messages, oldest-first, plus whether there
    are more beyond it. `before=None` means "the newest page" (used by
    both a resume/first load and a bare call to the pagination endpoint);
    otherwise strictly older than that sequence_number cursor.
    """
    qs = ChatMessage.objects.filter(session=session)
    if before is not None:
        qs = qs.filter(sequence_number__lt=before)
    # Over-fetch by one to learn has_more without a second COUNT query —
    # newest-of-the-range first so LIMIT bounds "the N most recent older
    # messages" rather than the N oldest ones.
    rows = list(qs.order_by("-sequence_number")[: limit + 1])
    has_more = len(rows) > limit
    rows = rows[:limit]
    rows.reverse()
    return rows, has_more


def persist_confirmation_message(chat_session: ChatSession, confirmation: dict[str, Any]) -> None:
    """Records a booking confirmation as its own ChatMessage.

    BookingService.confirm() is its own API call, entirely separate from
    the normal ChatEngine.process()/_save_messages() pipeline — without
    this, a confirmed appointment left no trace in the transcript at all,
    and a resumed conversation could only ever show the *original*
    booking_wizard launch card (which, replayed later, has no memory of
    ever having been completed). Persisted so /chat/resume, pagination,
    and the staff conversations view can all show the same confirmation
    receipt the live wizard showed, via the existing (previously unused)
    `case "confirmation"` renderer.
    """
    from django.db import transaction

    from apps.chatbot.models import MessageRole, MessageType

    doctor_name = confirmation.get("doctor_name") or ""
    slot_summary = confirmation.get("slot_summary") or ""
    content = "You're confirmed" + (f" with {doctor_name}" if doctor_name else "")
    if slot_summary:
        content += f" — {slot_summary}"
    content += "."

    with transaction.atomic():
        # Same locking discipline as ChatEngine._save_messages — a
        # concurrent chat turn saving on this same session must not race
        # this insert onto the same sequence_number.
        ChatSession.objects.select_for_update().get(pk=chat_session.pk)
        last = (
            ChatMessage.objects.filter(session=chat_session)
            .order_by("-sequence_number")
            .values_list("sequence_number", flat=True)
            .first()
        )
        ChatMessage.objects.create(
            clinic=chat_session.clinic,
            session=chat_session,
            role=MessageRole.ASSISTANT,
            message_type=MessageType.TEXT,
            content=content,
            sequence_number=(last or 0) + 1,
            metadata={"confirmation": confirmation},
        )
