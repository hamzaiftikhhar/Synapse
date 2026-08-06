"""booking/slots.py: consolidated slot generation used by both the booking
wizard (serializers._slots_for_day) and the conversational availability
handler (sql_tool.handlers.doctors.doctor_availability)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.test import TestCase
from django.utils import timezone

_TZ = ZoneInfo("America/New_York")

from apps.appointments.models import Appointment, AppointmentStatus
from apps.chatbot.booking.slots import active_holds_for_date, compute_slots_for_day
from apps.clinics.models import Clinic
from apps.doctors.models import Doctor, DoctorLeave, DoctorSchedule
from apps.patients.models import Patient


def _next_weekday(weekday: int, *, from_days_ahead: int = 3) -> date:
    """A date at least `from_days_ahead` out (avoids the 'skip past times for
    today' cutoff) that falls on the given weekday (0=Monday)."""
    d = timezone.localdate() + timedelta(days=from_days_ahead)
    while d.weekday() != weekday:
        d += timedelta(days=1)
    return d


class ComputeSlotsForDayTests(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="slots-clinic",
            name="Slots Clinic",
            email="slots@clinic.com",
            phone="+12125550002",
            timezone="America/New_York",
        )
        self.doctor = Doctor.objects.create(
            clinic=self.clinic, full_name="Dr. Slot Test", is_active=True
        )
        self.target_date = _next_weekday(0)  # a Monday, safely in the future
        DoctorSchedule.objects.create(
            clinic=self.clinic,
            doctor=self.doctor,
            day_of_week=self.target_date.weekday(),
            start_time=time(9, 0),
            end_time=time(11, 0),
            slot_duration_min=30,
        )

    def test_generates_slots_from_schedule(self):
        slots = compute_slots_for_day(
            self.clinic, target_date=self.target_date, doctors=[self.doctor]
        )
        # 09:00-11:00 in 30-min increments = 4 slots
        self.assertEqual(len(slots), 4)
        self.assertEqual(slots[0]["doctor_id"], str(self.doctor.id))

    def test_no_schedule_that_day_returns_empty(self):
        other_day = self.target_date + timedelta(days=1)
        slots = compute_slots_for_day(
            self.clinic, target_date=other_day, doctors=[self.doctor]
        )
        self.assertEqual(slots, [])

    def test_leave_excludes_doctor_entirely(self):
        tz_start = datetime.combine(self.target_date, time.min, tzinfo=_TZ)
        tz_end = datetime.combine(self.target_date, time.max, tzinfo=_TZ)
        DoctorLeave.objects.create(
            clinic=self.clinic,
            doctor=self.doctor,
            start_at=tz_start,
            end_at=tz_end,
            is_active=True,
        )
        slots = compute_slots_for_day(
            self.clinic, target_date=self.target_date, doctors=[self.doctor]
        )
        self.assertEqual(slots, [])

    def test_existing_appointment_removes_that_slot(self):
        patient = Patient.objects.create(
            clinic=self.clinic, first_name="Pat", last_name="Ient", phone="+15551234567"
        )
        start = datetime.combine(self.target_date, time(9, 0), tzinfo=_TZ)
        Appointment.objects.create(
            clinic=self.clinic,
            doctor=self.doctor,
            patient=patient,
            start_time=start,
            end_time=start + timedelta(minutes=30),
            status=AppointmentStatus.CONFIRMED,
        )
        slots = compute_slots_for_day(
            self.clinic, target_date=self.target_date, doctors=[self.doctor]
        )
        self.assertEqual(len(slots), 3)
        self.assertNotIn("09:00 AM", [s["label"] for s in slots])

    def test_excluded_keys_removes_held_slot(self):
        start = datetime.combine(self.target_date, time(9, 0), tzinfo=_TZ)
        key = f"{self.doctor.id}|{start.isoformat()}"
        slots = compute_slots_for_day(
            self.clinic,
            target_date=self.target_date,
            doctors=[self.doctor],
            excluded_keys={key},
        )
        self.assertEqual(len(slots), 3)

    def test_max_slots_caps_output(self):
        slots = compute_slots_for_day(
            self.clinic, target_date=self.target_date, doctors=[self.doctor], max_slots=2
        )
        self.assertLessEqual(len(slots), 2)


class ActiveHoldsForDateTests(TestCase):
    def test_no_active_sessions_returns_empty_set(self):
        clinic = Clinic.objects.create(
            slug="holds-clinic",
            name="Holds Clinic",
            email="holds@clinic.com",
            phone="+12125550003",
            timezone="America/New_York",
        )
        held = active_holds_for_date(clinic, timezone.localdate())
        self.assertEqual(held, set())
