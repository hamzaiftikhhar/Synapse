"""Authenticated patients must not re-enter DETAILS/OTP after picking a slot."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.test import TestCase
from django.utils import timezone

from apps.appointments.models import Appointment, AppointmentStatus
from apps.chatbot.booking.service import BookingService
from apps.chatbot.booking.state import BookingStep
from apps.chatbot.models import ChatSession, ChatSessionStatus
from apps.clinics.models import Clinic
from apps.doctors.models import Doctor, DoctorSchedule
from apps.patients.models import Patient
from apps.patients.services import patient_service

_TZ = ZoneInfo("America/New_York")


def _next_weekday(weekday: int, *, from_days_ahead: int = 0):
    d = timezone.localdate() + timedelta(days=from_days_ahead)
    while d.weekday() != weekday:
        d += timedelta(days=1)
    return d


class EmailPlaceholderPhoneTests(TestCase):
    def test_prefix_sharing_emails_get_distinct_placeholders(self):
        e1 = "collision-test-abcdefg@example.com"
        e2 = "collision-test-abcdefg@different.org"
        p1 = patient_service.email_placeholder_phone(e1)
        p2 = patient_service.email_placeholder_phone(e2)
        self.assertNotEqual(p1, p2)
        self.assertEqual(len(p1), 20)
        self.assertEqual(len(p2), 20)
        self.assertTrue(p1.startswith("email:"))
        # Old truncation would have collided:
        self.assertEqual((f"email:{e1}")[:20], (f"email:{e2}")[:20])

    def test_placeholder_is_case_insensitive(self):
        self.assertEqual(
            patient_service.email_placeholder_phone("Ali@Example.com"),
            patient_service.email_placeholder_phone("ali@example.com"),
        )


class AuthSkipConfirmTests(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="auth-skip-clinic",
            name="Auth Skip Clinic",
            email="auth-skip@clinic.com",
            phone="+12125550100",
            timezone="America/New_York",
        )
        self.doctor = Doctor.objects.create(clinic=self.clinic, full_name="Dr. Skip")
        self.target_date = _next_weekday(timezone.localdate().weekday(), from_days_ahead=1)
        DoctorSchedule.objects.create(
            clinic=self.clinic,
            doctor=self.doctor,
            day_of_week=self.target_date.weekday(),
            start_time=time(9, 0),
            end_time=time(11, 0),
            slot_duration_min=30,
        )
        self.patient = Patient.objects.create(
            clinic=self.clinic,
            first_name="Ali",
            last_name="Hamza",
            phone="+15551234567",
            email="ali@example.com",
            is_verified=True,
        )
        self.chat_session = ChatSession.objects.create(
            clinic=self.clinic,
            session_token="tok-auth-skip-1",
            status=ChatSessionStatus.ACTIVE,
            patient=self.patient,
            is_authenticated=True,
        )
        start = datetime(
            self.target_date.year,
            self.target_date.month,
            self.target_date.day,
            9,
            0,
            tzinfo=_TZ,
        )
        end = start + timedelta(minutes=30)
        self.slot_start = start.isoformat()
        self.slot_end = end.isoformat()

    def test_select_time_skips_details_when_authenticated(self):
        started = BookingService.start(
            clinic=self.clinic, chat_session=self.chat_session
        )
        result = BookingService.apply_step(
            clinic=self.clinic,
            chat_session=self.chat_session,
            booking_id=started["booking_id"],
            action="select_time",
            value={
                "start": self.slot_start,
                "end": self.slot_end,
                "doctor_id": str(self.doctor.id),
                "doctor": self.doctor.full_name,
            },
        )
        self.assertEqual(result["step"], BookingStep.CONFIRMED.value)
        self.assertEqual(result["confirmation"]["first_name"], "Ali")
        self.assertTrue(
            Appointment.objects.filter(
                clinic=self.clinic,
                patient=self.patient,
                status=AppointmentStatus.CONFIRMED,
            ).exists()
        )

    def test_slot_prefill_start_skips_details_when_authenticated(self):
        """Availability-card / hero deep-link into start(slot_*) must also skip."""
        result = BookingService.start(
            clinic=self.clinic,
            chat_session=self.chat_session,
            doctor_id=str(self.doctor.id),
            doctor_name=self.doctor.full_name,
            slot_start=self.slot_start,
            slot_end=self.slot_end,
        )
        self.assertEqual(result["step"], BookingStep.CONFIRMED.value)
        self.assertEqual(result["confirmation"]["first_name"], "Ali")

    def test_unauthenticated_still_lands_on_details(self):
        self.chat_session.is_authenticated = False
        self.chat_session.patient = None
        self.chat_session.save(update_fields=["is_authenticated", "patient"])
        result = BookingService.start(
            clinic=self.clinic,
            chat_session=self.chat_session,
            doctor_id=str(self.doctor.id),
            doctor_name=self.doctor.full_name,
            slot_start=self.slot_start,
            slot_end=self.slot_end,
        )
        self.assertEqual(result["step"], BookingStep.DETAILS.value)

    def test_email_only_patient_does_not_leak_placeholder_phone(self):
        email = "email-only@example.com"
        email_patient = Patient.objects.create(
            clinic=self.clinic,
            first_name="Eve",
            last_name="Mail",
            phone=patient_service.email_placeholder_phone(email),
            email=email,
            is_verified=True,
        )
        self.chat_session.patient = email_patient
        self.chat_session.is_authenticated = True
        self.chat_session.save(update_fields=["patient", "is_authenticated"])

        result = BookingService.start(
            clinic=self.clinic,
            chat_session=self.chat_session,
            doctor_id=str(self.doctor.id),
            doctor_name=self.doctor.full_name,
            slot_start=self.slot_start,
            slot_end=self.slot_end,
        )
        self.assertEqual(result["step"], BookingStep.CONFIRMED.value)
        self.chat_session.refresh_from_db()
        booking = self.chat_session.conversation_context["booking"]
        self.assertEqual(booking["patient_email"], email)
        self.assertFalse((booking.get("patient_phone") or "").startswith("email:"))
