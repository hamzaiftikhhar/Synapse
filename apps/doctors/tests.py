from datetime import time

from django.test import TestCase

from apps.api.test_helpers import make_clinic_admin
from apps.doctors.models import Doctor, DoctorSchedule


class DoctorScheduleTests(TestCase):
    def setUp(self):
        self.user, self.clinic, self.headers = make_clinic_admin(
            email="owner@schedule.test", clinic_slug="schedule-clinic"
        )
        self.doctor = Doctor.objects.create(clinic=self.clinic, full_name="Dr. Chloe Bennett")

    def test_get_empty_schedule(self):
        resp = self.client.get(
            f"/api/v1/doctors/{self.doctor.id}/schedule", headers=self.headers
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), [])

    def test_put_replaces_schedule(self):
        payload = [
            {"day_of_week": 0, "start_time": "09:00:00", "end_time": "17:00:00", "slot_duration_min": 30},
            {"day_of_week": 2, "start_time": "12:00:00", "end_time": "19:00:00", "slot_duration_min": 30},
        ]
        resp = self.client.put(
            f"/api/v1/doctors/{self.doctor.id}/schedule",
            data=payload,
            content_type="application/json",
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 2)
        self.assertEqual(
            DoctorSchedule.objects.filter(clinic=self.clinic, doctor=self.doctor).count(), 2
        )

        # A second PUT fully replaces (not appends)
        resp2 = self.client.put(
            f"/api/v1/doctors/{self.doctor.id}/schedule",
            data=[payload[0]],
            content_type="application/json",
            headers=self.headers,
        )
        self.assertEqual(len(resp2.json()), 1)
        self.assertEqual(
            DoctorSchedule.objects.filter(clinic=self.clinic, doctor=self.doctor).count(), 1
        )

    def test_put_rejects_end_before_start(self):
        resp = self.client.put(
            f"/api/v1/doctors/{self.doctor.id}/schedule",
            data=[{"day_of_week": 0, "start_time": "17:00:00", "end_time": "09:00:00"}],
            content_type="application/json",
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 400)

    def test_put_does_not_clobber_another_doctors_schedule(self):
        other = Doctor.objects.create(clinic=self.clinic, full_name="Dr. Other")
        DoctorSchedule.objects.create(
            clinic=self.clinic,
            doctor=other,
            day_of_week=1,
            start_time=time(14, 0),
            end_time=time(16, 0),
            slot_duration_min=30,
        )
        resp = self.client.put(
            f"/api/v1/doctors/{self.doctor.id}/schedule",
            data=[
                {
                    "day_of_week": 0,
                    "start_time": "09:00:00",
                    "end_time": "11:00:00",
                    "slot_duration_min": 30,
                }
            ],
            content_type="application/json",
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            DoctorSchedule.objects.filter(clinic=self.clinic, doctor=self.doctor).count(),
            1,
        )
        self.assertEqual(
            DoctorSchedule.objects.filter(clinic=self.clinic, doctor=other).count(), 1
        )
        leftover = DoctorSchedule.objects.get(clinic=self.clinic, doctor=other)
        self.assertEqual(leftover.day_of_week, 1)
        self.assertEqual(leftover.start_time, time(14, 0))

    def test_schedule_for_wrong_tenant_404s(self):
        _, _, other_headers = make_clinic_admin(
            email="owner2@schedule.test", clinic_slug="schedule-clinic-2"
        )
        resp = self.client.get(
            f"/api/v1/doctors/{self.doctor.id}/schedule", headers=other_headers
        )
        self.assertEqual(resp.status_code, 404)
