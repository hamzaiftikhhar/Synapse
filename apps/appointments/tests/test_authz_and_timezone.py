"""Tenant isolation, patient/widget auth, JWTs, and clinic-timezone storage."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import jwt
from django.conf import settings
from django.test import TestCase

from apps.api.auth.jwt import create_patient_access_token, create_staff_access_token
from apps.appointments.models import AppointmentStatus
from apps.appointments.tests.factories import (
    SLOT_END,
    SLOT_START,
    URL,
    AppointmentWorld,
    random_uuid,
)
from apps.chatbot.models import ChatSession, ChatSessionStatus
from apps.chatbot.sql_tool.utils import clinic_timezone, format_clinic_when

WIDGET_CANCEL = "/api/v1/widget/appointments/cancel"
WIDGET_LIST = "/api/v1/widget/appointments/list"
WIDGET_RESCHEDULE = "/api/v1/widget/appointments/reschedule"


class TenantIsolationTests(TestCase):
    def setUp(self):
        self.a = AppointmentWorld(slug="tenant-a", email="tenant-a@test.com")
        self.b = AppointmentWorld(slug="tenant-b", email="tenant-b@test.com")
        self.row_a = self.a.create_row()

    def test_clinic_b_list_does_not_include_clinic_a(self):
        resp = self.client.get(URL, {"limit": 100}, headers=self.b.headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 0)

    def test_clinic_b_cannot_get_clinic_a_appointment(self):
        resp = self.client.get(f"{URL}/{self.row_a.id}", headers=self.b.headers)
        self.assertEqual(resp.status_code, 404)

    def test_clinic_b_cannot_patch_clinic_a_appointment(self):
        resp = self.client.patch(
            f"{URL}/{self.row_a.id}",
            data={"notes": "hijacked"},
            content_type="application/json",
            headers=self.b.headers,
        )
        self.assertEqual(resp.status_code, 404)
        self.row_a.refresh_from_db()
        self.assertEqual(self.row_a.notes, "")

    def test_clinic_b_cannot_cancel_clinic_a_appointment(self):
        resp = self.client.delete(f"{URL}/{self.row_a.id}", headers=self.b.headers)
        self.assertEqual(resp.status_code, 404)
        self.row_a.refresh_from_db()
        self.assertEqual(self.row_a.status, AppointmentStatus.CONFIRMED)

    def test_clinic_a_cannot_book_clinic_b_doctor(self):
        resp = self.client.post(
            URL,
            data=self.a.payload(doctor_id=str(self.b.doctor_a.id)),
            content_type="application/json",
            headers=self.a.headers,
        )
        self.assertEqual(resp.status_code, 400)

    def test_clinic_a_cannot_book_clinic_b_patient(self):
        resp = self.client.post(
            URL,
            data=self.a.payload(patient_id=str(self.b.patient_a.id)),
            content_type="application/json",
            headers=self.a.headers,
        )
        self.assertEqual(resp.status_code, 400)

    def test_clinic_a_cannot_attach_clinic_b_service(self):
        resp = self.client.post(
            URL,
            data=self.a.payload(service_id=str(self.b.service.id)),
            content_type="application/json",
            headers=self.a.headers,
        )
        self.assertEqual(resp.status_code, 400)


class StaffJwtTests(TestCase):
    def setUp(self):
        self.world = AppointmentWorld(slug="jwt-staff", email="jwt-staff@test.com")
        self.row = self.world.create_row()

    def test_missing_jwt_rejected(self):
        resp = self.client.get(URL)
        self.assertEqual(resp.status_code, 401)

    def test_invalid_jwt_rejected(self):
        resp = self.client.get(URL, headers={"Authorization": "Bearer not-a-token"})
        self.assertEqual(resp.status_code, 401)

    def test_expired_staff_jwt_rejected(self):
        token = jwt.encode(
            {
                "sub": str(self.world.user.id),
                "tenant": self.world.clinic.slug,
                "clinic_id": str(self.world.clinic.id),
                "role": self.world.user.role,
                "exp": datetime.now(UTC) - timedelta(minutes=1),
                "iat": datetime.now(UTC) - timedelta(minutes=10),
                "type": "staff_access",
            },
            settings.JWT_SECRET_KEY,
            algorithm=settings.JWT_ALGORITHM,
        )
        resp = self.client.get(URL, headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(resp.status_code, 401)

    def test_staff_jwt_for_other_clinic_cannot_read(self):
        other = AppointmentWorld(slug="jwt-other", email="jwt-other@test.com")
        token = create_staff_access_token(
            user_id=other.user.id,
            role=other.user.role,
            tenant=other.clinic.slug,
            clinic_id=other.clinic.id,
        )
        resp = self.client.get(
            f"{URL}/{self.row.id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(resp.status_code, 404)

    def test_patient_jwt_cannot_use_staff_appointments_api(self):
        token = create_patient_access_token(
            patient_id=self.world.patient_a.id,
            clinic_id=self.world.clinic.id,
        )
        resp = self.client.get(URL, headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(resp.status_code, 401)
        resp = self.client.patch(
            f"{URL}/{self.row.id}",
            data={"notes": "nope"},
            content_type="application/json",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(resp.status_code, 401)


class WidgetPatientAuthzTests(TestCase):
    def setUp(self):
        self.world = AppointmentWorld(slug="widget-authz", email="widget-authz@test.com")
        self.row_a = self.world.create_row(patient=self.world.patient_a)
        self.row_b = self.world.create_row(
            patient=self.world.patient_b,
            start_time=SLOT_START + timedelta(hours=1),
            end_time=SLOT_END + timedelta(hours=1),
        )
        self.session_a = self.world.otp_session(self.world.patient_a, "sess-patient-a")
        self.session_b = self.world.otp_session(self.world.patient_b, "sess-patient-b")

    def test_patient_lists_only_own_upcoming(self):
        resp = self.client.post(
            WIDGET_LIST,
            data={"clinic_slug": self.world.clinic.slug, "session_token": "sess-patient-a"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        ids = {row["id"] for row in resp.json()["appointments"]}
        self.assertEqual(ids, {str(self.row_a.id)})

    def test_patient_a_cannot_cancel_patient_b(self):
        resp = self.client.post(
            WIDGET_CANCEL,
            data={
                "clinic_slug": self.world.clinic.slug,
                "session_token": "sess-patient-a",
                "appointment_id": str(self.row_b.id),
            },
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 404)
        self.row_b.refresh_from_db()
        self.assertEqual(self.row_b.status, AppointmentStatus.CONFIRMED)

    def test_patient_a_can_cancel_own(self):
        resp = self.client.post(
            WIDGET_CANCEL,
            data={
                "clinic_slug": self.world.clinic.slug,
                "session_token": "sess-patient-a",
                "appointment_id": str(self.row_a.id),
            },
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.row_a.refresh_from_db()
        self.assertEqual(self.row_a.status, AppointmentStatus.CANCELLED)

    def test_patient_a_cannot_reschedule_patient_b(self):
        resp = self.client.post(
            WIDGET_RESCHEDULE,
            data={
                "clinic_slug": self.world.clinic.slug,
                "session_token": "sess-patient-a",
                "appointment_id": str(self.row_b.id),
            },
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 404)

    def test_unauthenticated_session_cannot_list(self):
        ChatSession.objects.create(
            clinic=self.world.clinic,
            session_token="sess-guest",
            status=ChatSessionStatus.ACTIVE,
            is_authenticated=False,
        )
        resp = self.client.post(
            WIDGET_LIST,
            data={"clinic_slug": self.world.clinic.slug, "session_token": "sess-guest"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 401)

    def test_wrong_clinic_slug_cannot_use_session(self):
        other = AppointmentWorld(slug="widget-other", email="widget-other@test.com")
        resp = self.client.post(
            WIDGET_CANCEL,
            data={
                "clinic_slug": other.clinic.slug,
                "session_token": "sess-patient-a",
                "appointment_id": str(self.row_a.id),
            },
            content_type="application/json",
        )
        self.assertIn(resp.status_code, (404, 401))
        self.row_a.refresh_from_db()
        self.assertEqual(self.row_a.status, AppointmentStatus.CONFIRMED)

    def test_unknown_session_rejected(self):
        resp = self.client.post(
            WIDGET_LIST,
            data={"clinic_slug": self.world.clinic.slug, "session_token": "nope"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 404)

    def test_wrong_appointment_id_rejected(self):
        resp = self.client.post(
            WIDGET_CANCEL,
            data={
                "clinic_slug": self.world.clinic.slug,
                "session_token": "sess-patient-a",
                "appointment_id": random_uuid(),
            },
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 404)


class TimezoneTests(TestCase):
    def setUp(self):
        self.world = AppointmentWorld(
            slug="tz-clinic", email="tz@test.com", timezone="America/Los_Angeles"
        )

    def test_la_offset_stores_correct_utc_instant(self):
        """9:00 AM America/Los_Angeles on 13 Aug 2026 is 16:00 UTC (PDT)."""
        start = datetime(2026, 8, 13, 9, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
        end = start + timedelta(minutes=30)
        resp = self.client.post(
            URL,
            data=self.world.payload(start_time=start.isoformat(), end_time=end.isoformat()),
            content_type="application/json",
            headers=self.world.headers,
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        row_id = resp.json()["id"]
        fetched = self.client.get(f"{URL}/{row_id}", headers=self.world.headers).json()
        stored = datetime.fromisoformat(fetched["start_time"].replace("Z", "+00:00"))
        self.assertEqual(stored.astimezone(UTC), start.astimezone(UTC))
        self.assertEqual(stored.astimezone(UTC).hour, 16)

    def test_karachi_offset_is_honored_as_its_own_instant(self):
        """A client that sends +05:00 is storing Karachi wall-clock, not LA."""
        start = datetime(2026, 8, 13, 9, 0, tzinfo=ZoneInfo("Asia/Karachi"))
        end = start + timedelta(minutes=30)
        resp = self.client.post(
            URL,
            data=self.world.payload(start_time=start.isoformat(), end_time=end.isoformat()),
            content_type="application/json",
            headers=self.world.headers,
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        fetched = self.client.get(
            f"{URL}/{resp.json()['id']}", headers=self.world.headers
        ).json()
        stored = datetime.fromisoformat(fetched["start_time"].replace("Z", "+00:00"))
        self.assertEqual(stored.astimezone(UTC).hour, 4)

    def test_dst_spring_forward_pacific(self):
        """8 Mar 2026 01:30 PST is UTC 09:30; 03:30 PDT is UTC 10:30."""
        before = datetime(2026, 3, 8, 1, 30, tzinfo=ZoneInfo("America/Los_Angeles"))
        after = datetime(2026, 3, 8, 3, 30, tzinfo=ZoneInfo("America/Los_Angeles"))
        self.assertEqual(before.astimezone(UTC).hour, 9)
        self.assertEqual(after.astimezone(UTC).hour, 10)

        resp = self.client.post(
            URL,
            data=self.world.payload(
                start_time=after.isoformat(),
                end_time=(after + timedelta(minutes=30)).isoformat(),
            ),
            content_type="application/json",
            headers=self.world.headers,
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        fetched = self.client.get(
            f"{URL}/{resp.json()['id']}", headers=self.world.headers
        ).json()
        stored = datetime.fromisoformat(fetched["start_time"].replace("Z", "+00:00"))
        self.assertEqual(stored.astimezone(UTC), after.astimezone(UTC))

    def test_midnight_clinic_local_does_not_shift_calendar_day(self):
        start = datetime(2026, 8, 13, 0, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
        end = start + timedelta(minutes=30)
        resp = self.client.post(
            URL,
            data=self.world.payload(start_time=start.isoformat(), end_time=end.isoformat()),
            content_type="application/json",
            headers=self.world.headers,
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        fetched = self.client.get(
            f"{URL}/{resp.json()['id']}", headers=self.world.headers
        ).json()
        stored = datetime.fromisoformat(fetched["start_time"].replace("Z", "+00:00"))
        local = stored.astimezone(ZoneInfo("America/Los_Angeles"))
        self.assertEqual(local.day, 13)
        self.assertEqual(local.hour, 0)

    def test_format_clinic_when_uses_clinic_timezone(self):
        start = datetime(2026, 8, 13, 9, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
        label = format_clinic_when(start, clinic_timezone(self.world.clinic))
        self.assertIn("9:00", label.replace("\u202f", " "))
        self.assertNotIn("16:00", label)
