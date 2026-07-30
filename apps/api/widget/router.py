"""Public widget endpoints — tenant config and guest chat (no patient JWT)."""

from __future__ import annotations

import logging
import secrets

from django.utils import timezone
from ninja import Router, Schema
from ninja.errors import HttpError

from apps.api.chat.router import _to_out
from apps.api.chat.schemas import ChatMessageOut
from apps.chatbot.engine import ChatEngine
from apps.chatbot.marketing_engine import MarketingEngine
from apps.clinics.models import Clinic, ClinicStatus
from apps.widget.models import WidgetSettings

logger = logging.getLogger(__name__)

router = Router(tags=["Widget"])


class WidgetConfigOut(Schema):
    clinic_slug: str
    clinic_name: str
    phone: str
    configuration: dict


class WidgetChatIn(Schema):
    clinic_slug: str
    message: str
    session_token: str | None = None


class MarketingChatIn(Schema):
    message: str


def _resolve_clinic(slug: str) -> Clinic:
    try:
        clinic = Clinic.objects.get(slug=slug)
    except Clinic.DoesNotExist:
        raise HttpError(404, "Clinic not found") from None
    if clinic.status == ClinicStatus.SUSPENDED:
        raise HttpError(403, "Clinic is suspended")
    return clinic


@router.get("/config", response=WidgetConfigOut, auth=None)
def widget_config(request, clinic_slug: str):
    """Public widget configuration for tenant detection and branding."""
    clinic = _resolve_clinic(clinic_slug)
    settings = WidgetSettings.objects.filter(clinic=clinic).first()
    configuration = settings.configuration if settings else {}
    return WidgetConfigOut(
        clinic_slug=clinic.slug,
        clinic_name=clinic.name,
        phone=clinic.phone or "",
        configuration=configuration,
    )


@router.post("/chat/guest", response=ChatMessageOut, auth=None)
def guest_chat_message(request, payload: WidgetChatIn):
    """
    Anonymous patient chat — no OTP required for Q&A.

    OTP is only required when booking is confirmed (handled in booking wizard).
    """
    clinic = _resolve_clinic(payload.clinic_slug)
    message = (payload.message or "").strip()
    if not message:
        raise HttpError(422, "Message is required")
    if len(message) > 2000:
        raise HttpError(422, "Message too long")

    session = _resolve_guest_session(clinic, payload.session_token)

    try:
        result = ChatEngine().process(
            clinic=clinic,
            message=message,
            session=session,
            patient=None,
        )
    except Exception as exc:
        logger.exception("Guest chat failed clinic=%s", clinic.id)
        raise HttpError(500, "Failed to process message") from exc

    out = _to_out(result)
    out.meta = {**out.meta, "session_token": session.session_token}
    return out


@router.post("/chat/marketing", response=ChatMessageOut, auth=None)
def marketing_chat_message(request, payload: MarketingChatIn):
    """Synapse marketing assistant — never exposes clinic tenant data."""
    message = (payload.message or "").strip()
    if not message:
        raise HttpError(422, "Message is required")

    result = MarketingEngine().process(message=message)
    return _to_out(result)


def _resolve_guest_session(clinic: Clinic, session_token: str | None):
    from apps.chatbot.models import ChatSession, ChatSessionStatus

    if session_token:
        try:
            return ChatSession.objects.get(
                clinic=clinic,
                session_token=session_token,
                status=ChatSessionStatus.ACTIVE,
            )
        except ChatSession.DoesNotExist:
            pass

    token = secrets.token_urlsafe(32)
    return ChatSession.objects.create(
        clinic=clinic,
        session_token=token,
        ip_hash="",
        user_agent="",
        is_authenticated=False,
        status=ChatSessionStatus.ACTIVE,
        last_active_at=timezone.now(),
    )
