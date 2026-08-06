"""BookingService.start() resumes an in-progress draft instead of always
creating a new BookingSession (the "booking restarts constantly" bug), and
supports slot-filling from free text ("Botox Friday after 5")."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.test import TestCase
from django.utils import timezone

from apps.chatbot.booking.service import BookingService
from apps.chatbot.booking.state import BookingStep
from apps.chatbot.models import ChatSession, ChatSessionStatus
from apps.clinics.models import Clinic
from apps.doctors.models import Doctor, DoctorSchedule, DoctorService, DoctorSpecialty
from apps.services.models import Service
from apps.specialties.models import Specialty


def _next_friday_matching_parse_natural_date(tz_name: str = "America/New_York"):
    """Mirrors sql_tool.utils.parse_natural_date's weekday resolution exactly,
    so the test's expected date always agrees with what start() computes."""
    today = timezone.now().astimezone(ZoneInfo(tz_name)).date()
    days_ahead = (4 - today.weekday()) % 7 or 7
    return today + timedelta(days=days_ahead)


class BookingResumeTests(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="resume-clinic",
            name="Resume Clinic",
            email="resume@clinic.com",
            phone="+12125550004",
            timezone="America/New_York",
        )
        self.chat_session = ChatSession.objects.create(
            clinic=self.clinic,
            session_token="tok-resume-1",
            status=ChatSessionStatus.ACTIVE,
        )
        self.doctor_a = Doctor.objects.create(clinic=self.clinic, full_name="Dr. A")
        self.doctor_b = Doctor.objects.create(clinic=self.clinic, full_name="Dr. B")

    def test_second_start_resumes_same_booking_id(self):
        first = BookingService.start(clinic=self.clinic, chat_session=self.chat_session)
        self.chat_session.refresh_from_db()
        second = BookingService.start(clinic=self.clinic, chat_session=self.chat_session)

        self.assertFalse(first["resumed"])
        self.assertTrue(second["resumed"])
        self.assertEqual(first["booking_id"], second["booking_id"])

    def test_correcting_doctor_updates_in_place_and_clears_date(self):
        first = BookingService.start(
            clinic=self.clinic,
            chat_session=self.chat_session,
            doctor_id=str(self.doctor_a.id),
        )
        self.chat_session.refresh_from_db()
        # Move to DATE step and pick a date, then "correct" the doctor.
        booking = self.chat_session.conversation_context["booking"]
        booking["date"] = timezone.localdate().isoformat()
        booking["slot_start"] = timezone.now().isoformat()
        booking["patient_first_name"] = "Jamie"
        self.chat_session.conversation_context["booking"] = booking
        self.chat_session.save(update_fields=["conversation_context"])

        second = BookingService.start(
            clinic=self.clinic,
            chat_session=self.chat_session,
            doctor_id=str(self.doctor_b.id),
        )

        self.assertEqual(first["booking_id"], second["booking_id"])
        self.chat_session.refresh_from_db()
        updated = self.chat_session.conversation_context["booking"]
        self.assertEqual(updated["doctor_id"], str(self.doctor_b.id))
        self.assertIsNone(updated["date"])
        self.assertIsNone(updated["slot_start"])
        # Patient-entered details are never erased by a doctor/specialty correction.
        self.assertEqual(updated["patient_first_name"], "Jamie")

    def test_start_after_confirmed_creates_fresh_booking(self):
        first = BookingService.start(clinic=self.clinic, chat_session=self.chat_session)
        self.chat_session.refresh_from_db()
        booking = self.chat_session.conversation_context["booking"]
        booking["step"] = BookingStep.CONFIRMED.value
        self.chat_session.conversation_context["booking"] = booking
        self.chat_session.save(update_fields=["conversation_context"])

        second = BookingService.start(clinic=self.clinic, chat_session=self.chat_session)

        self.assertFalse(second["resumed"])
        self.assertNotEqual(first["booking_id"], second["booking_id"])


class BookingSlotFillingIntegrationTests(TestCase):
    """End-to-end: "Book Botox Friday after 5" seeds specialty/date/time_hint
    and, once a doctor is chosen, jumps straight to the TIME step."""

    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="botox-clinic",
            name="Botox Clinic",
            email="botox@clinic.com",
            phone="+12125550005",
            timezone="America/New_York",
        )
        self.chat_session = ChatSession.objects.create(
            clinic=self.clinic,
            session_token="tok-botox-1",
            status=ChatSessionStatus.ACTIVE,
        )
        self.aesthetics = Specialty.objects.create(
            clinic=self.clinic, name="Aesthetics", slug="aesthetics"
        )
        self.botox = Service.objects.create(
            clinic=self.clinic, name="Botox", duration_min=30, price_cents=50000
        )
        self.doctor = Doctor.objects.create(
            clinic=self.clinic, full_name="Dr. Aesthetic", is_accepting_patients=True
        )
        DoctorSpecialty.objects.create(
            clinic=self.clinic, doctor=self.doctor, specialty=self.aesthetics
        )
        DoctorService.objects.create(
            clinic=self.clinic, doctor=self.doctor, service=self.botox
        )
        self.friday = _next_friday_matching_parse_natural_date()
        DoctorSchedule.objects.create(
            clinic=self.clinic,
            doctor=self.doctor,
            day_of_week=self.friday.weekday(),
            start_time=time(9, 0),
            end_time=time(18, 0),
            slot_duration_min=30,
        )

    def test_specialty_resolves_from_service(self):
        from apps.chatbot.nlu.resolvers import resolve_specialty_for_service

        self.assertEqual(
            resolve_specialty_for_service(self.clinic, str(self.botox.id)),
            str(self.aesthetics.id),
        )

    def test_start_seeds_date_and_time_hint_from_free_text(self):
        result = BookingService.start(
            clinic=self.clinic,
            chat_session=self.chat_session,
            message="Book Botox Friday after 5",
            specialty_id=str(self.aesthetics.id),
        )
        self.assertEqual(result["mode"], "specialty_first")
        # Doctor not yet known -> stays at DOCTOR step (only date/time_hint are seeded).
        self.assertEqual(result["step"], BookingStep.DOCTOR.value)
        self.chat_session.refresh_from_db()
        booking = self.chat_session.conversation_context["booking"]
        self.assertEqual(booking["date"], self.friday.isoformat())
        self.assertEqual(booking["time_hint"], "17:00:00")

    def test_known_doctor_and_date_hint_jumps_straight_to_time_step(self):
        """When the chat engine has already resolved both the service->specialty
        and a named doctor from "Book Botox Friday after 5 with Dr. Aesthetic",
        start() should skip PATH/SPECIALTY/DOCTOR/DATE entirely."""
        result = BookingService.start(
            clinic=self.clinic,
            chat_session=self.chat_session,
            message="Book Botox Friday after 5",
            specialty_id=str(self.aesthetics.id),
            doctor_id=str(self.doctor.id),
        )

        self.assertEqual(result["step"], BookingStep.TIME.value)
        slots = result["options"]["slots"]
        self.assertTrue(slots)
        for slot in slots:
            start = datetime.fromisoformat(slot["start"])
            self.assertGreaterEqual(start.time(), time(17, 0))
