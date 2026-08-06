"""PATH step "Earliest Available" hero (Phase 2): _hero_slot + the select_hero
action, including revalidation when the slot goes stale between render and tap."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.test import TestCase
from django.utils import timezone

from apps.appointments.models import Appointment, AppointmentStatus
from apps.chatbot.booking.serializers import _hero_slot
from apps.chatbot.booking.service import BookingService
from apps.chatbot.booking.state import BookingStep
from apps.chatbot.models import ChatSession, ChatSessionStatus
from apps.clinics.models import Clinic
from apps.doctors.models import Doctor, DoctorSchedule
from apps.patients.models import Patient

_TZ = ZoneInfo("America/New_York")


def _next_weekday(weekday: int, *, from_days_ahead: int = 0):
    d = timezone.localdate() + timedelta(days=from_days_ahead)
    while d.weekday() != weekday:
        d += timedelta(days=1)
    return d


class HeroSlotTests(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="hero-clinic",
            name="Hero Clinic",
            email="hero@clinic.com",
            phone="+12125550008",
            timezone="America/New_York",
        )
        self.cfg = {"hero_horizon_days": 3}

    def test_none_when_no_availability(self):
        self.assertIsNone(_hero_slot(self.clinic, self.cfg))

    def test_returns_earliest_slot_within_horizon(self):
        doctor = Doctor.objects.create(clinic=self.clinic, full_name="Dr. Hero")
        target = _next_weekday(timezone.localdate().weekday(), from_days_ahead=1)
        DoctorSchedule.objects.create(
            clinic=self.clinic,
            doctor=doctor,
            day_of_week=target.weekday(),
            start_time=time(9, 0),
            end_time=time(11, 0),
            slot_duration_min=30,
        )
        hero = _hero_slot(self.clinic, self.cfg)
        self.assertIsNotNone(hero)
        self.assertEqual(hero["doctor_id"], str(doctor.id))
        self.assertIn("day_label", hero)


class SelectHeroActionTests(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="hero-action-clinic",
            name="Hero Action Clinic",
            email="hero-action@clinic.com",
            phone="+12125550009",
            timezone="America/New_York",
        )
        self.doctor = Doctor.objects.create(clinic=self.clinic, full_name="Dr. Action")
        self.target_date = _next_weekday(timezone.localdate().weekday(), from_days_ahead=1)
        DoctorSchedule.objects.create(
            clinic=self.clinic,
            doctor=self.doctor,
            day_of_week=self.target_date.weekday(),
            start_time=time(9, 0),
            end_time=time(11, 0),
            slot_duration_min=30,
        )
        self.chat_session = ChatSession.objects.create(
            clinic=self.clinic,
            session_token="tok-hero-1",
            status=ChatSessionStatus.ACTIVE,
        )
        start_result = BookingService.start(clinic=self.clinic, chat_session=self.chat_session)
        self.booking_id = start_result["booking_id"]

    def test_still_open_slot_holds_and_jumps_to_details(self):
        hero = _hero_slot(self.clinic, {"hero_horizon_days": 3})
        self.assertIsNotNone(hero)

        result = BookingService.apply_step(
            clinic=self.clinic,
            chat_session=self.chat_session,
            booking_id=self.booking_id,
            action="select_hero",
            value={
                "start": hero["start"],
                "end": hero["end"],
                "doctor_id": hero["doctor_id"],
                "doctor": hero["doctor"],
            },
        )
        self.assertEqual(result["step"], BookingStep.DETAILS.value)
        self.chat_session.refresh_from_db()
        booking = self.chat_session.conversation_context["booking"]
        self.assertEqual(booking["doctor_id"], str(self.doctor.id))
        self.assertIsNotNone(booking["hold_expires_at"])

    def test_stale_slot_falls_back_to_date_step(self):
        hero = _hero_slot(self.clinic, {"hero_horizon_days": 3})
        self.assertIsNotNone(hero)

        # Someone else books the exact hero slot between render and tap.
        patient = Patient.objects.create(
            clinic=self.clinic, first_name="Jo", last_name="Doe", phone="+15559990000"
        )
        start_dt = datetime.fromisoformat(hero["start"])
        Appointment.objects.create(
            clinic=self.clinic,
            doctor=self.doctor,
            patient=patient,
            start_time=start_dt,
            end_time=start_dt + timedelta(minutes=30),
            status=AppointmentStatus.CONFIRMED,
        )

        result = BookingService.apply_step(
            clinic=self.clinic,
            chat_session=self.chat_session,
            booking_id=self.booking_id,
            action="select_hero",
            value={
                "start": hero["start"],
                "end": hero["end"],
                "doctor_id": hero["doctor_id"],
                "doctor": hero["doctor"],
            },
        )
        self.assertEqual(result["step"], BookingStep.DATE.value)
        self.assertTrue(result.get("stale_hero"))

    def test_missing_fields_raise(self):
        from apps.chatbot.booking.service import BookingError

        with self.assertRaises(BookingError):
            BookingService.apply_step(
                clinic=self.clinic,
                chat_session=self.chat_session,
                booking_id=self.booking_id,
                action="select_hero",
                value={},
            )
