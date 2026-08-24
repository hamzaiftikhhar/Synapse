"""
Chat endpoint — the primary patient-facing message API.

POST /api/v1/chat/message
  - Accepts patient JWT (widget) or staff JWT (for testing).
  - Patient JWT: resolves patient + session from token.
  - Staff JWT:   clinic-scoped, no patient; good for testing via Swagger.
"""

from __future__ import annotations

import logging

from ninja import Query, Router
from ninja.errors import HttpError

from apps.api.auth.deps import PatientJWTAuth, StaffJWTAuth, clinic_from
from apps.api.chat.schemas import (
    ChatMessageIn,
    ChatMessageOut,
    ChatTimingsOut,
    ConversationMessageOut,
    ConversationMessagesOut,
    ConversationSummaryOut,
)
from apps.api.common.schemas import PaginatedOut

logger = logging.getLogger(__name__)

router = Router(tags=["Chat"])

_patient_auth = PatientJWTAuth()
_staff_auth = StaffJWTAuth()


# ── Patient-facing endpoint (widget) ─────────────────────────────────────────

@router.post("/message", response=ChatMessageOut, auth=_patient_auth)
def patient_chat_message(request, payload: ChatMessageIn) -> ChatMessageOut:
    """
    Process one patient message and return an AI-generated response.

    Auth: patient_access JWT (from /widget/otp/verify).
    """
    auth = request.auth
    clinic = auth.clinic
    patient = auth.patient

    message = (payload.message or "").strip()
    if not message:
        raise HttpError(422, "Message is required")
    if len(message) > 2000:
        raise HttpError(422, "Message too long (max 2000 characters)")

    session = _resolve_session(clinic, patient, payload.session_token)

    from apps.chatbot.engine import ChatEngine
    try:
        result = ChatEngine().process(
            clinic=clinic,
            message=message,
            session=session,
            patient=patient,
        )
    except Exception as exc:
        logger.exception("ChatEngine failed for clinic=%s", clinic.id)
        return _fallback_out()

    return _to_out(result)


# ── Staff/debug endpoint (portal + Swagger testing) ──────────────────────────

@router.post("/message/staff", response=ChatMessageOut, auth=_staff_auth)
def staff_chat_message(request, payload: ChatMessageIn) -> ChatMessageOut:
    """
    Process a message in the context of the staff's clinic.

    Auth: staff_access JWT. Useful for QA and Swagger. Still uses a real
    ChatSession (returned as meta.session_token) so verify-identity →
    appointment list/cancel/reschedule work the same as the public widget.
    """
    clinic = clinic_from(request)

    message = (payload.message or "").strip()
    if not message:
        raise HttpError(422, "Message is required")
    if len(message) > 2000:
        raise HttpError(422, "Message too long (max 2000 characters)")

    session = _resolve_staff_test_session(clinic, payload.session_token)

    from apps.chatbot.engine import ChatEngine
    try:
        result = ChatEngine().process(
            clinic=clinic,
            message=message,
            session=session,
            patient=session.patient if session.is_authenticated else None,
        )
    except Exception as exc:
        logger.exception("ChatEngine (staff) failed for clinic=%s", clinic.id)
        out = _fallback_out()
        out.meta = {**out.meta, "session_token": session.session_token}
        return out

    out = _to_out(result)
    out.meta = {**out.meta, "session_token": session.session_token}
    return out


# ── Staff-facing conversations inbox ──────────────────────────────────────────
# A clinic's own staff and a super admin who has entered this clinic
# (/auth/enter-clinic) both land here through the exact same code path —
# clinic_from(request) resolves the tenant from the staff JWT's tenant
# claim either way, so no separate "can this admin see this clinic's
# chats" check is needed beyond the tenant scoping every other staff
# dashboard endpoint already relies on.

_CONVERSATIONS_DEFAULT_LIMIT = 50
_CONVERSATIONS_MAX_LIMIT = 100
_MESSAGES_DEFAULT_LIMIT = 50
_MESSAGES_MAX_LIMIT = 100


@router.get(
    "/conversations", response=PaginatedOut[ConversationSummaryOut], auth=_staff_auth
)
def list_conversations(
    request,
    search: str | None = Query(None),
    limit: int = Query(_CONVERSATIONS_DEFAULT_LIMIT, ge=1, le=_CONVERSATIONS_MAX_LIMIT),
    offset: int = Query(0, ge=0),
):
    from django.db.models import Q

    from apps.chatbot.models import ChatSession

    clinic = clinic_from(request)
    qs = (
        ChatSession.objects.filter(clinic=clinic)
        .select_related("patient", "visitor")
        .order_by("-last_active_at")
    )
    if search:
        qs = qs.filter(
            Q(patient__first_name__icontains=search)
            | Q(patient__last_name__icontains=search)
            | Q(patient__phone__icontains=search)
        )
    count = qs.count()
    sessions = list(qs[offset : offset + limit])
    return PaginatedOut(
        count=count, results=[_serialize_conversation(s) for s in sessions]
    )


@router.get(
    "/conversations/{session_id}/messages",
    response=ConversationMessagesOut,
    auth=_staff_auth,
)
def conversation_messages(
    request,
    session_id: str,
    before: int | None = None,
    limit: int = _MESSAGES_DEFAULT_LIMIT,
):
    """Cursor-paginated transcript for one conversation. Ownership here is
    staff-JWT-plus-clinic-scope, not the visitor bearer header the public
    widget endpoint requires — staff already proved tenant membership."""
    from apps.chatbot.models import ChatSession
    from apps.chatbot.services.message_history import paginate_messages

    from django.core.exceptions import ValidationError

    clinic = clinic_from(request)
    try:
        session = ChatSession.objects.get(clinic=clinic, id=session_id)
    except (ChatSession.DoesNotExist, ValueError, ValidationError):
        raise HttpError(404, "Conversation not found") from None

    if before is not None and before < 1:
        raise HttpError(422, "Invalid cursor")
    limit = max(1, min(int(limit or _MESSAGES_DEFAULT_LIMIT), _MESSAGES_MAX_LIMIT))

    rows, has_more = paginate_messages(session, before=before, limit=limit)
    return ConversationMessagesOut(
        messages=[
            ConversationMessageOut(
                id=str(m.id),
                role=m.role,
                message_type=m.message_type,
                content=m.content,
                metadata=m.metadata or {},
                sequence_number=m.sequence_number,
                created_at=m.created_at.isoformat(),
            )
            for m in rows
        ],
        has_more=has_more,
    )


def _serialize_conversation(session: object) -> ConversationSummaryOut:
    patient = session.patient  # type: ignore[attr-defined]
    visitor = session.visitor  # type: ignore[attr-defined]
    if patient is not None:
        display_name = patient.full_name or "Unnamed patient"
        phone = patient.phone
    elif visitor is not None:
        display_name = "Anonymous visitor"
        phone = None
    else:
        display_name = "Anonymous"
        phone = None
    messages = session.messages  # type: ignore[attr-defined]
    last_message = messages.order_by("-sequence_number").first()
    return ConversationSummaryOut(
        id=str(session.id),  # type: ignore[attr-defined]
        session_token=session.session_token,  # type: ignore[attr-defined]
        display_name=display_name,
        phone=phone,
        is_authenticated=session.is_authenticated,  # type: ignore[attr-defined]
        status=session.status,  # type: ignore[attr-defined]
        message_count=messages.count(),
        last_message_preview=(last_message.content[:140] if last_message else None),
        last_active_at=session.last_active_at.isoformat(),  # type: ignore[attr-defined]
        created_at=session.created_at.isoformat(),  # type: ignore[attr-defined]
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _resolve_staff_test_session(clinic: object, session_token: str | None) -> object:
    """Guest-style ChatSession for staff portal QA of patient flows."""
    import secrets

    from apps.chatbot.models import ChatSession, ChatSessionStatus
    from django.utils import timezone

    if session_token:
        try:
            return ChatSession.objects.get(clinic=clinic, session_token=session_token)
        except ChatSession.DoesNotExist:
            pass

    return ChatSession.objects.create(
        clinic=clinic,
        session_token=secrets.token_urlsafe(32),
        status=ChatSessionStatus.ACTIVE,
        last_active_at=timezone.now(),
    )


def _resolve_session(clinic: object, patient: object, session_token: str | None) -> object | None:
    """Load or create a ChatSession for this patient."""
    try:
        from apps.chatbot.models import ChatSession, ChatSessionStatus
        from django.utils import timezone

        if session_token:
            try:
                return ChatSession.objects.get(clinic=clinic, session_token=session_token)
            except ChatSession.DoesNotExist:
                pass

        # Get or create active session for this patient
        session, _ = ChatSession.objects.get_or_create(
            clinic=clinic,
            patient=patient,
            status=ChatSessionStatus.ACTIVE,
            defaults={
                "session_token": _generate_token(),
                "ip_hash": "",
                "user_agent": "",
                "is_authenticated": True,
                "last_active_at": timezone.now(),
            },
        )
        return session
    except Exception:
        logger.exception("Failed to resolve chat session")
        return None


def _generate_token() -> str:
    import secrets
    return secrets.token_urlsafe(32)


def _to_out(result: object) -> ChatMessageOut:
    raw = result.timings  # type: ignore[attr-defined]
    return ChatMessageOut(
        response=result.response,  # type: ignore[attr-defined]
        route=result.route,  # type: ignore[attr-defined]
        intent=result.intent,  # type: ignore[attr-defined]
        confidence=result.confidence,  # type: ignore[attr-defined]
        needs_sql=result.needs_sql,  # type: ignore[attr-defined]
        needs_vector=result.needs_vector,  # type: ignore[attr-defined]
        needs_llm=result.needs_llm,  # type: ignore[attr-defined]
        safety_message=result.safety_message,  # type: ignore[attr-defined]
        timings=ChatTimingsOut(
            nlu_ms=raw.get("nlu_ms", 0.0),
            decision_ms=raw.get("decision_ms", 0.0),
            sql_ms=raw.get("sql_ms", 0.0),
            vector_ms=raw.get("vector_ms", 0.0),
            llm_ms=raw.get("llm_ms", 0.0),
            fast_path_ms=raw.get("fast_path_ms", 0.0),
            total_ms=raw.get("total_ms", 0.0),
        ),
        meta=result.meta,  # type: ignore[attr-defined]
    )


def _fallback_out() -> ChatMessageOut:
    return ChatMessageOut(
        response=(
            "I want to make sure I help with the right thing. Could you rephrase "
            "your question, or ask about appointments, doctors, clinic hours, "
            "insurance, services, or clinic policies?"
        ),
        route="clarify",
        intent="unknown",
        confidence=0.0,
        needs_sql=False,
        needs_vector=False,
        needs_llm=False,
        safety_message=None,
        timings=ChatTimingsOut(),
        meta={
            "degraded": True,
            "degraded_reason": "chat_engine_exception",
            "lane": "clarify",
        },
    )
