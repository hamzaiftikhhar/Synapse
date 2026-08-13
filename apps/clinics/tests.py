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

    def test_get_profile_includes_saved_clinic_type(self):
        self.clinic.clinic_type = "cardiology"
        self.clinic.save(update_fields=["clinic_type"])
        resp = self.client.get("/api/v1/clinics/me", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["clinic_type"], "cardiology")

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

    def test_get_returns_no_rows_when_unset(self):
        """GET no longer synthesizes 7 placeholder rows — it reflects
        exactly what's been saved, same as DoctorSchedule."""
        resp = self.client.get("/api/v1/clinics/me/business-hours", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), [])

    def test_put_replaces_and_apply_to_weekdays(self):
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

    def test_put_is_a_full_replace(self):
        """A second PUT with a smaller payload drops rows that weren't
        resent — same delete+recreate contract as DoctorSchedule."""
        first = [{"day_of_week": d, "open_time": "09:00:00", "close_time": "17:00:00"} for d in range(7)]
        self.client.put(
            "/api/v1/clinics/me/business-hours",
            data=first,
            content_type="application/json",
            headers=self.headers,
        )
        second = [{"day_of_week": 0, "open_time": "09:00:00", "close_time": "17:00:00"}]
        resp = self.client.put(
            "/api/v1/clinics/me/business-hours",
            data=second,
            content_type="application/json",
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(ClinicBusinessHours.objects.filter(clinic=self.clinic).count(), 1)


class BusinessHoursMultiIntervalTests(TestCase):
    """Split-shift business hours (e.g. a lunch closure) — multiple
    ClinicBusinessHours rows per day are now allowed."""

    def setUp(self):
        self.user, self.clinic, self.headers = make_clinic_admin(
            email="owner@splitshift.test", clinic_slug="split-shift-clinic"
        )

    def _put(self, payload):
        return self.client.put(
            "/api/v1/clinics/me/business-hours",
            data=payload,
            content_type="application/json",
            headers=self.headers,
        )

    def test_multiple_intervals_same_day_accepted(self):
        payload = [
            {"day_of_week": 0, "open_time": "08:00:00", "close_time": "13:00:00"},
            {"day_of_week": 0, "open_time": "13:30:00", "close_time": "17:00:00"},
        ]
        resp = self._put(payload)
        self.assertEqual(resp.status_code, 200, resp.content)
        rows = ClinicBusinessHours.objects.filter(clinic=self.clinic, day_of_week=0).order_by(
            "open_time"
        )
        self.assertEqual(rows.count(), 2)
        self.assertEqual(str(rows[0].close_time), "13:00:00")
        self.assertEqual(str(rows[1].open_time), "13:30:00")

    def test_overlapping_intervals_rejected(self):
        payload = [
            {"day_of_week": 0, "open_time": "08:00:00", "close_time": "13:00:00"},
            {"day_of_week": 0, "open_time": "12:30:00", "close_time": "17:00:00"},
        ]
        resp = self._put(payload)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("overlap", resp.json()["detail"].lower())

    def test_duplicate_intervals_rejected_as_overlap(self):
        payload = [
            {"day_of_week": 0, "open_time": "08:00:00", "close_time": "13:00:00"},
            {"day_of_week": 0, "open_time": "08:00:00", "close_time": "13:00:00"},
        ]
        resp = self._put(payload)
        self.assertEqual(resp.status_code, 400)

    def test_end_before_start_rejected(self):
        resp = self._put([{"day_of_week": 0, "open_time": "13:00:00", "close_time": "08:00:00"}])
        self.assertEqual(resp.status_code, 400)

    def test_closed_and_open_same_day_rejected(self):
        payload = [
            {"day_of_week": 0, "is_closed": True},
            {"day_of_week": 0, "open_time": "08:00:00", "close_time": "13:00:00"},
        ]
        resp = self._put(payload)
        self.assertEqual(resp.status_code, 400)

    def test_get_returns_flat_real_rows(self):
        self._put(
            [
                {"day_of_week": 0, "open_time": "08:00:00", "close_time": "13:00:00"},
                {"day_of_week": 0, "open_time": "13:30:00", "close_time": "17:00:00"},
            ]
        )
        resp = self.client.get("/api/v1/clinics/me/business-hours", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(len(body), 2)
        self.assertTrue(all("id" in row for row in body))

    def test_onboarding_checklist_still_true_with_multi_interval_day(self):
        self._put(
            [
                {"day_of_week": 0, "open_time": "08:00:00", "close_time": "13:00:00"},
                {"day_of_week": 0, "open_time": "13:30:00", "close_time": "17:00:00"},
            ]
        )
        resp = self.client.get("/api/v1/clinics/me/onboarding-status", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["checklist"]["hours"])

    def test_cannot_write_another_clinics_business_hours(self):
        _, other_clinic, other_headers = make_clinic_admin(
            email="owner2@othersplit.test", clinic_slug="other-split-clinic"
        )
        self._put([{"day_of_week": 0, "open_time": "08:00:00", "close_time": "17:00:00"}])
        resp = self.client.put(
            "/api/v1/clinics/me/business-hours",
            data=[{"day_of_week": 0, "open_time": "09:00:00", "close_time": "10:00:00"}],
            content_type="application/json",
            headers=other_headers,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(ClinicBusinessHours.objects.filter(clinic=self.clinic).count(), 1)
        self.assertEqual(ClinicBusinessHours.objects.filter(clinic=other_clinic).count(), 1)


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
        body = resp.json()
        self.assertTrue(body["ready"])
        self.assertEqual(body["counts"]["insurance_plans"], 0)

    def test_ready_without_insurance_plans(self):
        self._make_ready()
        resp = self.client.post(
            "/api/v1/clinics/me/onboarding/complete", headers=self.headers
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "active")

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


class OnboardingBillingGateTests(TestCase):
    """A clinic provisioned from a paid application must not go `active`
    on checklist-completion alone — it waits for a verified Paddle webhook
    (see apps/billing/services/activation.py). Plain self-serve clinics
    (no Subscription row) keep the original immediate-activation behavior,
    covered by OnboardingStatusTests above."""

    def setUp(self):
        self.user, self.clinic, self.headers = make_clinic_admin(
            email="owner@paid.test", clinic_slug="paid-clinic", clinic_name="Paid Clinic"
        )
        self.clinic.clinic_type = "dermatology"
        self.clinic.phone = "555-0100"
        self.clinic.address = {
            "line1": "1 Main St", "city": "New York", "state": "NY",
            "postal_code": "10001", "country": "US",
        }
        self.clinic.save()
        doctor = Doctor.objects.create(clinic=self.clinic, full_name="Dr. Ready")
        Service.objects.create(clinic=self.clinic, name="Consultation", duration_min=30)
        ClinicBusinessHours.objects.create(
            clinic=self.clinic, day_of_week=0, open_time="09:00", close_time="17:00"
        )
        DoctorSchedule.objects.create(
            clinic=self.clinic, doctor=doctor, day_of_week=0,
            start_time="09:00", end_time="17:00",
        )

    def test_complete_with_pending_subscription_stays_onboarding(self):
        from apps.billing.models import Plan, Subscription

        plan = Plan.objects.create(slug="starter", name="Starter")
        Subscription.objects.create(clinic=self.clinic, plan=plan)  # default: INCOMPLETE

        resp = self.client.post(
            "/api/v1/clinics/me/onboarding/complete", headers=self.headers
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "onboarding")
        self.assertEqual(resp.json()["onboarding_step"], "billing")
        self.clinic.refresh_from_db()
        self.assertEqual(self.clinic.status, ClinicStatus.ONBOARDING)
        self.assertIsNone(self.clinic.onboarding_completed_at)

    def test_complete_with_already_active_subscription_activates_immediately(self):
        from apps.billing.models import Plan, Subscription, SubscriptionStatus

        plan = Plan.objects.create(slug="starter", name="Starter")
        Subscription.objects.create(
            clinic=self.clinic, plan=plan, status=SubscriptionStatus.ACTIVE
        )

        resp = self.client.post(
            "/api/v1/clinics/me/onboarding/complete", headers=self.headers
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "active")
        self.clinic.refresh_from_db()
        self.assertEqual(self.clinic.status, ClinicStatus.ACTIVE)
