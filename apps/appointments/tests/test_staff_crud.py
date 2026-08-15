"""Staff JWT appointment CRUD, filters, and input validation."""

from __future__ import annotations

from datetime import timedelta

from django.test import TestCase

from apps.appointments.models import Appointment, AppointmentStatus
from apps.appointments.tests.factories import (
    LA,
    SLOT_END,
    SLOT_START,
    URL,
    AppointmentWorld,
    random_uuid,
    unique_code,
)


class CreateAppointmentTests(TestCase):
    def setUp(self):
        self.world = AppointmentWorld(slug="crud-create", email="crud-create@test.com")

    def test_valid_appointment_creates_and_persists(self):
        resp = self.client.post(
            URL,
            data=self.world.payload(),
            content_type="application/json",
            headers=self.world.headers,
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        body = resp.json()
        self.assertEqual(body["doctor_id"], str(self.world.doctor_a.id))
        self.assertEqual(body["patient_id"], str(self.world.patient_a.id))
        self.assertEqual(body["status"], "confirmed")
        self.assertEqual(body["source"], "admin")
        self.assertTrue(body["confirmation_code"])
        self.assertEqual(Appointment.objects.filter(clinic=self.world.clinic).count(), 1)
        row = Appointment.objects.get(id=body["id"])
        self.assertEqual(row.clinic_id, self.world.clinic.id)
        self.assertEqual(row.start_time, SLOT_START)
        self.assertEqual(row.end_time, SLOT_END)

    def test_missing_patient_rejected(self):
        payload = self.world.payload()
        del payload["patient_id"]
        resp = self.client.post(
            URL, data=payload, content_type="application/json", headers=self.world.headers
        )
        self.assertIn(resp.status_code, (400, 422))

    def test_missing_doctor_rejected(self):
        payload = self.world.payload()
        del payload["doctor_id"]
        resp = self.client.post(
            URL, data=payload, content_type="application/json", headers=self.world.headers
        )
        self.assertIn(resp.status_code, (400, 422))

    def test_unknown_patient_rejected(self):
        resp = self.client.post(
            URL,
            data=self.world.payload(patient_id=random_uuid()),
            content_type="application/json",
            headers=self.world.headers,
        )
        self.assertEqual(resp.status_code, 400)

    def test_unknown_doctor_rejected(self):
        resp = self.client.post(
            URL,
            data=self.world.payload(doctor_id=random_uuid()),
            content_type="application/json",
            headers=self.world.headers,
        )
        self.assertEqual(resp.status_code, 400)

    def test_unknown_service_rejected(self):
        resp = self.client.post(
            URL,
            data=self.world.payload(service_id=random_uuid()),
            content_type="application/json",
            headers=self.world.headers,
        )
        self.assertEqual(resp.status_code, 400)

    def test_unknown_insurance_rejected(self):
        resp = self.client.post(
            URL,
            data=self.world.payload(insurance_plan_id=random_uuid()),
            content_type="application/json",
            headers=self.world.headers,
        )
        self.assertEqual(resp.status_code, 400)

    def test_end_before_start_rejected(self):
        resp = self.client.post(
            URL,
            data=self.world.payload(
                start_time=SLOT_END.isoformat(),
                end_time=SLOT_START.isoformat(),
            ),
            content_type="application/json",
            headers=self.world.headers,
        )
        self.assertEqual(resp.status_code, 400)

    def test_equal_start_and_end_rejected(self):
        resp = self.client.post(
            URL,
            data=self.world.payload(
                start_time=SLOT_START.isoformat(),
                end_time=SLOT_START.isoformat(),
            ),
            content_type="application/json",
            headers=self.world.headers,
        )
        self.assertEqual(resp.status_code, 400)

    def test_invalid_datetime_string_rejected(self):
        resp = self.client.post(
            URL,
            data=self.world.payload(start_time="not-a-date", end_time="also-bad"),
            content_type="application/json",
            headers=self.world.headers,
        )
        self.assertIn(resp.status_code, (400, 422))

    def test_invalid_status_rejected(self):
        resp = self.client.post(
            URL,
            data=self.world.payload(status="maybe"),
            content_type="application/json",
            headers=self.world.headers,
        )
        self.assertEqual(resp.status_code, 400)

    def test_invalid_source_rejected(self):
        resp = self.client.post(
            URL,
            data=self.world.payload(source="fax"),
            content_type="application/json",
            headers=self.world.headers,
        )
        self.assertEqual(resp.status_code, 400)

    def test_past_appointment_is_currently_allowed(self):
        """Staff API does not reject historical start times — documented gap."""
        past_start = SLOT_START.replace(year=2020)
        past_end = past_start + timedelta(minutes=30)
        resp = self.client.post(
            URL,
            data=self.world.payload(
                start_time=past_start.isoformat(),
                end_time=past_end.isoformat(),
            ),
            content_type="application/json",
            headers=self.world.headers,
        )
        self.assertEqual(resp.status_code, 201, resp.content)

    def test_service_doctor_does_not_offer_is_currently_allowed(self):
        """Staff API does not require DoctorService membership — documented gap."""
        resp = self.client.post(
            URL,
            data=self.world.payload(service_id=str(self.world.other_service.id)),
            content_type="application/json",
            headers=self.world.headers,
        )
        self.assertEqual(resp.status_code, 201, resp.content)

    def test_duplicate_confirmation_code_rejected(self):
        self.world.create_row(confirmation_code="DUP001")
        resp = self.client.post(
            URL,
            data=self.world.payload(
                confirmation_code="DUP001",
                start_time=(SLOT_START + timedelta(hours=2)).isoformat(),
                end_time=(SLOT_END + timedelta(hours=2)).isoformat(),
            ),
            content_type="application/json",
            headers=self.world.headers,
        )
        self.assertEqual(resp.status_code, 400)


class ReadAppointmentTests(TestCase):
    def setUp(self):
        self.world = AppointmentWorld(slug="crud-read", email="crud-read@test.com")
        self.a = self.world.create_row(status=AppointmentStatus.CONFIRMED)
        self.b = self.world.create_row(
            doctor=self.world.doctor_b,
            patient=self.world.patient_b,
            start_time=SLOT_START + timedelta(hours=1),
            end_time=SLOT_END + timedelta(hours=1),
            status=AppointmentStatus.PENDING,
            confirmation_code=unique_code(),
        )
        self.past = self.world.create_row(
            start_time=SLOT_START - timedelta(days=7),
            end_time=SLOT_END - timedelta(days=7),
            status=AppointmentStatus.COMPLETED,
            confirmation_code=unique_code(),
        )

    def test_list_returns_clinic_appointments(self):
        resp = self.client.get(URL, {"limit": 100}, headers=self.world.headers)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["count"], 3)
        self.assertEqual(len(body["results"]), 3)

    def test_get_detail(self):
        resp = self.client.get(f"{URL}/{self.a.id}", headers=self.world.headers)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["id"], str(self.a.id))
        self.assertEqual(body["confirmation_code"], self.a.confirmation_code)
        self.assertEqual(body["doctor_name"], "Dr. Alpha")

    def test_get_unknown_id_404(self):
        resp = self.client.get(f"{URL}/{random_uuid()}", headers=self.world.headers)
        self.assertEqual(resp.status_code, 404)

    def test_filter_status(self):
        resp = self.client.get(URL, {"status": "pending"}, headers=self.world.headers)
        ids = {row["id"] for row in resp.json()["results"]}
        self.assertEqual(ids, {str(self.b.id)})

    def test_filter_doctor(self):
        resp = self.client.get(
            URL, {"doctor_id": str(self.world.doctor_b.id)}, headers=self.world.headers
        )
        ids = {row["id"] for row in resp.json()["results"]}
        self.assertEqual(ids, {str(self.b.id)})

    def test_filter_patient(self):
        resp = self.client.get(
            URL, {"patient_id": str(self.world.patient_a.id)}, headers=self.world.headers
        )
        ids = {row["id"] for row in resp.json()["results"]}
        self.assertEqual(ids, {str(self.a.id), str(self.past.id)})

    def test_filter_from_date_upcoming(self):
        resp = self.client.get(
            URL,
            {"from_date": SLOT_START.isoformat(), "limit": 100},
            headers=self.world.headers,
        )
        ids = {row["id"] for row in resp.json()["results"]}
        self.assertIn(str(self.a.id), ids)
        self.assertIn(str(self.b.id), ids)
        self.assertNotIn(str(self.past.id), ids)

    def test_filter_to_date_past(self):
        cutoff = SLOT_START - timedelta(days=1)
        resp = self.client.get(
            URL,
            {"to_date": cutoff.isoformat(), "limit": 100},
            headers=self.world.headers,
        )
        ids = {row["id"] for row in resp.json()["results"]}
        self.assertEqual(ids, {str(self.past.id)})

    def test_filter_today_window_in_clinic_tz(self):
        start = SLOT_START.replace(hour=0, minute=0)
        end = SLOT_START.replace(hour=23, minute=59)
        resp = self.client.get(
            URL,
            {"from_date": start.isoformat(), "to_date": end.isoformat()},
            headers=self.world.headers,
        )
        ids = {row["id"] for row in resp.json()["results"]}
        self.assertEqual(ids, {str(self.a.id), str(self.b.id)})

    def test_pagination_limit_and_offset(self):
        page1 = self.client.get(URL, {"limit": 1, "offset": 0}, headers=self.world.headers)
        page2 = self.client.get(URL, {"limit": 1, "offset": 1}, headers=self.world.headers)
        self.assertEqual(page1.json()["count"], 3)
        self.assertEqual(len(page1.json()["results"]), 1)
        self.assertNotEqual(page1.json()["results"][0]["id"], page2.json()["results"][0]["id"])

    def test_list_has_no_search_query_param(self):
        """Search is frontend-only; unknown params must not 500."""
        resp = self.client.get(URL, {"search": "Alpha"}, headers=self.world.headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 3)


class UpdateAppointmentTests(TestCase):
    def setUp(self):
        self.world = AppointmentWorld(slug="crud-update", email="crud-update@test.com")
        self.row = self.world.create_row()

    def test_change_patient(self):
        resp = self.client.patch(
            f"{URL}/{self.row.id}",
            data={"patient_id": str(self.world.patient_b.id)},
            content_type="application/json",
            headers=self.world.headers,
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.row.refresh_from_db()
        self.assertEqual(self.row.patient_id, self.world.patient_b.id)

    def test_change_doctor(self):
        resp = self.client.patch(
            f"{URL}/{self.row.id}",
            data={"doctor_id": str(self.world.doctor_b.id)},
            content_type="application/json",
            headers=self.world.headers,
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.row.refresh_from_db()
        self.assertEqual(self.row.doctor_id, self.world.doctor_b.id)

    def test_change_service(self):
        resp = self.client.patch(
            f"{URL}/{self.row.id}",
            data={"service_id": str(self.world.other_service.id)},
            content_type="application/json",
            headers=self.world.headers,
        )
        self.assertEqual(resp.status_code, 200)
        self.row.refresh_from_db()
        self.assertEqual(self.row.service_id, self.world.other_service.id)

    def test_change_start_and_duration(self):
        new_start = SLOT_START + timedelta(hours=2)
        new_end = new_start + timedelta(minutes=45)
        resp = self.client.patch(
            f"{URL}/{self.row.id}",
            data={"start_time": new_start.isoformat(), "end_time": new_end.isoformat()},
            content_type="application/json",
            headers=self.world.headers,
        )
        self.assertEqual(resp.status_code, 200)
        self.row.refresh_from_db()
        self.assertEqual(self.row.start_time, new_start)
        self.assertEqual(self.row.end_time, new_end)

    def test_change_notes_and_insurance(self):
        resp = self.client.patch(
            f"{URL}/{self.row.id}",
            data={
                "notes": "Prefers afternoon",
                "insurance_plan_id": str(self.world.insurance.id),
            },
            content_type="application/json",
            headers=self.world.headers,
        )
        self.assertEqual(resp.status_code, 200)
        self.row.refresh_from_db()
        self.assertEqual(self.row.notes, "Prefers afternoon")
        self.assertEqual(self.row.insurance_plan_id, self.world.insurance.id)

    def test_change_status(self):
        resp = self.client.patch(
            f"{URL}/{self.row.id}",
            data={"status": "completed"},
            content_type="application/json",
            headers=self.world.headers,
        )
        self.assertEqual(resp.status_code, 200)
        self.row.refresh_from_db()
        self.assertEqual(self.row.status, AppointmentStatus.COMPLETED)

    def test_invalid_end_on_update_rejected(self):
        resp = self.client.patch(
            f"{URL}/{self.row.id}",
            data={
                "start_time": SLOT_END.isoformat(),
                "end_time": SLOT_START.isoformat(),
            },
            content_type="application/json",
            headers=self.world.headers,
        )
        self.assertEqual(resp.status_code, 400)
        self.row.refresh_from_db()
        self.assertEqual(self.row.start_time, SLOT_START)


class CancelAppointmentTests(TestCase):
    def setUp(self):
        self.world = AppointmentWorld(slug="crud-cancel", email="crud-cancel@test.com")

    def test_cancel_confirmed_soft_deletes(self):
        row = self.world.create_row(status=AppointmentStatus.CONFIRMED)
        resp = self.client.delete(f"{URL}/{row.id}", headers=self.world.headers)
        self.assertEqual(resp.status_code, 200)
        row.refresh_from_db()
        self.assertEqual(row.status, AppointmentStatus.CANCELLED)
        self.assertTrue(Appointment.objects.filter(id=row.id).exists())

    def test_cancel_pending(self):
        row = self.world.create_row(status=AppointmentStatus.PENDING)
        resp = self.client.delete(f"{URL}/{row.id}", headers=self.world.headers)
        self.assertEqual(resp.status_code, 200)
        row.refresh_from_db()
        self.assertEqual(row.status, AppointmentStatus.CANCELLED)

    def test_cancel_already_cancelled_is_idempotent(self):
        row = self.world.create_row(status=AppointmentStatus.CANCELLED)
        resp = self.client.delete(f"{URL}/{row.id}", headers=self.world.headers)
        self.assertEqual(resp.status_code, 200)
        row.refresh_from_db()
        self.assertEqual(row.status, AppointmentStatus.CANCELLED)

    def test_cancel_unknown_404(self):
        resp = self.client.delete(f"{URL}/{random_uuid()}", headers=self.world.headers)
        self.assertEqual(resp.status_code, 404)


class StatusTransitionTests(TestCase):
    """Current API accepts any enum value — there is no state machine."""

    def setUp(self):
        self.world = AppointmentWorld(slug="crud-status", email="crud-status@test.com")

    def test_every_status_value_can_be_saved(self):
        row = self.world.create_row(status=AppointmentStatus.PENDING)
        for status in AppointmentStatus.values:
            resp = self.client.patch(
                f"{URL}/{row.id}",
                data={"status": status},
                content_type="application/json",
                headers=self.world.headers,
            )
            self.assertEqual(resp.status_code, 200, status)
            row.refresh_from_db()
            self.assertEqual(row.status, status)

    def test_cancelled_to_completed_is_currently_allowed(self):
        row = self.world.create_row(status=AppointmentStatus.CANCELLED)
        resp = self.client.patch(
            f"{URL}/{row.id}",
            data={"status": "completed"},
            content_type="application/json",
            headers=self.world.headers,
        )
        self.assertEqual(resp.status_code, 200)

    def test_completed_to_cancelled_is_currently_allowed(self):
        row = self.world.create_row(status=AppointmentStatus.COMPLETED)
        resp = self.client.patch(
            f"{URL}/{row.id}",
            data={"status": "cancelled"},
            content_type="application/json",
            headers=self.world.headers,
        )
        self.assertEqual(resp.status_code, 200)
