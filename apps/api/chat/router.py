"""
Chat endpoint — the primary patient-facing message API.

POST /api/v1/chat/message
  - Accepts patient JWT (widget) or staff JWT (for testing).
  - Patient JWT: resolves patient + session from token.
  - Staff JWT:   clinic-scoped, no patient; good for testing via Swagger.
"""

from __future__ import annotations

import logging

from ninja import Router
from ninja.errors import HttpError

from apps.api.auth.deps import PatientJWTAuth, StaffJWTAuth
from apps.api.chat.schemas import ChatMessageIn, ChatMessageOut, ChatTimingsOut

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
        raise HttpError(500, "Failed to process message") from exc

    return _to_out(result)


# ── Staff/debug endpoint (portal + Swagger testing) ──────────────────────────

@router.post("/message/staff", response=ChatMessageOut, auth=_staff_auth)
def staff_chat_message(request, payload: ChatMessageIn) -> ChatMessageOut:
    """
    Process a message in the context of the staff's clinic.

    Auth: staff_access JWT. No patient context. Useful for QA and Swagger.
    """
    clinic = getattr(request.auth, "clinic", None)
    if clinic is None:
        raise HttpError(400, "Clinic context required — include clinic_id in your JWT")

    message = (payload.message or "").strip()
    if not message:
        raise HttpError(422, "Message is required")
    if len(message) > 2000:
        raise HttpError(422, "Message too long (max 2000 characters)")

    from apps.chatbot.engine import ChatEngine
    try:
        result = ChatEngine().process(
            clinic=clinic,
            message=message,
            session=None,
            patient=None,
        )
    except Exception as exc:
        logger.exception("ChatEngine (staff) failed for clinic=%s", clinic.id)
        raise HttpError(500, "Failed to process message") from exc

    return _to_out(result)


# ── Helpers ───────────────────────────────────────────────────────────────────

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
