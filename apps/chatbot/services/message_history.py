"""Cursor pagination over one ChatSession's messages — shared between the
patient-facing widget endpoints (apps/api/widget/router.py) and the
staff-facing conversations endpoints (apps/api/chat/router.py) so both
sides page through history identically instead of maintaining two copies
of the same query shape."""

from __future__ import annotations

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
