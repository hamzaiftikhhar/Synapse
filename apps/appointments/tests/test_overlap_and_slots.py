"""Doctor-specific overlap (GiST), slot availability, and concurrent booking."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from django.db import IntegrityError, connections
from django.test import TestCase, TransactionTestCase

from apps.appointments.models import Appointment, AppointmentStatus
from apps.appointments.tests.factories import (
    SLOT_END,
    SLOT_START,
    URL,
    AppointmentWorld,
    unique_code,
)
from apps.chatbot.booking.slots import compute_slots_for_day
from apps.doctors.models import Doctor


class OverlapTests(TestCase):
    def setUp(self):
        self.world = AppointmentWorld(slug="overlap-clinic", email="overlap@test.com")

    def test_exact_duplicate_same_doctor_time_rejected(self):
        first = self.client.post(
            URL,
            data=self.world.payload(),
            content_type="application/json",
            headers=self.world.headers,
        )
        self.assertEqual(first.status_code, 201, first.content)
        second = self.client.post(
            URL,
            data=self.world.payload(patient_id=str(self.world.patient_b.id)),
            content_type="application/json",
            headers=self.world.headers,
        )
        self.assertEqual(second.status_code, 400)
        self.assertEqual(Appointment.objects.filter(clinic=self.world.clinic).count(), 1)

    def test_partial_overlap_same_doctor_rejected(self):
        self.world.create_row()
        overlap_start = SLOT_START + timedelta(minutes=15)
        overlap_end = overlap_start + timedelta(minutes=30)
        resp = self.client.post(
            URL,
            data=self.world.payload(
                start_time=overlap_start.isoformat(),
                end_time=overlap_end.isoformat(),
                patient_id=str(self.world.patient_b.id),
            ),
            content_type="application/json",
            headers=self.world.headers,
        )
        self.assertEqual(resp.status_code, 400)

    def test_adjacent_slots_same_doctor_allowed(self):
        """tstzrange is half-open: 15:00–15:30 and 15:30–16:00 must both succeed."""
        self.world.create_row()
        resp = self.client.post(
            URL,
            data=self.world.payload(
                start_time=SLOT_END.isoformat(),
                end_time=(SLOT_END + timedelta(minutes=30)).isoformat(),
                patient_id=str(self.world.patient_b.id),
            ),
            content_type="application/json",
            headers=self.world.headers,
        )
        self.assertEqual(resp.status_code, 201, resp.content)

    def test_same_time_different_doctors_allowed(self):
        first = self.client.post(
            URL,
            data=self.world.payload(),
            content_type="application/json",
            headers=self.world.headers,
        )
        self.assertEqual(first.status_code, 201)
        second = self.client.post(
            URL,
            data=self.world.payload(
                doctor_id=str(self.world.doctor_b.id),
                patient_id=str(self.world.patient_b.id),
            ),
            content_type="application/json",
            headers=self.world.headers,
        )
        self.assertEqual(second.status_code, 201, second.content)
        self.assertEqual(Appointment.objects.filter(clinic=self.world.clinic).count(), 2)

    def test_update_to_occupied_slot_rejected(self):
        self.world.create_row()
        other = self.world.create_row(
            start_time=SLOT_START + timedelta(hours=2),
            end_time=SLOT_END + timedelta(hours=2),
            patient=self.world.patient_b,
            confirmation_code=unique_code(),
        )
        resp = self.client.patch(
            f"{URL}/{other.id}",
            data={
                "start_time": SLOT_START.isoformat(),
                "end_time": SLOT_END.isoformat(),
            },
            content_type="application/json",
            headers=self.world.headers,
        )
        self.assertEqual(resp.status_code, 400)
        other.refresh_from_db()
        self.assertEqual(other.start_time, SLOT_START + timedelta(hours=2))

    def test_change_doctor_releases_a_and_reserves_b(self):
        row = self.world.create_row(doctor=self.world.doctor_a)
        resp = self.client.patch(
            f"{URL}/{row.id}",
            data={"doctor_id": str(self.world.doctor_b.id)},
            content_type="application/json",
            headers=self.world.headers,
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        row.refresh_from_db()
        self.assertEqual(row.doctor_id, self.world.doctor_b.id)

        reuse_a = self.client.post(
            URL,
            data=self.world.payload(
                doctor_id=str(self.world.doctor_a.id),
                patient_id=str(self.world.patient_b.id),
            ),
            content_type="application/json",
            headers=self.world.headers,
        )
        self.assertEqual(reuse_a.status_code, 201, reuse_a.content)

        clash_b = self.client.post(
            URL,
            data=self.world.payload(
                doctor_id=str(self.world.doctor_b.id),
                start_time=(SLOT_START + timedelta(hours=1)).isoformat(),
                end_time=(SLOT_END + timedelta(hours=1)).isoformat(),
            ),
            content_type="application/json",
            headers=self.world.headers,
        )
        # 3pm on B is taken by the moved appointment; 4pm is free — just assert 3pm B is blocked
        clash_3pm = self.client.post(
            URL,
            data=self.world.payload(
                doctor_id=str(self.world.doctor_b.id),
                patient_id=str(self.world.patient_a.id),
                confirmation_code=unique_code(),
            ),
            content_type="application/json",
            headers=self.world.headers,
        )
        self.assertEqual(clash_3pm.status_code, 400)
        self.assertEqual(clash_b.status_code, 201)

    def test_cancel_frees_only_that_doctors_slot(self):
        a_row = self.world.create_row(doctor=self.world.doctor_a)
        self.world.create_row(
            doctor=self.world.doctor_b,
            patient=self.world.patient_b,
            confirmation_code=unique_code(),
        )
        self.client.delete(f"{URL}/{a_row.id}", headers=self.world.headers)

        reuse_a = self.client.post(
            URL,
            data=self.world.payload(patient_id=str(self.world.patient_a.id)),
            content_type="application/json",
            headers=self.world.headers,
        )
        self.assertEqual(reuse_a.status_code, 201, reuse_a.content)

        still_blocked_b = self.client.post(
            URL,
            data=self.world.payload(
                doctor_id=str(self.world.doctor_b.id),
                patient_id=str(self.world.patient_a.id),
                confirmation_code=unique_code(),
            ),
            content_type="application/json",
            headers=self.world.headers,
        )
        self.assertEqual(still_blocked_b.status_code, 400)

    def test_rescheduled_status_does_not_block_slot(self):
        self.world.create_row(status=AppointmentStatus.RESCHEDULED)
        resp = self.client.post(
            URL,
            data=self.world.payload(patient_id=str(self.world.patient_b.id)),
            content_type="application/json",
            headers=self.world.headers,
        )
        self.assertEqual(resp.status_code, 201, resp.content)

    def test_completed_still_blocks_gist(self):
        self.world.create_row(status=AppointmentStatus.COMPLETED)
        resp = self.client.post(
            URL,
            data=self.world.payload(patient_id=str(self.world.patient_b.id)),
            content_type="application/json",
            headers=self.world.headers,
        )
        self.assertEqual(resp.status_code, 400)

    def test_no_show_still_blocks_gist(self):
        self.world.create_row(status=AppointmentStatus.NO_SHOW)
        resp = self.client.post(
            URL,
            data=self.world.payload(patient_id=str(self.world.patient_b.id)),
            content_type="application/json",
            headers=self.world.headers,
        )
        self.assertEqual(resp.status_code, 400)


class SlotAvailabilityTests(TestCase):
    def setUp(self):
        self.world = AppointmentWorld(slug="slot-clinic", email="slots@test.com")
        self.day = SLOT_START.date()

    def _labels(self, doctor: Doctor) -> set[str]:
        slots = compute_slots_for_day(
            self.world.clinic, target_date=self.day, doctors=[doctor]
        )
        return {s["label"] for s in slots}

    def test_booking_doctor_a_does_not_remove_doctor_b_slot(self):
        self.world.create_row(doctor=self.world.doctor_a)
        self.assertNotIn("03:00 PM", self._labels(self.world.doctor_a))
        self.assertIn("03:00 PM", self._labels(self.world.doctor_b))

    def test_cancel_restores_only_doctor_a_slot(self):
        row = self.world.create_row(doctor=self.world.doctor_a)
        self.world.create_row(
            doctor=self.world.doctor_b,
            patient=self.world.patient_b,
            confirmation_code=unique_code(),
        )
        row.status = AppointmentStatus.CANCELLED
        row.save(update_fields=["status"])
        self.assertIn("03:00 PM", self._labels(self.world.doctor_a))
        self.assertNotIn("03:00 PM", self._labels(self.world.doctor_b))

    def test_change_doctor_updates_both_timetables(self):
        row = self.world.create_row(doctor=self.world.doctor_a)
        row.doctor = self.world.doctor_b
        row.save(update_fields=["doctor"])
        self.assertIn("03:00 PM", self._labels(self.world.doctor_a))
        self.assertNotIn("03:00 PM", self._labels(self.world.doctor_b))

    def test_completed_appointment_must_not_appear_in_slots(self):
        """GiST still occupies completed rows; chatbot slots must match."""
        self.world.create_row(status=AppointmentStatus.COMPLETED)
        self.assertNotIn("03:00 PM", self._labels(self.world.doctor_a))

    def test_no_show_appointment_must_not_appear_in_slots(self):
        self.world.create_row(status=AppointmentStatus.NO_SHOW)
        self.assertNotIn("03:00 PM", self._labels(self.world.doctor_a))


class ConcurrentBookingTests(TransactionTestCase):
    def test_two_parallel_inserts_only_one_succeeds(self):
        world = AppointmentWorld(slug="race-clinic", email="race@test.com")
        clinic_id = world.clinic.id
        doctor_id = world.doctor_a.id
        patient_a = world.patient_a.id
        patient_b = world.patient_b.id
        start = SLOT_START
        end = SLOT_END

        def attempt(patient_id: object, code: str) -> str:
            try:
                Appointment.objects.create(
                    clinic_id=clinic_id,
                    doctor_id=doctor_id,
                    patient_id=patient_id,
                    start_time=start,
                    end_time=end,
                    status=AppointmentStatus.CONFIRMED,
                    confirmation_code=code,
                    source="admin",
                )
                return "ok"
            except IntegrityError:
                return "conflict"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(attempt, patient_a, "RACE1")
            f2 = pool.submit(attempt, patient_b, "RACE2")
            results = [f1.result(), f2.result()]

        self.assertEqual(results.count("ok"), 1)
        self.assertEqual(results.count("conflict"), 1)
        self.assertEqual(
            Appointment.objects.filter(clinic_id=clinic_id, doctor_id=doctor_id).count(),
            1,
        )
