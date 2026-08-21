"""Anonymous -> identified linking (ROADMAP.md's persistent-chat-history
phase, Step 3). Two independent call sites resolve a Patient onto a
ChatSession — otp_service.verify_otp and booking/service.py's confirm() —
and both call the one shared apps.chatbot.services.visitor_service helper,
so this file tests that shared boundary from both call sites rather than
duplicating the same assertions per site.

Also covers the booking dedup regression: confirm() used to do its own raw
Patient.objects.get_or_create keyed on whatever phone format the wizard's
own form collected, which a comment in that file already flagged as able
to create a second Patient row for an existing SMS-verified person."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.appointments.models import Appointment
from apps.chatbot.booking.service import BookingService
from apps.chatbot.models import (
    ChatMessage,
    ChatSession,
    ChatSessionStatus,
    ChatVisitor,
    MessageRole,
    MessageType,
)
from apps.chatbot.services.otp_service import send_otp, verify_otp
from apps.chatbot.services.visitor_service import (
    link_session_visitor_to_patient,
    link_visitor_to_patient,
)
from apps.clinics.models import Clinic
from apps.doctors.models import Doctor, DoctorSchedule
from apps.patients.models import Patient
from apps.patients.services import patient_service
from apps.widget.models import WidgetSettings

_TZ = ZoneInfo("America/New_York")


def _next_weekday(weekday: int, *, from_days_ahead: int = 0):
    d = timezone.localdate() + timedelta(days=from_days_ahead)
    while d.weekday() != weekday:
        d += timedelta(days=1)
    return d


class VisitorServiceUnitTests(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="visitor-service-clinic", name="Visitor Service Clinic",
            email="visitor-service@clinic.com", phone="+12125550210",
            timezone="America/New_York",
        )
        self.patient = Patient.objects.create(
            clinic=self.clinic, phone="+15550002222", first_name="Pat", last_name="One",
        )
        self.other_patient = Patient.objects.create(
            clinic=self.clinic, phone="+15550003333", first_name="Pat", last_name="Two",
        )

    def test_links_an_unlinked_visitor(self):
        visitor = ChatVisitor.objects.create(clinic=self.clinic, visitor_key="v-unlinked")
        linked = link_visitor_to_patient(visitor, self.patient)
        self.assertTrue(linked)
        visitor.refresh_from_db()
        self.assertEqual(visitor.patient_id, self.patient.id)

    def test_does_not_reassign_an_already_linked_visitor_to_a_different_patient(self):
        visitor = ChatVisitor.objects.create(
            clinic=self.clinic, visitor_key="v-already-linked", patient=self.patient,
        )
        linked = link_visitor_to_patient(visitor, self.other_patient)
        self.assertFalse(linked)
        visitor.refresh_from_db()
        self.assertEqual(visitor.patient_id, self.patient.id)

    def test_none_visitor_is_a_safe_no_op(self):
        self.assertFalse(link_visitor_to_patient(None, self.patient))

    def test_session_with_no_visitor_is_a_safe_no_op(self):
        legacy = ChatSession.objects.create(
            clinic=self.clinic, session_token="tok-vs-legacy", status=ChatSessionStatus.ACTIVE,
        )
        self.assertFalse(link_session_visitor_to_patient(legacy, self.patient))


class OTPVerificationLinksVisitorTests(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="otp-link-clinic", name="OTP Link Clinic",
            email="otp-link@clinic.com", phone="+12125550220",
            timezone="America/New_York",
        )
        self.visitor = ChatVisitor.objects.create(clinic=self.clinic, visitor_key="otp-link-visitor")
        self.patient = Patient.objects.create(
            clinic=self.clinic, phone="+15550004444", email="otp-link@example.com",
            first_name="Ari", last_name="Anon",
        )

    @override_settings(DEBUG=True)
    def test_otp_verification_links_visitor_to_patient(self):
        session = ChatSession.objects.create(
            clinic=self.clinic, visitor=self.visitor, session_token="tok-otp-link",
            status=ChatSessionStatus.ACTIVE,
        )
        sent = send_otp(
            clinic=self.clinic, email=self.patient.email, channel="email",
            session_token=session.session_token, require_existing_patient=True,
        )
        verify_otp(
            clinic=self.clinic, email=self.patient.email, code=sent.debug_code,
            session_token=session.session_token,
        )
        self.visitor.refresh_from_db()
        self.assertEqual(self.visitor.patient_id, self.patient.id)

    @override_settings(DEBUG=True)
    def test_all_prior_sessions_for_the_visitor_get_backfilled_without_recreating_them(self):
        """The important part isn't just the session that got OTP-verified
        — every ChatSession the visitor already owns, with ids, tokens and
        messages all untouched."""
        older = ChatSession.objects.create(
            clinic=self.clinic, visitor=self.visitor, session_token="tok-otp-older",
            status=ChatSessionStatus.CLOSED,
        )
        current = ChatSession.objects.create(
            clinic=self.clinic, visitor=self.visitor, session_token="tok-otp-current",
            status=ChatSessionStatus.ACTIVE,
        )
        ChatMessage.objects.create(
            clinic=self.clinic, session=older, role=MessageRole.USER,
            message_type=MessageType.TEXT, content="an old anonymous message",
            sequence_number=1, metadata={},
        )
        older_id, older_token = older.id, older.session_token

        sent = send_otp(
            clinic=self.clinic, email=self.patient.email, channel="email",
            session_token=current.session_token, require_existing_patient=True,
        )
        verify_otp(
            clinic=self.clinic, email=self.patient.email, code=sent.debug_code,
            session_token=current.session_token,
        )

        older.refresh_from_db()
        current.refresh_from_db()
        self.assertEqual(older.patient_id, self.patient.id)
        self.assertEqual(current.patient_id, self.patient.id)
        # Conversation identity is never recreated or copied.
        self.assertEqual(older.id, older_id)
        self.assertEqual(older.session_token, older_token)
        self.assertEqual(ChatMessage.objects.filter(session=older).count(), 1)
        self.assertEqual(
            ChatMessage.objects.get(session=older).content, "an old anonymous message"
        )
        # `older` was never itself OTP-verified — only `current` was —
        # so is_authenticated must reflect that per-session fact, not get
        # blanket-flipped just because the visitor is now identified.
        self.assertFalse(older.is_authenticated)
        self.assertTrue(current.is_authenticated)

    @override_settings(DEBUG=True)
    def test_session_with_no_visitor_still_authenticates_normally(self):
        """Legacy (pre-Step-1) sessions have visitor=NULL — OTP verification
        must keep working exactly as before; the new linking call is a
        no-op, not a new failure mode."""
        session = ChatSession.objects.create(
            clinic=self.clinic, session_token="tok-otp-no-visitor", status=ChatSessionStatus.ACTIVE,
        )
        sent = send_otp(
            clinic=self.clinic, email=self.patient.email, channel="email",
            session_token=session.session_token, require_existing_patient=True,
        )
        verify_otp(
            clinic=self.clinic, email=self.patient.email, code=sent.debug_code,
            session_token=session.session_token,
        )
        session.refresh_from_db()
        self.assertTrue(session.is_authenticated)
        self.assertEqual(session.patient_id, self.patient.id)


class BookingConfirmLinksVisitorTests(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="booking-link-clinic", name="Booking Link Clinic",
            email="booking-link@clinic.com", phone="+12125550230",
            timezone="America/New_York",
        )
        WidgetSettings.objects.create(
            clinic=self.clinic, configuration={"booking": {"verification_mode": "none"}},
        )
        self.doctor = Doctor.objects.create(clinic=self.clinic, full_name="Dr. Link")
        self.target_date = _next_weekday(timezone.localdate().weekday(), from_days_ahead=1)
        DoctorSchedule.objects.create(
            clinic=self.clinic, doctor=self.doctor,
            day_of_week=self.target_date.weekday(),
            start_time=time(9, 0), end_time=time(11, 0), slot_duration_min=30,
        )
        self.visitor = ChatVisitor.objects.create(clinic=self.clinic, visitor_key="booking-link-visitor")
        self.chat_session = ChatSession.objects.create(
            clinic=self.clinic, visitor=self.visitor, session_token="tok-booking-link",
            status=ChatSessionStatus.ACTIVE, is_authenticated=False,
        )
        start = datetime(
            self.target_date.year, self.target_date.month, self.target_date.day, 9, 0, tzinfo=_TZ,
        )
        end = start + timedelta(minutes=30)
        self.slot_start = start.isoformat()
        self.slot_end = end.isoformat()

    def _book(self, *, first_name="Sam", phone="", email=""):
        started = BookingService.start(
            clinic=self.clinic, chat_session=self.chat_session,
            doctor_id=str(self.doctor.id), doctor_name=self.doctor.full_name,
            slot_start=self.slot_start, slot_end=self.slot_end,
        )
        details = {"first_name": first_name}
        if phone:
            details["phone"] = phone
        if email:
            details["email"] = email
        BookingService.apply_step(
            clinic=self.clinic, chat_session=self.chat_session,
            booking_id=started["booking_id"], action="submit_details", value=details,
        )
        return BookingService.apply_step(
            clinic=self.clinic, chat_session=self.chat_session,
            booking_id=started["booking_id"], action="confirm_review", value={},
        )

    def test_booking_confirm_links_visitor_to_the_resolved_patient(self):
        self._book(phone="+15559990000", email="booking-link@example.com")
        self.visitor.refresh_from_db()
        patient = Patient.objects.get(clinic=self.clinic, phone="+15559990000")
        self.assertEqual(self.visitor.patient_id, patient.id)
        self.assertFalse(patient.is_verified)

    def test_booking_confirm_reuses_existing_patient_by_phone_instead_of_duplicating(self):
        """Regression for the pre-existing dedup bug: differently-typed
        phone input for an existing patient must resolve to that same
        Patient row, not silently create a second one."""
        existing = Patient.objects.create(
            clinic=self.clinic, phone="+15559990000", first_name="Sam", last_name="Original",
            is_verified=True,
        )
        self._book(first_name="Sam", phone="+15559990000")
        self.assertEqual(Patient.objects.filter(clinic=self.clinic, phone="+15559990000").count(), 1)
        appt = Appointment.objects.get(clinic=self.clinic)
        self.assertEqual(appt.patient_id, existing.id)
        self.visitor.refresh_from_db()
        self.assertEqual(self.visitor.patient_id, existing.id)

    def test_booking_confirm_reuses_existing_patient_by_email(self):
        existing = Patient.objects.create(
            clinic=self.clinic,
            phone=patient_service.email_placeholder_phone("booking-link@example.com"),
            email="booking-link@example.com", first_name="Sam", last_name="Original",
        )
        self._book(first_name="Sam", email="booking-link@example.com")
        self.assertEqual(
            Patient.objects.filter(clinic=self.clinic, email="booking-link@example.com").count(), 1
        )
        appt = Appointment.objects.get(clinic=self.clinic)
        self.assertEqual(appt.patient_id, existing.id)

    def test_session_with_no_visitor_still_books_normally(self):
        """Legacy (pre-Step-1) chat sessions have visitor=NULL — booking
        confirm() must keep working exactly as before."""
        self.chat_session.visitor = None
        self.chat_session.save(update_fields=["visitor"])
        result = self._book(phone="+15559991111")
        self.assertTrue(Appointment.objects.filter(clinic=self.clinic).exists())
        self.assertEqual(result["step"], "confirmed")
