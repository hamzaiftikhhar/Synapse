"""Reschedule must never leave a patient with neither appointment, nor with
both — the old one stays live until the new one is actually confirmed, then
both changes land atomically in BookingService.confirm."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.test import TestCase
from django.utils import timezone

from apps.appointments.models import Appointment, AppointmentStatus
from apps.chatbot.booking.service import BookingService
from apps.chatbot.models import ChatSession, ChatSessionStatus
from apps.clinics.models import Clinic
from apps.doctors.models import Doctor, DoctorSchedule
from apps.patients.models import Patient

TZ = ZoneInfo("America/New_York")


def _next_weekday(days_ahead_min: int):
    """A date at least `days_ahead_min` out that's guaranteed Mon–Fri, so it
    always falls inside the Mon–Fri DoctorSchedule this test sets up."""
    today = timezone.now().astimezone(TZ).date()
    d = today + timedelta(days=days_ahead_min)
    while d.weekday() > 4:  # Sat=5, Sun=6
        d += timedelta(days=1)
    return d


class RescheduleAtomicSwapTests(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="reschedule-clinic",
            name="Reschedule Clinic",
            email="reschedule@clinic.com",
            phone="+12125550099",
            timezone="America/New_York",
        )
        self.doctor = Doctor.objects.create(clinic=self.clinic, full_name="Dr. Reschedule")
        for day in range(5):
            DoctorSchedule.objects.create(
                clinic=self.clinic,
                doctor=self.doctor,
                day_of_week=day,
                start_time="09:00",
                end_time="17:00",
            )
        self.patient = Patient.objects.create(
            clinic=self.clinic, phone="+15550001111", first_name="Pat", last_name="Ient"
        )
        old_date = _next_weekday(3)
        self.old_start = timezone.make_aware(datetime.combine(old_date, time(10, 0)), TZ)
        self.old_appt = Appointment.objects.create(
            clinic=self.clinic,
            doctor=self.doctor,
            patient=self.patient,
            start_time=self.old_start,
            end_time=self.old_start + timedelta(minutes=30),
            status=AppointmentStatus.CONFIRMED,
            confirmation_code="OLD123",
        )
        self.chat_session = ChatSession.objects.create(
            clinic=self.clinic,
            session_token="tok-reschedule-1",
            status=ChatSessionStatus.ACTIVE,
            is_authenticated=True,
            patient=self.patient,
        )

    def _start_and_hold_new_slot(self, new_start):
        new_end = new_start + timedelta(minutes=30)
        result = BookingService.start(
            clinic=self.clinic,
            chat_session=self.chat_session,
            reason="Reschedule",
            doctor_id=str(self.doctor.id),
            doctor_name=self.doctor.full_name,
            slot_start=new_start.isoformat(),
            slot_end=new_end.isoformat(),
            replaces_appointment_id=str(self.old_appt.id),
        )
        self.chat_session.refresh_from_db()
        BookingService.hold_slot(
            clinic=self.clinic,
            chat_session=self.chat_session,
            booking_id=result["booking_id"],
        )
        self.chat_session.refresh_from_db()
        return result["booking_id"]

    def test_confirm_creates_new_and_cancels_old_together(self):
        new_start = self.old_start.replace(hour=11)
        booking_id = self._start_and_hold_new_slot(new_start)

        BookingService.confirm(
            clinic=self.clinic,
            chat_session=self.chat_session,
            booking_id=booking_id,
            patient=self.patient,
            otp_verified=True,
        )

        self.old_appt.refresh_from_db()
        self.assertEqual(self.old_appt.status, AppointmentStatus.CANCELLED)

        new_appts = Appointment.objects.filter(
            clinic=self.clinic, patient=self.patient, status=AppointmentStatus.CONFIRMED
        )
        self.assertEqual(new_appts.count(), 1)
        self.assertEqual(new_appts.first().start_time, new_start)

    def test_old_appointment_stays_active_until_confirm(self):
        """Starting/holding a new slot must not touch the old appointment —
        only an actual confirm() should cancel it."""
        new_start = self.old_start.replace(hour=13)
        self._start_and_hold_new_slot(new_start)

        self.old_appt.refresh_from_db()
        self.assertEqual(self.old_appt.status, AppointmentStatus.CONFIRMED)
        # No new appointment exists yet either — nothing was created early.
        self.assertEqual(
            Appointment.objects.filter(clinic=self.clinic, patient=self.patient).count(), 1
        )

    def test_confirm_fails_if_new_slot_taken_and_old_appointment_untouched(self):
        """A collision on the new slot must raise and leave the old
        appointment exactly as it was — never cancelled without a replacement.

        Simulates the race window between holding a slot and confirming it:
        the hold succeeds first (slot is free), then someone else grabs the
        same slot before this booking confirms — confirm()'s own re-check
        must catch it."""
        from apps.chatbot.booking.service import BookingError

        new_start = self.old_start.replace(hour=15)
        booking_id = self._start_and_hold_new_slot(new_start)

        other_patient = Patient.objects.create(
            clinic=self.clinic, phone="+15550002222", first_name="Other", last_name="One"
        )
        Appointment.objects.create(
            clinic=self.clinic,
            doctor=self.doctor,
            patient=other_patient,
            start_time=new_start,
            end_time=new_start + timedelta(minutes=30),
            status=AppointmentStatus.CONFIRMED,
            confirmation_code="TAKEN1",
        )

        with self.assertRaises(BookingError):
            BookingService.confirm(
                clinic=self.clinic,
                chat_session=self.chat_session,
                booking_id=booking_id,
                patient=self.patient,
                otp_verified=True,
            )

        self.old_appt.refresh_from_db()
        self.assertEqual(self.old_appt.status, AppointmentStatus.CONFIRMED)

    def test_reschedule_ignores_appointment_owned_by_another_patient(self):
        """Defense in depth: replaces_appointment_id for someone else's
        appointment must not cancel it, even though the new booking still
        succeeds for this patient."""
        other_patient = Patient.objects.create(
            clinic=self.clinic, phone="+15550003333", first_name="Not", last_name="You"
        )
        others_start = self.old_start + timedelta(days=1)
        others_appt = Appointment.objects.create(
            clinic=self.clinic,
            doctor=self.doctor,
            patient=other_patient,
            start_time=others_start,
            end_time=others_start + timedelta(minutes=30),
            status=AppointmentStatus.CONFIRMED,
            confirmation_code="OTHER1",
        )

        new_start = self.old_start.replace(hour=16)
        new_end = new_start + timedelta(minutes=30)
        result = BookingService.start(
            clinic=self.clinic,
            chat_session=self.chat_session,
            reason="Reschedule",
            doctor_id=str(self.doctor.id),
            doctor_name=self.doctor.full_name,
            slot_start=new_start.isoformat(),
            slot_end=new_end.isoformat(),
            replaces_appointment_id=str(others_appt.id),
        )
        self.chat_session.refresh_from_db()
        BookingService.hold_slot(
            clinic=self.clinic, chat_session=self.chat_session, booking_id=result["booking_id"]
        )
        self.chat_session.refresh_from_db()

        BookingService.confirm(
            clinic=self.clinic,
            chat_session=self.chat_session,
            booking_id=result["booking_id"],
            patient=self.patient,
            otp_verified=True,
        )

        others_appt.refresh_from_db()
        self.assertEqual(others_appt.status, AppointmentStatus.CONFIRMED)
        self.old_appt.refresh_from_db()
        self.assertEqual(self.old_appt.status, AppointmentStatus.CONFIRMED)

    def test_reschedule_cancels_old_even_when_details_step_resolves_a_different_patient_row(self):
        """Regression: the booking wizard's own contact-details step can
        legitimately resolve to a *different* Patient row for the same real
        person (e.g. phone typed without the "+1" the original SMS-verified
        record was saved with). Ownership of the appointment being replaced
        must be checked against the chat session's original OTP-verified
        patient, not that freshly-resolved one — otherwise the old
        appointment silently survives and the patient ends up with both."""
        duplicate_patient = Patient.objects.create(
            clinic=self.clinic, phone="5550001111", first_name="Pat", last_name="Ient"
        )
        self.assertNotEqual(duplicate_patient.id, self.patient.id)

        new_start = self.old_start.replace(hour=14)
        booking_id = self._start_and_hold_new_slot(new_start)

        BookingService.confirm(
            clinic=self.clinic,
            chat_session=self.chat_session,
            booking_id=booking_id,
            patient=duplicate_patient,  # what the details-step contact resolved to
            otp_verified=True,
        )

        self.old_appt.refresh_from_db()
        self.assertEqual(self.old_appt.status, AppointmentStatus.CANCELLED)
        self.assertEqual(
            Appointment.objects.filter(
                clinic=self.clinic, status=AppointmentStatus.CONFIRMED
            ).count(),
            1,
        )
