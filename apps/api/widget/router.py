"""Public widget endpoints — tenant config and guest chat (no patient JWT)."""

from __future__ import annotations

import logging
import secrets

from django.utils import timezone
from ninja import Router, Schema
from ninja.errors import HttpError

from apps.api.auth.deps import client_ip, resolve_public_clinic
from apps.api.chat.router import _fallback_out, _to_out
from apps.api.chat.schemas import ChatMessageOut, ChatTimingsOut
from apps.chatbot.engine import ChatEngine
from apps.chatbot.marketing_engine import MarketingEngine
from apps.chatbot.sql_tool.utils import clinic_timezone, format_clinic_when
from apps.clinics.models import Clinic
from apps.widget.models import WidgetSettings
from core.ratelimit import check_rate_limit

logger = logging.getLogger(__name__)

router = Router(tags=["Widget"])

# Persistent chat history (ROADMAP.md Phase 29+) — visitor_id always travels
# in this header, never a body/query param (see the plan: keeps it out of
# request-body logs, and it's a bearer identifier, not an authorization
# token, so it doesn't belong in a URL either).
_VISITOR_HEADER = "X-Synapse-Visitor-Id"
_DEFAULT_PAGE_SIZE = 50
_MAX_PAGE_SIZE = 100
_RESUME_MAX_PER_IP, _RESUME_IP_WINDOW_S = 30, 300
_MESSAGES_MAX_PER_IP, _MESSAGES_IP_WINDOW_S = 120, 300
_CONTACT_MAX_PER_IP, _CONTACT_IP_WINDOW_S = 10, 600


class WidgetConfigOut(Schema):
    clinic_slug: str
    clinic_name: str
    phone: str
    timezone: str
    configuration: dict


class WidgetChatIn(Schema):
    clinic_slug: str
    message: str
    session_token: str | None = None


class MarketingChatIn(Schema):
    message: str


class ChatMessageHistoryOut(Schema):
    id: str
    role: str
    message_type: str
    content: str
    metadata: dict
    sequence_number: int
    created_at: str


class ChatResumeOut(Schema):
    session_token: str | None
    visitor_id: str | None
    has_history: bool
    messages: list[ChatMessageHistoryOut]
    has_more: bool
    # Phase 42A — an in-progress booking (not yet CONFIRMED) on this
    # session, if any. Historical booking_wizard messages in `messages`
    # are always inert (see hydrateHistoryRow) — this is the separate,
    # live signal the frontend uses to remount an interrupted wizard at
    # its real step instead of losing it.
    active_booking: dict | None = None


class ChatMessagesPageOut(Schema):
    messages: list[ChatMessageHistoryOut]
    has_more: bool


class ChatContactIn(Schema):
    clinic_slug: str
    email: str | None = None
    phone: str | None = None


class ChatContactOut(Schema):
    linked: bool
    patient_verified: bool


class SpecialtySearchIn(Schema):
    clinic_slug: str
    specialty_id: str


class ClinicOnlyActionIn(Schema):
    clinic_slug: str


class AppointmentActionIn(Schema):
    clinic_slug: str
    session_token: str
    appointment_id: str


class AppointmentsListIn(Schema):
    clinic_slug: str
    session_token: str


class AppointmentCardOut(Schema):
    id: str
    doctor: str
    doctor_id: str | None = None
    service: str = ""
    start_time: str
    end_time: str = ""
    when: str = ""
    status: str = ""
    confirmation_code: str = ""


class AppointmentsListOut(Schema):
    appointments: list[AppointmentCardOut]


class AppointmentCancelOut(Schema):
    detail: str
    appointment_id: str


class AppointmentRescheduleOut(Schema):
    detail: str
    appointment_id: str
    doctor_id: str
    doctor_name: str
    service_id: str | None = None
    service_name: str | None = None
    start_time: str
    end_time: str
    when: str = ""


@router.get("/config", response=WidgetConfigOut, auth=None)
def widget_config(request, clinic_slug: str):
    """Public widget configuration for tenant detection and branding."""
    from apps.clinics.features import (
        default_widget_configuration,
        get_feature_flags,
        get_verification_mode,
    )

    clinic = resolve_public_clinic(request, clinic_slug)
    settings = WidgetSettings.objects.filter(clinic=clinic).first()
    configuration = (
        dict(settings.configuration)
        if settings and isinstance(settings.configuration, dict)
        else default_widget_configuration()
    )
    booking = dict(configuration.get("booking") or {})
    booking["verification_mode"] = get_verification_mode(clinic)
    booking["require_auth"] = booking["verification_mode"] != "none"
    configuration["booking"] = booking
    configuration["feature_flags"] = get_feature_flags(clinic)
    return WidgetConfigOut(
        clinic_slug=clinic.slug,
        clinic_name=clinic.name,
        phone=clinic.phone or "",
        timezone=clinic.timezone or "UTC",
        configuration=configuration,
    )


class EmbedPolicyOut(Schema):
    allowed_origins: list[str] = []


@router.get("/embed-policy", response=EmbedPolicyOut, auth=None)
def widget_embed_policy(request, clinic_slug: str):
    """Server-to-server only — consumed by the Next.js embed route's Edge
    Middleware to build the `Content-Security-Policy: frame-ancestors`
    header for /embed/{clinicSlug}. Deliberately separate from
    WidgetConfigOut (which the browser-side widget itself fetches for
    branding): this is per-clinic *security* configuration, and keeping it
    out of the response the public widget's own JS consumes is a cleaner
    separation of concerns, even though a registered domain isn't a secret.

    Not routed through resolve_public_clinic — that would enforce the very
    allowlist this endpoint exists to hand out, and would 403 the Edge
    Middleware's own server-to-server request (which carries no browser
    Origin header). An unknown clinic_slug returns an empty list rather than
    404 — the middleware treats "unknown clinic" and "no origins configured"
    identically (fail closed to `frame-ancestors 'self'`).
    """
    clinic = Clinic.objects.filter(slug=clinic_slug).first()
    return EmbedPolicyOut(allowed_origins=(clinic.allowed_origins or []) if clinic else [])


@router.get("/chat/resume", response=ChatResumeOut, auth=None)
def resume_chat(request, clinic_slug: str):
    """Resolve the calling browser's most recent conversation, if any.

    Pure read — never creates a `ChatVisitor` or a `ChatSession`. Opening
    the widget must not, by itself, write anything to the database; only
    the actual send-message path (`_resolve_guest_session`, below) creates
    either. A first-time visitor (no header) and a header that doesn't
    resolve to a real `ChatVisitor` for this clinic (garbage, or another
    clinic's key — tenant isolation fails closed, not open) are handled
    identically: `visitor_id=None`, `has_history=False`, nothing written.

    The initial page is always bounded (`_DEFAULT_PAGE_SIZE`), never the
    full conversation — the same cursor-pagination endpoint used for
    scrolling up loads everything before it. There is no separate
    "load everything" path anywhere in this system.
    """
    clinic = resolve_public_clinic(request, clinic_slug)
    check_rate_limit(
        "chat_resume_ip", client_ip(request) or "",
        limit=_RESUME_MAX_PER_IP, window_seconds=_RESUME_IP_WINDOW_S,
    )

    from apps.chatbot.models import ChatSession, ChatSessionStatus, ChatVisitor

    visitor_key = (request.headers.get(_VISITOR_HEADER) or "").strip() or None
    visitor = (
        ChatVisitor.objects.filter(clinic=clinic, visitor_key=visitor_key).first()
        if visitor_key
        else None
    )
    if visitor is None:
        return ChatResumeOut(
            session_token=None, visitor_id=None, has_history=False, messages=[], has_more=False,
        )

    session = (
        ChatSession.objects.filter(
            clinic=clinic, visitor=visitor, status=ChatSessionStatus.ACTIVE,
        )
        .order_by("-last_active_at")
        .first()
    )
    if session is None:
        return ChatResumeOut(
            session_token=None,
            visitor_id=visitor.visitor_key,
            has_history=False,
            messages=[],
            has_more=False,
        )

    rows, has_more = _message_page(session, before=None, limit=_DEFAULT_PAGE_SIZE)
    from apps.chatbot.booking.service import BookingService

    return ChatResumeOut(
        session_token=session.session_token,
        visitor_id=visitor.visitor_key,
        has_history=bool(rows),
        messages=_serialize_messages(rows),
        has_more=has_more,
        active_booking=BookingService.active_booking_payload(clinic, session),
    )


@router.get(
    "/chat/sessions/{session_token}/messages", response=ChatMessagesPageOut, auth=None
)
def chat_messages_page(
    request,
    session_token: str,
    clinic_slug: str,
    before: int | None = None,
    limit: int = _DEFAULT_PAGE_SIZE,
):
    """Cursor-paginated older messages for one conversation, newest-first
    boundary semantics (`before=<sequence_number>`, strictly older than
    that cursor) — never offset-based, so concurrent inserts elsewhere in
    the same session can't shift a page's contents underneath a scrolling
    reader (see ROADMAP.md's persistent-chat-history phase for why)."""
    clinic = resolve_public_clinic(request, clinic_slug)
    check_rate_limit(
        "chat_messages_ip", client_ip(request) or "",
        limit=_MESSAGES_MAX_PER_IP, window_seconds=_MESSAGES_IP_WINDOW_S,
    )

    from apps.chatbot.models import ChatSession

    try:
        session = ChatSession.objects.select_related("visitor").get(
            clinic=clinic, session_token=session_token,
        )
    except ChatSession.DoesNotExist:
        raise HttpError(404, "Session not found") from None

    if session.visitor_id is not None:
        # A session that already has a visitor attached requires proof of
        # ownership — a bare session_token is no longer enough on its own
        # for these (new) history rows, even though the rest of this app
        # still trusts session_token alone for older, pre-visitor sessions.
        # Same 404 either way — never confirm a session_token is real to a
        # caller who can't prove ownership of it.
        submitted = (request.headers.get(_VISITOR_HEADER) or "").strip()
        if not submitted or submitted != session.visitor.visitor_key:
            raise HttpError(404, "Session not found") from None

    if before is not None and before < 1:
        raise HttpError(422, "Invalid cursor")
    limit = max(1, min(int(limit or _DEFAULT_PAGE_SIZE), _MAX_PAGE_SIZE))

    rows, has_more = _message_page(session, before=before, limit=limit)
    return ChatMessagesPageOut(messages=_serialize_messages(rows), has_more=has_more)


@router.post("/chat/contact", response=ChatContactOut, auth=None)
def chat_contact(request, payload: ChatContactIn):
    """Lightweight, unverified contact capture — identification, not
    authentication (ROADMAP.md's persistent-chat-history phase, §5's hard
    rule). Never sets Patient.is_verified; that only happens through the
    existing OTP flow. Skip is simply never calling this endpoint — no
    server-side state to represent "skipped" is needed.
    """
    clinic = resolve_public_clinic(request, payload.clinic_slug)
    check_rate_limit(
        "chat_contact_ip", client_ip(request) or "",
        limit=_CONTACT_MAX_PER_IP, window_seconds=_CONTACT_IP_WINDOW_S,
    )

    visitor_key = (request.headers.get(_VISITOR_HEADER) or "").strip()
    if not visitor_key:
        raise HttpError(422, "Missing visitor identity")
    visitor, _created = _find_or_create_visitor(clinic, visitor_key)

    email = (payload.email or "").strip().lower()
    phone = (payload.phone or "").strip()
    if not email and not phone:
        raise HttpError(422, "Email or phone is required")

    if visitor.patient_id is not None:
        # Already linked — a casual, unverified submission must never
        # silently reassign an established identity onto a different
        # Patient row.
        patient = visitor.patient
    else:
        from apps.chatbot.services.visitor_service import link_visitor_to_patient
        from apps.patients.services import patient_service

        if phone:
            patient, _ = patient_service.get_or_create_by_phone(clinic=clinic, phone=phone)
            if email and not patient.email:
                patient.email = email
                patient.save(update_fields=["email", "updated_at"])
        else:
            patient, _ = patient_service.get_or_create_by_email(clinic=clinic, email=email)
        link_visitor_to_patient(visitor, patient)

    return ChatContactOut(linked=True, patient_verified=patient.is_verified)


@router.post("/chat/guest", response=ChatMessageOut, auth=None)
def guest_chat_message(request, payload: WidgetChatIn):
    """
    Anonymous patient chat — no OTP required for Q&A.

    OTP is only required when booking is confirmed (handled in booking wizard).
    """
    clinic = resolve_public_clinic(request, payload.clinic_slug)
    message = (payload.message or "").strip()
    if not message:
        raise HttpError(422, "Message is required")
    if len(message) > 2000:
        raise HttpError(422, "Message too long")

    visitor_key = (request.headers.get(_VISITOR_HEADER) or "").strip() or None
    visitor, _created = _find_or_create_visitor(clinic, visitor_key)

    session = _resolve_guest_session(clinic, payload.session_token, visitor)
    patient = session.patient if session.is_authenticated else None

    try:
        result = ChatEngine().process(
            clinic=clinic,
            message=message,
            session=session,
            patient=patient,
        )
    except Exception as exc:
        logger.exception("Guest chat failed clinic=%s", clinic.id)
        out = _fallback_out()
        out.meta = {**out.meta, "session_token": session.session_token, "visitor_id": visitor.visitor_key}
        return out

    out = _to_out(result)
    out.meta = {**out.meta, "session_token": session.session_token, "visitor_id": visitor.visitor_key}
    return out


@router.post("/specialty/search", response=ChatMessageOut, auth=None)
def specialty_search(request, payload: SpecialtySearchIn):
    """Doctors for a specialty the patient picked from a UI card.

    Deliberately bypasses ChatEngine/NLU entirely — the frontend already
    knows exactly which specialty was selected (see ui_actions.py's
    docstring), so there is no language to understand, only a database
    lookup to run. Same ChatMessageOut response shape as /chat/guest so
    the widget renders the result (doctor cards, or an honest no-match
    message) through its existing response handling, unchanged.
    """
    from apps.chatbot.ui_actions import search_doctors_for_specialty

    clinic = resolve_public_clinic(request, payload.clinic_slug)
    result = search_doctors_for_specialty(clinic, payload.specialty_id)
    return ChatMessageOut(
        response=result["response"],
        route="ui_action",
        intent="doctor_search",
        confidence=1.0,
        needs_sql=True,
        needs_vector=False,
        needs_llm=False,
        timings=ChatTimingsOut(),
        meta=result["meta"],
    )


@router.post("/doctors/browse", response=ChatMessageOut, auth=None)
def doctors_browse(request, payload: ClinicOnlyActionIn):
    """"Find a Doctor" main-menu button — frontend-authored label, not
    user language, so it bypasses ChatEngine/NLU the same way specialty
    cards do (see ui_actions.browse_doctors)."""
    from apps.chatbot.ui_actions import browse_doctors

    clinic = resolve_public_clinic(request, payload.clinic_slug)
    result = browse_doctors(clinic)
    return ChatMessageOut(
        response=result["response"],
        route="ui_action",
        intent="doctor_search",
        confidence=1.0,
        needs_sql=True,
        needs_vector=False,
        needs_llm=False,
        timings=ChatTimingsOut(),
        meta=result["meta"],
    )


@router.post("/clinic/hours", response=ChatMessageOut, auth=None)
def clinic_hours_action(request, payload: ClinicOnlyActionIn):
    """"Clinic Hours" main-menu button — same rationale as doctors_browse."""
    from apps.chatbot.ui_actions import clinic_hours_info

    clinic = resolve_public_clinic(request, payload.clinic_slug)
    result = clinic_hours_info(clinic)
    return ChatMessageOut(
        response=result["response"],
        route="ui_action",
        intent="clinic_hours",
        confidence=1.0,
        needs_sql=True,
        needs_vector=False,
        needs_llm=False,
        timings=ChatTimingsOut(),
        meta=result["meta"],
    )


@router.post("/appointments/cancel", response=AppointmentCancelOut, auth=None)
def cancel_appointment(request, payload: AppointmentActionIn):
    """Cancel a patient's own appointment — requires an OTP-verified session."""
    from apps.appointments.models import Appointment, AppointmentStatus

    clinic = resolve_public_clinic(request, payload.clinic_slug)
    session = _resolve_authenticated_session(clinic, payload.session_token)
    try:
        appt = Appointment.objects.get(
            id=payload.appointment_id, clinic=clinic, patient=session.patient
        )
    except (Appointment.DoesNotExist, ValueError):
        raise HttpError(404, "Appointment not found") from None

    appt.status = AppointmentStatus.CANCELLED
    appt.save(update_fields=["status", "updated_at"])
    return AppointmentCancelOut(detail="Appointment cancelled", appointment_id=str(appt.id))


@router.post("/appointments/reschedule", response=AppointmentRescheduleOut, auth=None)
def reschedule_appointment(request, payload: AppointmentActionIn):
    """
    Fetch reschedule context for a patient's own appointment — does NOT
    cancel it. The appointment stays live (and bookable as a fallback) for
    the entire time the patient is picking a new slot in the booking wizard;
    it's only cancelled atomically alongside the new appointment's creation,
    in BookingService.confirm (see `replaces_appointment_id`).
    """
    from apps.appointments.models import Appointment, AppointmentStatus

    clinic = resolve_public_clinic(request, payload.clinic_slug)
    session = _resolve_authenticated_session(clinic, payload.session_token)
    try:
        appt = Appointment.objects.select_related("doctor", "service").get(
            id=payload.appointment_id,
            clinic=clinic,
            patient=session.patient,
            status__in=[AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED],
        )
    except (Appointment.DoesNotExist, ValueError):
        raise HttpError(404, "Appointment not found") from None

    return AppointmentRescheduleOut(
        detail="ok",
        appointment_id=str(appt.id),
        doctor_id=str(appt.doctor_id),
        doctor_name=appt.doctor.full_name,
        service_id=str(appt.service_id) if appt.service_id else None,
        service_name=appt.service.name if appt.service else None,
        start_time=appt.start_time.isoformat(),
        end_time=appt.end_time.isoformat(),
        when=format_clinic_when(appt.start_time, clinic_timezone(clinic)),
    )


@router.post("/appointments/list", response=AppointmentsListOut, auth=None)
def list_appointments(request, payload: AppointmentsListIn):
    """
    A patient's own upcoming appointments for an OTP-verified session.

    Used right after identity verification to render appointment cards as a
    direct state transition — not a new chat turn, no re-classification.
    """
    from apps.appointments.models import Appointment, AppointmentStatus

    clinic = resolve_public_clinic(request, payload.clinic_slug)
    session = _resolve_authenticated_session(clinic, payload.session_token)

    upcoming = (
        Appointment.objects.filter(
            clinic=clinic,
            patient=session.patient,
            start_time__gte=timezone.now(),
            status__in=[AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED],
        )
        .select_related("doctor", "service")
        .order_by("start_time")[:10]
    )

    tz = clinic_timezone(clinic)
    return AppointmentsListOut(
        appointments=[
            AppointmentCardOut(
                id=str(a.id),
                doctor=a.doctor.full_name,
                doctor_id=str(a.doctor_id),
                service=a.service.name if a.service else "",
                start_time=a.start_time.isoformat(),
                end_time=a.end_time.isoformat(),
                when=format_clinic_when(a.start_time, tz),
                status=a.status,
                confirmation_code=a.confirmation_code,
            )
            for a in upcoming
        ]
    )


@router.post("/chat/marketing", response=ChatMessageOut, auth=None)
def marketing_chat_message(request, payload: MarketingChatIn):
    """Synapse marketing assistant — never exposes clinic tenant data."""
    message = (payload.message or "").strip()
    if not message:
        raise HttpError(422, "Message is required")

    result = MarketingEngine().process(message=message)
    return _to_out(result)


def _find_or_create_visitor(clinic: Clinic, visitor_key: str | None):
    """Resolve the calling browser's `ChatVisitor`, tenant-scoped.

    A submitted key that doesn't belong to *this* clinic — missing,
    garbage, or (deliberately) belonging to a different clinic entirely —
    is never trusted as-is; a fresh visitor is minted instead of either
    erroring or silently resolving to another tenant's identity.
    `visitor_key` is globally unique (not merely unique per clinic — see
    ROADMAP.md's persistent-chat-history phase for why), so `filter(clinic
    =clinic, visitor_key=visitor_key)` returning nothing is exactly the
    signal that the key belongs elsewhere or doesn't exist at all; both
    cases are handled identically.
    """
    from django.db import IntegrityError, transaction

    from apps.chatbot.models import ChatVisitor

    if visitor_key:
        visitor = ChatVisitor.objects.filter(
            clinic=clinic, visitor_key=visitor_key
        ).first()
        if visitor is not None:
            return visitor, False

    # secrets.token_urlsafe(32) collisions are astronomically unlikely
    # (256 bits); the retry loop exists purely so a freak collision never
    # surfaces as a 500 rather than because it's expected to fire.
    for _ in range(3):
        new_key = secrets.token_urlsafe(32)
        try:
            with transaction.atomic():
                return ChatVisitor.objects.create(clinic=clinic, visitor_key=new_key), True
        except IntegrityError:
            continue
    raise HttpError(500, "Could not allocate a visitor identity")


def _message_page(session, *, before: int | None, limit: int):
    from apps.chatbot.services.message_history import paginate_messages

    return paginate_messages(session, before=before, limit=limit)


def _serialize_messages(rows) -> list[ChatMessageHistoryOut]:
    return [
        ChatMessageHistoryOut(
            id=str(m.id),
            role=m.role,
            message_type=m.message_type,
            content=m.content,
            metadata=m.metadata or {},
            sequence_number=m.sequence_number,
            created_at=m.created_at.isoformat(),
        )
        for m in rows
    ]


def _resolve_guest_session(clinic: Clinic, session_token: str | None, visitor=None):
    """Find-or-create the ChatSession for a guest message and (Phase 29
    Step 3) make sure it carries the calling browser's ChatVisitor, so
    /chat/resume can find it afterwards. `visitor` is None only for the
    (should no longer happen from guest_chat_message, but kept safe for
    any other caller) case of no visitor identity at all — those sessions
    behave exactly as they did before the visitor concept existed.
    """
    from apps.chatbot.models import ChatSession, ChatSessionStatus

    if session_token:
        try:
            session = ChatSession.objects.get(
                clinic=clinic,
                session_token=session_token,
                status=ChatSessionStatus.ACTIVE,
            )
        except ChatSession.DoesNotExist:
            session = None
        if session is not None:
            if visitor is not None and session.visitor_id is None:
                # Adopts a legacy (pre-visitor) session into the visitor
                # concept the moment its own browser sends another message
                # — never reassigns a session that already belongs to a
                # (possibly different) visitor.
                session.visitor = visitor
                session.save(update_fields=["visitor"])
            return session

    if visitor is not None:
        # A returning visitor without a usable session_token (e.g. the
        # widget reloaded before the first reply/session_token came back)
        # resumes its own most recent active session instead of forking a
        # second conversation.
        existing = (
            ChatSession.objects.filter(
                clinic=clinic, visitor=visitor, status=ChatSessionStatus.ACTIVE,
            )
            .order_by("-last_active_at")
            .first()
        )
        if existing is not None:
            return existing

    token = secrets.token_urlsafe(32)
    return ChatSession.objects.create(
        clinic=clinic,
        visitor=visitor,
        session_token=token,
        ip_hash="",
        user_agent="",
        is_authenticated=False,
        status=ChatSessionStatus.ACTIVE,
        last_active_at=timezone.now(),
    )


def _resolve_authenticated_session(clinic: Clinic, session_token: str):
    """A chat session that has already completed OTP verification
    (apps/api/auth/patient_router.py's /otp/verify sets session.patient +
    is_authenticated when given this same session_token)."""
    from apps.chatbot.models import ChatSession, ChatSessionStatus

    try:
        session = ChatSession.objects.get(
            clinic=clinic,
            session_token=session_token,
            status=ChatSessionStatus.ACTIVE,
        )
    except ChatSession.DoesNotExist:
        raise HttpError(404, "Session not found") from None
    if not session.is_authenticated or session.patient_id is None:
        raise HttpError(401, "Verification required")
    return session
