"""Clinic analytics overview/insights: tenant isolation, ranges, timezone, empty."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.test import TestCase
from django.utils import timezone

from apps.api.platform.tests import make_super_admin
from apps.api.test_helpers import make_clinic_admin
from apps.appointments.models import Appointment, AppointmentSource, AppointmentStatus
from apps.appointments.tests.factories import AppointmentWorld, unique_code
from apps.chatbot.models import ChatSession, ChatSessionStatus
from apps.doctors.models import DoctorSpecialty
from apps.specialties.models import Specialty


OVERVIEW = "/api/v1/analytics/overview"
INSIGHTS = "/api/v1/analytics/insights"
BREAKDOWN = "/api/v1/analytics/breakdown"
CALENDAR = "/api/v1/analytics/calendar"
LA = ZoneInfo("America/Los_Angeles")


class AnalyticsOverviewTests(TestCase):
    def setUp(self):
        self.world = AppointmentWorld(slug="ov-a", email="ov-a@test.com")
        self.other_user, self.other_clinic, self.other_headers = make_clinic_admin(
            email="ov-b@test.com", clinic_slug="ov-b"
        )

    def test_empty_clinic_returns_zeroes(self):
        resp = self.client.get(OVERVIEW, headers=self.world.headers)
        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()
        self.assertEqual(body["summary"]["conversations"], 0)
        self.assertEqual(body["summary"]["appointments"], 0)
        self.assertEqual(
            {row["status"]: row["count"] for row in body["appointment_status"]},
            {
                "confirmed": 0,
                "pending": 0,
                "completed": 0,
                "cancelled": 0,
                "no_show": 0,
                "rescheduled": 0,
            },
        )
        self.assertTrue(len(body["conversation_appointment_trend"]) >= 7)

    def test_invalid_range_rejected(self):
        resp = self.client.get(OVERVIEW + "?range=2d", headers=self.world.headers)
        self.assertEqual(resp.status_code, 400)

    def test_tenant_isolation(self):
        ChatSession.objects.create(
            clinic=self.world.clinic,
            session_token="sess-a-1",
            status=ChatSessionStatus.ACTIVE,
        )
        self.world.create_row()
        mine = self.client.get(OVERVIEW, headers=self.world.headers).json()
        other = self.client.get(OVERVIEW, headers=self.other_headers).json()
        self.assertGreaterEqual(mine["summary"]["conversations"], 1)
        self.assertGreaterEqual(mine["summary"]["appointments"], 1)
        self.assertEqual(other["summary"]["conversations"], 0)
        self.assertEqual(other["summary"]["appointments"], 0)

    def test_unauthenticated_rejected(self):
        self.assertEqual(self.client.get(OVERVIEW).status_code, 401)

    def test_status_aggregation_matches_db(self):
        now = timezone.now()
        self.world.create_row(status=AppointmentStatus.CONFIRMED, start_time=now, end_time=now + timedelta(minutes=30))
        self.world.create_row(
            status=AppointmentStatus.PENDING,
            start_time=now - timedelta(minutes=30),
            end_time=now,
            confirmation_code=unique_code(),
            patient=self.world.patient_b,
        )
        body = self.client.get(OVERVIEW, headers=self.world.headers).json()
        by_status = {row["status"]: row["count"] for row in body["appointment_status"]}
        self.assertEqual(by_status.get("confirmed"), 1)
        self.assertEqual(by_status.get("pending"), 1)
        self.assertEqual(sum(by_status.values()), body["summary"]["appointments"])

    def test_clinic_timezone_daily_bucket(self):
        # 21 Aug 2026 01:00 UTC = 20 Aug 2026 18:00 America/Los_Angeles
        when = datetime(2026, 8, 21, 1, 0, tzinfo=ZoneInfo("UTC"))
        frozen = datetime(2026, 8, 25, 20, 0, tzinfo=ZoneInfo("UTC"))
        appt = self.world.create_row(start_time=when, end_time=when + timedelta(minutes=30))
        Appointment.objects.filter(id=appt.id).update(created_at=when)
        from unittest.mock import patch

        with patch("apps.api.analytics.ranges.timezone.now", return_value=frozen):
            body = self.client.get(OVERVIEW + "?range=12m", headers=self.world.headers).json()
        by_day = {row["date"]: row["appointments"] for row in body["conversation_appointment_trend"]}
        self.assertEqual(by_day.get("2026-08-20"), 1)
        self.assertNotEqual(by_day.get("2026-08-21"), 1)

    def test_super_admin_entering_clinic_sees_that_clinic(self):
        ChatSession.objects.create(
            clinic=self.world.clinic,
            session_token="sess-sa-1",
            status=ChatSessionStatus.CLOSED,
        )
        _admin, headers = make_super_admin(email="root-ov@test.com")
        headers["X-Tenant-ID"] = self.world.clinic.slug
        body = self.client.get(OVERVIEW, headers=headers).json()
        self.assertGreaterEqual(body["summary"]["conversations"], 1)

    def test_specialty_bars_use_doctor_link(self):
        spec = Specialty.objects.create(
            clinic=self.world.clinic, name="Dermatology", slug="derm"
        )
        DoctorSpecialty.objects.create(
            clinic=self.world.clinic, doctor=self.world.doctor_a, specialty=spec
        )
        now = timezone.now()
        self.world.create_row(start_time=now, end_time=now + timedelta(minutes=30))
        body = self.client.get(OVERVIEW, headers=self.world.headers).json()
        labels = [row["label"] for row in body["appointments_by_specialty"]]
        self.assertIn("Dermatology", labels)

    def test_source_radar_compares_phone_walk_in_chatbot(self):
        now = timezone.now()
        self.world.create_row(
            source=AppointmentSource.PHONE,
            status=AppointmentStatus.CONFIRMED,
            start_time=now - timedelta(hours=2),
            end_time=now - timedelta(hours=1, minutes=30),
        )
        self.world.create_row(
            source=AppointmentSource.WALK_IN,
            status=AppointmentStatus.PENDING,
            start_time=now - timedelta(hours=1),
            end_time=now - timedelta(minutes=30),
            confirmation_code=unique_code(),
            patient=self.world.patient_b,
        )
        self.world.create_row(
            source=AppointmentSource.CHATBOT,
            status=AppointmentStatus.COMPLETED,
            start_time=now - timedelta(hours=2),
            end_time=now - timedelta(hours=1, minutes=30),
            confirmation_code=unique_code(),
            doctor=self.world.doctor_b,
        )
        body = self.client.get(OVERVIEW, headers=self.world.headers).json()
        by_axis = {row["axis"]: row for row in body["appointment_source_radar"]}
        self.assertGreaterEqual(by_axis["Volume"]["phone"], 1)
        self.assertGreaterEqual(by_axis["Volume"]["walk_in"], 1)
        self.assertGreaterEqual(by_axis["Volume"]["chatbot"], 1)
        self.assertGreaterEqual(by_axis["Confirmed"]["phone"], 1)
        self.assertGreaterEqual(by_axis["Pending"]["walk_in"], 1)
        self.assertGreaterEqual(by_axis["Completed"]["chatbot"], 1)


    def test_accepted_ranges(self):
        for key in ("7d", "30d", "90d", "6m", "12m"):
            resp = self.client.get(OVERVIEW + f"?range={key}", headers=self.world.headers)
            self.assertEqual(resp.status_code, 200, resp.content)

    def test_longer_range_has_more_daily_points(self):
        short = self.client.get(OVERVIEW + "?range=7d", headers=self.world.headers).json()
        long = self.client.get(OVERVIEW + "?range=12m", headers=self.world.headers).json()
        self.assertGreater(
            len(long["conversation_appointment_trend"]),
            len(short["conversation_appointment_trend"]),
        )

    def test_owner_without_clinic_rejected(self):
        from apps.api.test_helpers import make_verified_owner

        _user, headers = make_verified_owner(email="noclinic-ov@test.com")
        self.assertEqual(self.client.get(OVERVIEW, headers=headers).status_code, 400)

    def test_super_admin_without_tenant_rejected(self):
        _admin, headers = make_super_admin(email="root-ov-none@test.com")
        self.assertEqual(self.client.get(OVERVIEW, headers=headers).status_code, 400)

    def test_ops_inbox_is_all_time(self):
        ChatSession.objects.create(
            clinic=self.world.clinic,
            session_token="sess-inbox-1",
            status=ChatSessionStatus.ESCALATED,
        )
        body = self.client.get(OVERVIEW, headers=self.world.headers).json()
        self.assertGreaterEqual(body["ops"]["inbox"]["escalated"], 1)
        self.assertGreaterEqual(body["ops"]["inbox"]["total"], 1)


class AnalyticsInsightsTests(TestCase):
    def setUp(self):
        self.world = AppointmentWorld(slug="ins-a", email="ins-a@test.com")

    def test_conversation_outcomes_use_session_status(self):
        ChatSession.objects.create(
            clinic=self.world.clinic, session_token="c1", status=ChatSessionStatus.CLOSED
        )
        ChatSession.objects.create(
            clinic=self.world.clinic, session_token="c2", status=ChatSessionStatus.ESCALATED
        )
        body = self.client.get(INSIGHTS, headers=self.world.headers).json()
        detail = body["conversations_detail"]
        self.assertEqual(detail["closed"], 1)
        self.assertEqual(detail["escalated"], 1)
        self.assertNotIn("resolved", detail)

    def test_breakdown_doctors(self):
        now = timezone.now()
        self.world.create_row(start_time=now, end_time=now + timedelta(minutes=30))
        resp = self.client.get(
            BREAKDOWN + "?dimension=doctor&range=30d", headers=self.world.headers
        )
        self.assertEqual(resp.status_code, 200)
        labels = [row["label"] for row in resp.json()["items"]]
        self.assertIn("Dr. Alpha", labels)

    def test_breakdown_doctor_status(self):
        now = timezone.now()
        self.world.create_row(
            doctor=self.world.doctor_a,
            status=AppointmentStatus.COMPLETED,
            start_time=now - timedelta(hours=2),
            end_time=now - timedelta(hours=1, minutes=30),
        )
        self.world.create_row(
            doctor=self.world.doctor_a,
            status=AppointmentStatus.PENDING,
            start_time=now - timedelta(hours=1),
            end_time=now - timedelta(minutes=30),
        )
        self.world.create_row(
            doctor=self.world.doctor_b,
            status=AppointmentStatus.CANCELLED,
            start_time=now - timedelta(minutes=45),
            end_time=now - timedelta(minutes=15),
        )
        resp = self.client.get(
            BREAKDOWN + "?dimension=doctor_status&range=30d", headers=self.world.headers
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["dimension"], "doctor_status")
        by_label = {row["label"]: row for row in body["items"]}
        self.assertEqual(by_label["Dr. Alpha"]["completed"], 1)
        self.assertEqual(by_label["Dr. Alpha"]["pending"], 1)
        self.assertEqual(by_label["Dr. Alpha"]["total"], 2)
        self.assertEqual(by_label["Dr. Bravo"]["cancelled"], 1)

    def test_clinic_owner_does_not_see_ai_cost(self):
        body = self.client.get(INSIGHTS, headers=self.world.headers).json()
        self.assertFalse(body["show_cost"])
        self.assertIsNone(body["ai"]["estimated_usd"])

    def test_insights_empty_structures(self):
        body = self.client.get(INSIGHTS, headers=self.world.headers).json()
        self.assertIn("volume", body["conversations_detail"])
        self.assertIn("frequency", body["patients_detail"])
        self.assertEqual(body["knowledge"]["documents"], 0)

    def test_breakdown_invalid_dimension(self):
        resp = self.client.get(
            BREAKDOWN + "?dimension=revenue", headers=self.world.headers
        )
        self.assertEqual(resp.status_code, 400)

    def test_breakdown_service_and_insurance(self):
        now = timezone.now()
        self.world.create_row(
            start_time=now,
            end_time=now + timedelta(minutes=30),
            insurance_plan=self.world.insurance,
        )
        service = self.client.get(
            BREAKDOWN + "?dimension=service&range=30d", headers=self.world.headers
        ).json()
        insurance = self.client.get(
            BREAKDOWN + "?dimension=insurance&range=30d", headers=self.world.headers
        ).json()
        self.assertIn("Consult", [row["label"] for row in service["items"]])
        self.assertIn("Aetna", [row["label"] for row in insurance["items"]])


class AnalyticsCalendarTests(TestCase):
    def setUp(self):
        self.world = AppointmentWorld(slug="cal-a", email="cal-a@test.com")
        self.other_user, self.other_clinic, self.other_headers = make_clinic_admin(
            email="cal-b@test.com", clinic_slug="cal-b"
        )

    def test_empty_clinic_returns_empty_days(self):
        resp = self.client.get(CALENDAR + "?year=2026&month=8", headers=self.world.headers)
        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()
        self.assertEqual(body["year"], 2026)
        self.assertEqual(body["month"], 8)
        self.assertEqual(body["days"], [])
        self.assertEqual(body["upcoming"], [])
        self.assertEqual(body["timezone"], "America/Los_Angeles")
        self.assertTrue(body["today"])

    def test_invalid_month_rejected(self):
        resp = self.client.get(CALENDAR + "?year=2026&month=13", headers=self.world.headers)
        self.assertEqual(resp.status_code, 400)

    def test_tenant_isolation(self):
        when = datetime(2026, 8, 20, 15, 0, tzinfo=LA)
        self.world.create_row(start_time=when, end_time=when + timedelta(minutes=30))
        mine = self.client.get(CALENDAR + "?year=2026&month=8", headers=self.world.headers).json()
        other = self.client.get(CALENDAR + "?year=2026&month=8", headers=self.other_headers).json()
        self.assertEqual(sum(row["count"] for row in mine["days"]), 1)
        self.assertEqual(other["days"], [])

    def test_clinic_timezone_day_bucket(self):
        # 21 Aug 2026 01:00 UTC = 20 Aug 2026 18:00 America/Los_Angeles
        when = datetime(2026, 8, 21, 1, 0, tzinfo=ZoneInfo("UTC"))
        self.world.create_row(start_time=when, end_time=when + timedelta(minutes=30))
        body = self.client.get(CALENDAR + "?year=2026&month=8", headers=self.world.headers).json()
        by_day = {row["date"]: row["count"] for row in body["days"]}
        self.assertEqual(by_day.get("2026-08-20"), 1)
        self.assertNotIn("2026-08-21", by_day)

    def test_day_count_and_cancelled_excluded(self):
        day = datetime(2026, 8, 12, 10, 0, tzinfo=LA)
        self.world.create_row(start_time=day, end_time=day + timedelta(minutes=30))
        self.world.create_row(
            start_time=day + timedelta(hours=1),
            end_time=day + timedelta(hours=1, minutes=30),
            confirmation_code=unique_code(),
            patient=self.world.patient_b,
        )
        self.world.create_row(
            start_time=day + timedelta(hours=2),
            end_time=day + timedelta(hours=2, minutes=30),
            status=AppointmentStatus.CANCELLED,
            confirmation_code=unique_code(),
            doctor=self.world.doctor_b,
        )
        body = self.client.get(CALENDAR + "?year=2026&month=8", headers=self.world.headers).json()
        by_day = {row["date"]: row["count"] for row in body["days"]}
        self.assertEqual(by_day.get("2026-08-12"), 2)

    def test_upcoming_includes_patient_name(self):
        now = timezone.now()
        future = now + timedelta(days=2)
        self.world.create_row(start_time=future, end_time=future + timedelta(minutes=30))
        body = self.client.get(CALENDAR, headers=self.world.headers).json()
        self.assertGreaterEqual(len(body["upcoming"]), 1)
        self.assertEqual(body["upcoming"][0]["patient_name"], "Pat Alpha")
        self.assertEqual(body["upcoming"][0]["doctor_name"], "Dr. Alpha")
        self.assertEqual(body["upcoming"][0]["service_name"], "Consult")

    def test_unauthenticated_rejected(self):
        self.assertEqual(self.client.get(CALENDAR).status_code, 401)
