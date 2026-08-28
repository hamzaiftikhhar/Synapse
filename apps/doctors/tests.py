from datetime import time

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.api.test_helpers import make_clinic_admin
from apps.doctors.models import Doctor, DoctorSchedule, DoctorService, DoctorSpecialty
from apps.doctors.services.doctor_service import create_doctor
from apps.services.models import Service
from apps.specialties.models import Specialty


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


class DoctorCreateDefaultsTests(TestCase):
    def setUp(self):
        _, self.clinic, _ = make_clinic_admin(
            email="owner@doctor-defaults.test", clinic_slug="doctor-defaults-clinic"
        )

    def test_omitted_languages_are_empty_not_english(self):
        doctor = create_doctor(clinic=self.clinic, full_name="Dr. No Lang")
        self.assertEqual(list(doctor.languages), [])

    def test_explicit_languages_are_kept(self):
        doctor = create_doctor(
            clinic=self.clinic, full_name="Dr. Bilingual", languages=["en", "ur"]
        )
        self.assertEqual(list(doctor.languages), ["en", "ur"])


class ListDoctorsQueryCountTests(TestCase):
    """Dashboard "Doctors" list page — previously 2 unprefetched M2M
    queries (specialties, services) per row, up to ~200 extra queries for
    a full 100-row page."""

    def setUp(self):
        self.user, self.clinic, self.headers = make_clinic_admin(
            email="owner@doctors-list.test", clinic_slug="doctors-list-clinic"
        )

    def _seed(self, count: int) -> None:
        specialty, _ = Specialty.objects.get_or_create(
            clinic=self.clinic, slug="general", defaults={"name": "General"}
        )
        service, _ = Service.objects.get_or_create(
            clinic=self.clinic, name="Checkup", defaults={"duration_min": 30}
        )
        for i in range(count):
            doctor = Doctor.objects.create(
                clinic=self.clinic, full_name=f"Dr. {Doctor.objects.count()}-{i}"
            )
            DoctorSpecialty.objects.create(
                clinic=self.clinic, doctor=doctor, specialty=specialty
            )
            DoctorService.objects.create(
                clinic=self.clinic, doctor=doctor, service=service
            )

    def test_specialty_and_service_ids_are_still_correct(self):
        self._seed(3)
        resp = self.client.get("/api/v1/doctors", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(len(body["results"]), 3)
        for row in body["results"]:
            self.assertEqual(len(row["specialty_ids"]), 1)
            self.assertEqual(len(row["service_ids"]), 1)

    def test_query_count_does_not_scale_with_page_size(self):
        self._seed(2)
        with CaptureQueriesContext(connection) as few_ctx:
            self.client.get("/api/v1/doctors", headers=self.headers)

        self._seed(8)
        with CaptureQueriesContext(connection) as many_ctx:
            self.client.get("/api/v1/doctors", headers=self.headers)

        few, many = len(few_ctx.captured_queries), len(many_ctx.captured_queries)
        self.assertEqual(
            few,
            many,
            f"query count scaled with row count ({few} for 2 doctors vs "
            f"{many} for 10) — the unprefetched specialties/services N+1 "
            "has crept back in",
        )
