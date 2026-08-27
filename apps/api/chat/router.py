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
    StaffChatResumeOut,
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

    session = _resolve_staff_test_session(clinic, payload.session_token, request.auth.user)

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


@router.get("/message/staff/resume", response=StaffChatResumeOut, auth=_staff_auth)
def resume_staff_chat(request):
    """Resolve *this staff user's* most recent QA session in *this* clinic.

    Pure read, mirrors the public widget's /chat/resume (apps/api/widget/
    router.py) — same reasoning applies: opening the dashboard's chat
    widget must not itself create a ChatSession, only sending a real
    message does (staff_chat_message, above). Scoped by both clinic (from
    the staff JWT's tenant claim — the same clinic_from(request) every
    staff endpoint uses) and created_by_user (from that same JWT's user)
    so two staff members testing the same clinic never resume each
    other's conversation, and a super admin who has entered several
    clinics resumes a *different* conversation per clinic, never one
    bleeding into another.
    """
    from apps.chatbot.models import ChatSession
    from apps.chatbot.services.message_history import paginate_messages

    clinic = clinic_from(request)
    session = (
        ChatSession.objects.filter(
            clinic=clinic, created_by_user=request.auth.user, patient__isnull=True
        )
        .order_by("-last_active_at")
        .first()
    )
    if session is None:
        return StaffChatResumeOut(
            session_token=None, has_history=False, messages=[], has_more=False
        )

    rows, has_more = paginate_messages(session, before=None, limit=_MESSAGES_DEFAULT_LIMIT)
    return StaffChatResumeOut(
        session_token=session.session_token,
        has_history=bool(rows),
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
    from django.db.models import Count, IntegerField, OuterRef, Q, Subquery
    from django.db.models.functions import Coalesce

    from apps.chatbot.models import ChatMessage, ChatSession

    clinic = clinic_from(request)
    # message_count/last_message used to be one `.first()` and one
    # `.count()` query *per row* in _serialize_conversation below — up to
    # 200 extra queries for a 100-row page. Correlated subqueries fold both
    # into the single list query instead; each is still indexed the same
    # way paginate_messages already relies on (ChatMessage's unique
    # (session, sequence_number) index serves the "latest by session"
    # lookup, and (session, created_at) backs the per-session count).
    message_qs = ChatMessage.objects.filter(session=OuterRef("pk"))
    count_subquery = (
        message_qs.order_by().values("session").annotate(c=Count("id")).values("c")
    )
    latest_message = message_qs.order_by("-sequence_number")
    qs = (
        ChatSession.objects.filter(clinic=clinic)
        .select_related("patient", "visitor")
        .annotate(
            message_count_annotated=Coalesce(
                Subquery(count_subquery, output_field=IntegerField()), 0
            ),
            last_message_content=Subquery(latest_message.values("content")[:1]),
        )
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
    last_message_content = getattr(session, "last_message_content", None)
    return ConversationSummaryOut(
        id=str(session.id),  # type: ignore[attr-defined]
        session_token=session.session_token,  # type: ignore[attr-defined]
        display_name=display_name,
        phone=phone,
        is_authenticated=session.is_authenticated,  # type: ignore[attr-defined]
        status=session.status,  # type: ignore[attr-defined]
        message_count=getattr(session, "message_count_annotated", 0),
        last_message_preview=(last_message_content[:140] if last_message_content else None),
        last_active_at=session.last_active_at.isoformat(),  # type: ignore[attr-defined]
        created_at=session.created_at.isoformat(),  # type: ignore[attr-defined]
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _resolve_staff_test_session(
    clinic: object, session_token: str | None, user: object
) -> object:
    """Guest-style ChatSession for staff portal QA of patient flows.

    `created_by_user` is only ever set on creation, here — it's what lets
    /message/staff/resume find "this staff user's own most recent QA
    session in this clinic" without depending on the frontend to have
    remembered the right session_token itself.
    """
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
        created_by_user=user,
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
