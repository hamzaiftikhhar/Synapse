"""Manual-booking double-booking prevention.

Live-confirmed gap: the only DB constraint on Appointment was
end_time > start_time -- no uniqueness/overlap constraint existed at all,
so two patients could be booked with the same doctor at the same time with
no error, and the dashboard's "New appointment" dialog had no way to check
real availability before submitting (see ROADMAP.md). These tests cover
the new proactive overlap check (_check_no_overlap in router.py).
"""

from __future__ import annotations

from datetime import timedelta

from django.test import TestCase

from apps.appointments.models import AppointmentStatus
from apps.appointments.tests.factories import SLOT_END, SLOT_START, AppointmentWorld, unique_code

URL = "/api/v1/appointments"


class OverlapPreventionTests(TestCase):
    def setUp(self):
        self.world = AppointmentWorld(slug="overlap-a", email="overlap-a@test.com")
        self.existing = self.world.create_row()  # doctor_a, SLOT_START-SLOT_END, confirmed

    def test_exact_same_time_same_doctor_is_rejected(self):
        resp = self.client.post(
            URL,
            data=self.world.payload(confirmation_code=unique_code()),
            content_type="application/json",
            headers=self.world.headers,
        )
        self.assertEqual(resp.status_code, 409, resp.content)

    def test_partially_overlapping_time_same_doctor_is_rejected(self):
        overlap_start = SLOT_START + timedelta(minutes=15)
        overlap_end = overlap_start + timedelta(minutes=30)
        resp = self.client.post(
            URL,
            data=self.world.payload(
                start_time=overlap_start.isoformat(),
                end_time=overlap_end.isoformat(),
                confirmation_code=unique_code(),
                patient_id=str(self.world.patient_b.id),
            ),
            content_type="application/json",
            headers=self.world.headers,
        )
        self.assertEqual(resp.status_code, 409, resp.content)

    def test_same_time_different_doctor_is_allowed(self):
        resp = self.client.post(
            URL,
            data=self.world.payload(
                doctor_id=str(self.world.doctor_b.id),
                confirmation_code=unique_code(),
                patient_id=str(self.world.patient_b.id),
            ),
            content_type="application/json",
            headers=self.world.headers,
        )
        self.assertEqual(resp.status_code, 201, resp.content)

    def test_back_to_back_non_overlapping_time_is_allowed(self):
        """Starting exactly when the existing appointment ends must not be
        treated as an overlap."""
        resp = self.client.post(
            URL,
            data=self.world.payload(
                start_time=SLOT_END.isoformat(),
                end_time=(SLOT_END + timedelta(minutes=30)).isoformat(),
                confirmation_code=unique_code(),
                patient_id=str(self.world.patient_b.id),
            ),
            content_type="application/json",
            headers=self.world.headers,
        )
        self.assertEqual(resp.status_code, 201, resp.content)

    def test_cancelled_existing_appointment_does_not_block_the_slot(self):
        self.existing.status = AppointmentStatus.CANCELLED
        self.existing.save(update_fields=["status"])
        resp = self.client.post(
            URL,
            data=self.world.payload(confirmation_code=unique_code()),
            content_type="application/json",
            headers=self.world.headers,
        )
        self.assertEqual(resp.status_code, 201, resp.content)

    def test_editing_an_appointment_without_moving_it_does_not_conflict_with_itself(self):
        resp = self.client.patch(
            f"{URL}/{self.existing.id}",
            data={"notes": "Patient requested reminder call"},
            content_type="application/json",
            headers=self.world.headers,
        )
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_moving_an_appointment_into_another_ones_time_is_rejected(self):
        other_start = SLOT_START + timedelta(hours=1)
        other_end = other_start + timedelta(minutes=30)
        other = self.world.create_row(
            patient=self.world.patient_b,
            start_time=other_start,
            end_time=other_end,
            confirmation_code=unique_code(),
        )
        resp = self.client.patch(
            f"{URL}/{other.id}",
            data={"start_time": SLOT_START.isoformat(), "end_time": SLOT_END.isoformat()},
            content_type="application/json",
            headers=self.world.headers,
        )
        self.assertEqual(resp.status_code, 409, resp.content)
