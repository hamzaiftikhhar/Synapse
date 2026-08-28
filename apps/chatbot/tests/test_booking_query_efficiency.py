"""Pre-deployment query-efficiency audit fixes.

`_doctor_options` previously called `_next_available_slot()` once per
candidate doctor, each of which looped 14 days re-querying schedule/leave/
appointments/holds for that one doctor alone — for a clinic with enough
doctors to hit the 20-candidate cap, up to ~1,400 DB round trips just to
render the "Choose a doctor" step. `list_specialties` and `_service_options`
had the same shape at smaller scale: a per-row `.count()` inside a list
comprehension. These tests assert the fixed query count stays flat as the
number of doctors/specialties/services grows — the whole point of the
fix — not just that the code still returns the right data (existing tests
in test_booking_service_first.py etc. already cover correctness).
"""

from __future__ import annotations

from datetime import time

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.chatbot.booking.serializers import _doctor_options, _service_options
from apps.chatbot.booking.state import BookingSession, BookingStep
from apps.chatbot.sql_tool.base import SQLContext
from apps.chatbot.sql_tool.handlers.doctors import list_specialties
from apps.clinics.models import Clinic
from apps.doctors.models import Doctor, DoctorSchedule, DoctorService, DoctorSpecialty
from apps.services.models import Service
from apps.specialties.models import Specialty


def _make_doctors(clinic: Clinic, count: int) -> list[Doctor]:
    doctors = []
    for i in range(count):
        doctor = Doctor.objects.create(
            clinic=clinic,
            full_name=f"Doctor {i}",
            is_active=True,
            is_accepting_patients=True,
        )
        # A real weekly schedule so compute_next_available_slots actually
        # walks slot generation instead of short-circuiting on "no schedule".
        DoctorSchedule.objects.create(
            clinic=clinic,
            doctor=doctor,
            day_of_week=0,
            start_time=time(9, 0),
            end_time=time(17, 0),
            slot_duration_min=30,
            is_active=True,
        )
        doctors.append(doctor)
    return doctors


class DoctorOptionsQueryCountTests(TestCase):
    def _clinic(self, tag: str) -> Clinic:
        return Clinic.objects.create(
            slug=f"query-efficiency-clinic-{tag}",
            name="Query Efficiency Clinic",
            email=f"query-efficiency-{tag}@clinic.com",
            phone="+12125550950",
            timezone="America/New_York",
        )

    def _doctor_options_query_count(self, doctor_count: int) -> int:
        clinic = self._clinic(str(doctor_count))
        _make_doctors(clinic, doctor_count)
        session = BookingSession.create(clinic_id=str(clinic.id), mode="general")
        session.step = BookingStep.DOCTOR.value
        with CaptureQueriesContext(connection) as ctx:
            result = _doctor_options(clinic, session)
        self.assertEqual(len(result["doctors"]), doctor_count)
        return len(ctx.captured_queries)

    def test_query_count_does_not_scale_with_doctor_count(self):
        """The regression this exists to catch: query count must be flat,
        not proportional to the number of doctors returned."""
        few = self._doctor_options_query_count(2)
        many = self._doctor_options_query_count(8)
        self.assertEqual(
            few,
            many,
            f"query count scaled with doctor count ({few} for 2 doctors vs "
            f"{many} for 8) — an N+1 has crept back in",
        )

    def test_query_count_is_small_in_absolute_terms(self):
        """Belt-and-suspenders: even the flat cost must be a small,
        constant handful of queries, not merely "flat but huge"."""
        count = self._doctor_options_query_count(6)
        self.assertLessEqual(
            count, 12, f"expected a small constant query count, got {count}"
        )

    def test_next_available_slot_is_still_correct_after_batching(self):
        """Correctness, not just query count — batching must find the same
        answer compute_slots_for_day would for that doctor/date."""
        clinic = self._clinic("correctness")
        [doctor] = _make_doctors(clinic, 1)
        session = BookingSession.create(clinic_id=str(clinic.id), mode="general")
        session.step = BookingStep.DOCTOR.value
        doctors = _doctor_options(clinic, session)["doctors"]
        self.assertEqual(len(doctors), 1)
        next_slot = doctors[0]["next_available"]
        self.assertIsNotNone(next_slot)
        self.assertEqual(next_slot["doctor_id"], str(doctor.id))


class ListSpecialtiesQueryCountTests(TestCase):
    def _query_count(self, specialty_count: int) -> int:
        clinic = Clinic.objects.create(
            slug=f"specialties-clinic-{specialty_count}",
            name="Specialties Clinic",
            email=f"specialties-{specialty_count}@clinic.com",
            phone="+12125550951",
            timezone="America/New_York",
        )
        for i in range(specialty_count):
            specialty = Specialty.objects.create(
                clinic=clinic, name=f"Specialty {i}", slug=f"specialty-{i}"
            )
            doctor = Doctor.objects.create(
                clinic=clinic, full_name=f"Doc {i}", is_active=True
            )
            DoctorSpecialty.objects.create(
                clinic=clinic, doctor=doctor, specialty=specialty
            )

        class _NLU:
            class entities:
                specialty = None

            class resolved_ids:
                specialty_id = None

        ctx = SQLContext(clinic=clinic, nlu=_NLU(), message="")
        with CaptureQueriesContext(connection) as qctx:
            result = list_specialties(ctx)
        self.assertEqual(len(result.rows), specialty_count)
        return len(qctx.captured_queries)

    def test_query_count_does_not_scale_with_specialty_count(self):
        few = self._query_count(2)
        many = self._query_count(8)
        self.assertEqual(
            few,
            many,
            f"query count scaled with specialty count ({few} for 2 vs "
            f"{many} for 8) — the per-row .count() N+1 has crept back in",
        )


class ServiceOptionsQueryCountTests(TestCase):
    def _query_count(self, service_count: int) -> int:
        clinic = Clinic.objects.create(
            slug=f"services-clinic-{service_count}",
            name="Services Clinic",
            email=f"services-{service_count}@clinic.com",
            phone="+12125550952",
            timezone="America/New_York",
        )
        for i in range(service_count):
            service = Service.objects.create(
                clinic=clinic, name=f"Service {i}", duration_min=30
            )
            doctor = Doctor.objects.create(
                clinic=clinic, full_name=f"Doc {i}", is_active=True,
                is_accepting_patients=True,
            )
            DoctorService.objects.create(clinic=clinic, doctor=doctor, service=service)

        session = BookingSession.create(clinic_id=str(clinic.id), mode="service_first")
        session.step = BookingStep.SERVICE.value
        with CaptureQueriesContext(connection) as qctx:
            result = _service_options(clinic, session)
        self.assertEqual(len(result["all"]), service_count)
        return len(qctx.captured_queries)

    def test_query_count_does_not_scale_with_service_count(self):
        few = self._query_count(2)
        many = self._query_count(8)
        self.assertEqual(
            few,
            many,
            f"query count scaled with service count ({few} for 2 vs "
            f"{many} for 8) — the per-row .count() N+1 has crept back in",
        )
