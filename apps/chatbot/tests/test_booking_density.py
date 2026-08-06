"""booking/slots.py: weekday_capacity + compute_density_for_range — the cheap
aggregate-only calendar density preview (Phase 2), distinct from
compute_slots_for_day's full per-slot walk."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.test import TestCase
from django.utils import timezone

from apps.appointments.models import Appointment, AppointmentStatus
from apps.chatbot.booking.slots import compute_density_for_range, weekday_capacity
from apps.clinics.models import Clinic, ClinicBusinessHours
from apps.doctors.models import Doctor, DoctorLeave, DoctorSchedule
from apps.patients.models import Patient

_TZ = ZoneInfo("America/New_York")


def _next_weekday(weekday: int, *, from_days_ahead: int = 3):
    d = timezone.localdate() + timedelta(days=from_days_ahead)
    while d.weekday() != weekday:
        d += timedelta(days=1)
    return d


class WeekdayCapacityTests(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="density-clinic",
            name="Density Clinic",
            email="density@clinic.com",
            phone="+12125550006",
            timezone="America/New_York",
        )
        self.doctor = Doctor.objects.create(clinic=self.clinic, full_name="Dr. Density")

    def test_sums_slot_units_per_weekday(self):
        DoctorSchedule.objects.create(
            clinic=self.clinic,
            doctor=self.doctor,
            day_of_week=0,
            start_time=time(9, 0),
            end_time=time(12, 0),
            slot_duration_min=30,
        )
        capacity = weekday_capacity(self.clinic, [self.doctor])
        self.assertEqual(capacity[0], 6)
        self.assertEqual(capacity[1], 0)

    def test_no_doctors_returns_zeroed_map(self):
        capacity = weekday_capacity(self.clinic, [])
        self.assertEqual(capacity, {i: 0 for i in range(7)})


class ComputeDensityForRangeTests(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="density-range-clinic",
            name="Density Range Clinic",
            email="density-range@clinic.com",
            phone="+12125550007",
            timezone="America/New_York",
        )
        self.doctor = Doctor.objects.create(clinic=self.clinic, full_name="Dr. Range")
        self.target_date = _next_weekday(0)
        DoctorSchedule.objects.create(
            clinic=self.clinic,
            doctor=self.doctor,
            day_of_week=self.target_date.weekday(),
            start_time=time(9, 0),
            end_time=time(12, 0),
            slot_duration_min=30,
        )

    def _density(self):
        return compute_density_for_range(
            self.clinic,
            doctors=[self.doctor],
            start_date=self.target_date,
            end_date=self.target_date,
        )

    def test_plenty_when_nothing_booked(self):
        result = self._density()
        self.assertEqual(result[self.target_date]["density"], "plenty")

    def test_almost_full_when_mostly_booked(self):
        patient = Patient.objects.create(
            clinic=self.clinic, first_name="A", last_name="B", phone="+15551110000"
        )
        # 6 slots total; book 5 -> remaining/capacity ~0.17 still counts as
        # almost_full only below 0.15, so book 6 to guarantee almost_full.
        start = datetime.combine(self.target_date, time(9, 0), tzinfo=_TZ)
        for i in range(6):
            Appointment.objects.create(
                clinic=self.clinic,
                doctor=self.doctor,
                patient=patient,
                start_time=start + timedelta(minutes=30 * i),
                end_time=start + timedelta(minutes=30 * (i + 1)),
                status=AppointmentStatus.CONFIRMED,
                confirmation_code=f"AF{i:03d}",
            )
        result = self._density()
        self.assertEqual(result[self.target_date]["density"], "almost_full")

    def test_few_when_half_booked(self):
        patient = Patient.objects.create(
            clinic=self.clinic, first_name="A", last_name="B", phone="+15551110001"
        )
        start = datetime.combine(self.target_date, time(9, 0), tzinfo=_TZ)
        for i in range(4):
            Appointment.objects.create(
                clinic=self.clinic,
                doctor=self.doctor,
                patient=patient,
                start_time=start + timedelta(minutes=30 * i),
                end_time=start + timedelta(minutes=30 * (i + 1)),
                status=AppointmentStatus.CONFIRMED,
                confirmation_code=f"FL{i:03d}",
            )
        result = self._density()
        self.assertEqual(result[self.target_date]["density"], "few")

    def test_closed_when_business_hours_closed(self):
        ClinicBusinessHours.objects.create(
            clinic=self.clinic,
            day_of_week=self.target_date.weekday(),
            open_time=time(9, 0),
            close_time=time(17, 0),
            is_closed=True,
        )
        result = self._density()
        self.assertEqual(result[self.target_date]["density"], "closed")
        self.assertEqual(result[self.target_date]["reason"], "closed")

    def test_closed_when_no_schedule_coverage(self):
        other_day = self.target_date + timedelta(days=1)
        result = compute_density_for_range(
            self.clinic, doctors=[self.doctor], start_date=other_day, end_date=other_day
        )
        self.assertEqual(result[other_day]["density"], "closed")
        self.assertEqual(result[other_day]["reason"], "no_schedule")

    def test_leave_reduces_capacity(self):
        start = datetime.combine(self.target_date, time.min, tzinfo=_TZ)
        end = datetime.combine(self.target_date, time.max, tzinfo=_TZ)
        DoctorLeave.objects.create(
            clinic=self.clinic, doctor=self.doctor, start_at=start, end_at=end, is_active=True
        )
        result = self._density()
        # Sole doctor on leave for the whole day -> zero effective capacity -> closed.
        self.assertEqual(result[self.target_date]["density"], "closed")
