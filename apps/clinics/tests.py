from django.test import TestCase

from apps.api.test_helpers import make_clinic_admin, make_verified_owner
from apps.clinics.models import ClinicBusinessHours, ClinicStatus
from apps.doctors.models import Doctor, DoctorSchedule
from apps.services.models import Service


class CreateClinicEndpointTests(TestCase):
    """POST /auth/clinics — regression coverage for a bug where decorating
    the ninja view with @transaction.atomic broke Django Ninja's request
    body resolution (`QueryParams is not fully defined`), 500-ing every
    clinic-creation attempt regardless of payload."""

    def test_verified_owner_can_create_clinic(self):
        _, headers = make_verified_owner(email="new-owner@example.test")
        resp = self.client.post(
            "/api/v1/auth/clinics",
            data={"name": "Fresh Start Clinic", "slug": "fresh-start-clinic"},
            content_type="application/json",
            headers=headers,
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()
        self.assertEqual(body["slug"], "fresh-start-clinic")
        self.assertEqual(body["status"], "onboarding")

    def test_duplicate_slug_rejected(self):
        _, headers = make_verified_owner(email="dup-owner@example.test")
        payload = {"name": "Dup Clinic", "slug": "dup-clinic"}
        first = self.client.post(
            "/api/v1/auth/clinics", data=payload, content_type="application/json", headers=headers
        )
        self.assertEqual(first.status_code, 200)
        _, headers2 = make_verified_owner(email="dup-owner-2@example.test")
        second = self.client.post(
            "/api/v1/auth/clinics", data=payload, content_type="application/json", headers=headers2
        )
        self.assertEqual(second.status_code, 400)


class ClinicProfileTests(TestCase):
    def setUp(self):
        self.user, self.clinic, self.headers = make_clinic_admin(
            email="owner@lumina.test", clinic_slug="lumina-derm ", clinic_name="Lumina Derm"
        )

    def test_get_profile(self):
        resp = self.client.get("/api/v1/clinics/me", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["name"], "Lumina Derm")
        self.assertEqual(resp.json()["status"], "onboarding")
        self.assertEqual(resp.json()["onboarding_step"], "")

    def test_patch_profile_updates_fields_and_step(self):
        resp = self.client.patch(
            "/api/v1/clinics/me",
            data={
                "clinic_type": "dermatology",
                "phone": "555-0100",
                "address": {
                    "line1": "1 Main St",
                    "city": "New York",
                    "state": "NY",
                    "postal_code": "10001",
                    "country": "US",
                },
                "onboarding_step": "location",
            },
            content_type="application/json",
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["clinic_type"], "dermatology")
        self.assertEqual(body["onboarding_step"], "location")
        self.clinic.refresh_from_db()
        self.assertEqual(self.clinic.address["city"], "New York")

    def test_patch_rejects_unknown_clinic_type(self):
        resp = self.client.patch(
            "/api/v1/clinics/me",
            data={"clinic_type": "not-a-real-type"},
            content_type="application/json",
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 400)

    def test_patch_rejects_blank_name(self):
        resp = self.client.patch(
            "/api/v1/clinics/me",
            data={"name": "   "},
            content_type="application/json",
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 400)

    def test_patch_rejects_oversized_onboarding_step(self):
        resp = self.client.patch(
            "/api/v1/clinics/me",
            data={"onboarding_step": "x" * 64},
            content_type="application/json",
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 400)

    def test_patch_rejects_invalid_onboarding_step_characters(self):
        resp = self.client.patch(
            "/api/v1/clinics/me",
            data={"onboarding_step": "not a valid slug!"},
            content_type="application/json",
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 400)

    def test_cannot_access_another_clinics_profile(self):
        _, _, other_headers = make_clinic_admin(
            email="owner2@other.test", clinic_slug="other-clinic"
        )
        resp = self.client.get("/api/v1/clinics/me", headers=other_headers)
        self.assertEqual(resp.status_code, 200)
        self.assertNotEqual(resp.json()["slug"], self.clinic.slug)


class BusinessHoursTests(TestCase):
    def setUp(self):
        self.user, self.clinic, self.headers = make_clinic_admin(
            email="owner@hours.test", clinic_slug="hours-clinic"
        )

    def test_get_returns_all_seven_days_with_defaults(self):
        resp = self.client.get("/api/v1/clinics/me/business-hours", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(len(body), 7)
        self.assertEqual({row["day_of_week"] for row in body}, set(range(7)))

    def test_put_upserts_and_apply_to_weekdays(self):
        payload = [
            {"day_of_week": d, "open_time": "09:00:00", "close_time": "17:00:00", "is_closed": False}
            for d in range(5)
        ] + [
            {"day_of_week": 5, "is_closed": True},
            {"day_of_week": 6, "is_closed": True},
        ]
        resp = self.client.put(
            "/api/v1/clinics/me/business-hours",
            data=payload,
            content_type="application/json",
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(ClinicBusinessHours.objects.filter(clinic=self.clinic).count(), 7)
        monday = ClinicBusinessHours.objects.get(clinic=self.clinic, day_of_week=0)
        self.assertEqual(str(monday.open_time), "09:00:00")
        saturday = ClinicBusinessHours.objects.get(clinic=self.clinic, day_of_week=5)
        self.assertTrue(saturday.is_closed)

    def test_put_rejects_bad_day(self):
        resp = self.client.put(
            "/api/v1/clinics/me/business-hours",
            data=[{"day_of_week": 9, "is_closed": True}],
            content_type="application/json",
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 400)


class WidgetSettingsTests(TestCase):
    def setUp(self):
        self.user, self.clinic, self.headers = make_clinic_admin(
            email="owner@widget.test", clinic_slug="widget-clinic"
        )

    def test_get_creates_defaults(self):
        resp = self.client.get("/api/v1/clinics/me/widget-settings", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        config = resp.json()["configuration"]
        self.assertEqual(config["booking"]["lead_time_hours"], 24)

    def test_patch_shallow_merges_booking(self):
        self.client.get("/api/v1/clinics/me/widget-settings", headers=self.headers)
        resp = self.client.patch(
            "/api/v1/clinics/me/widget-settings",
            data={"configuration": {"booking": {"lead_time_hours": 48}}},
            content_type="application/json",
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 200)
        config = resp.json()["configuration"]
        self.assertEqual(config["booking"]["lead_time_hours"], 48)
        # Untouched keys survive the merge
        self.assertIn("verification_mode", config["booking"])
        self.assertIn("widget", config)


class OnboardingStatusTests(TestCase):
    def setUp(self):
        self.user, self.clinic, self.headers = make_clinic_admin(
            email="owner@ready.test", clinic_slug="ready-clinic", clinic_name="Ready Clinic"
        )

    def test_not_ready_when_empty(self):
        resp = self.client.get("/api/v1/clinics/me/onboarding-status", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body["ready"])
        self.assertFalse(body["checklist"]["providers"])

    def test_complete_blocked_with_human_message(self):
        resp = self.client.post(
            "/api/v1/clinics/me/onboarding/complete", headers=self.headers
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("clinic", resp.json()["detail"].lower())

    def _make_ready(self):
        self.clinic.clinic_type = "dermatology"
        self.clinic.phone = "555-0100"
        self.clinic.address = {
            "line1": "1 Main St",
            "city": "New York",
            "state": "NY",
            "postal_code": "10001",
            "country": "US",
        }
        self.clinic.save()
        doctor = Doctor.objects.create(clinic=self.clinic, full_name="Dr. Chloe Bennett")
        Service.objects.create(clinic=self.clinic, name="Consultation", duration_min=30)
        ClinicBusinessHours.objects.create(
            clinic=self.clinic, day_of_week=0, open_time="09:00", close_time="17:00"
        )
        DoctorSchedule.objects.create(
            clinic=self.clinic,
            doctor=doctor,
            day_of_week=0,
            start_time="09:00",
            end_time="17:00",
        )
        return doctor

    def test_ready_when_minimum_requirements_met(self):
        self._make_ready()
        resp = self.client.get("/api/v1/clinics/me/onboarding-status", headers=self.headers)
        self.assertTrue(resp.json()["ready"])

    def test_complete_flips_status_and_sets_completed_at(self):
        self._make_ready()
        resp = self.client.post(
            "/api/v1/clinics/me/onboarding/complete", headers=self.headers
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "active")
        self.assertIsNotNone(resp.json()["onboarding_completed_at"])
        self.clinic.refresh_from_db()
        self.assertEqual(self.clinic.status, ClinicStatus.ACTIVE)
        self.assertIsNotNone(self.clinic.onboarding_completed_at)

    def test_unauthenticated_request_rejected(self):
        resp = self.client.get("/api/v1/clinics/me/onboarding-status")
        self.assertEqual(resp.status_code, 401)
