"""apps.billing.services.activation.maybe_activate_clinic — the one place
billing state is allowed to flip Clinic.status, and only under an explicit,
narrow rule."""

from __future__ import annotations

from django.test import TestCase

from apps.billing.models import Plan, Subscription, SubscriptionStatus
from apps.billing.services.activation import maybe_activate_clinic
from apps.clinics.models import ClinicBusinessHours, ClinicStatus
from apps.clinics.models import Clinic
from apps.doctors.models import Doctor, DoctorSchedule
from apps.services.models import Service


class ActivationTests(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="activation-clinic", name="Activation Clinic",
            email="owner@activation.example.com", status=ClinicStatus.ONBOARDING,
        )
        self.plan = Plan.objects.create(slug="growth", name="Growth")
        self.sub = Subscription.objects.create(clinic=self.clinic, plan=self.plan)

    def _make_checklist_ready(self):
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

    def test_payment_confirmed_and_checklist_ready_activates_clinic(self):
        self._make_checklist_ready()
        self.sub.status = SubscriptionStatus.ACTIVE
        self.sub.save(update_fields=["status"])

        maybe_activate_clinic(self.sub)

        self.clinic.refresh_from_db()
        self.assertEqual(self.clinic.status, ClinicStatus.ACTIVE)
        self.assertIsNotNone(self.clinic.onboarding_completed_at)

    def test_payment_confirmed_but_checklist_not_ready_stays_onboarding(self):
        # Deliberately skip _make_checklist_ready() — no doctors/services/hours.
        self.sub.status = SubscriptionStatus.ACTIVE
        self.sub.save(update_fields=["status"])

        maybe_activate_clinic(self.sub)

        self.clinic.refresh_from_db()
        self.assertEqual(self.clinic.status, ClinicStatus.ONBOARDING)

    def test_payment_not_confirmed_stays_onboarding_even_if_checklist_ready(self):
        self._make_checklist_ready()
        # sub.status stays default INCOMPLETE

        maybe_activate_clinic(self.sub)

        self.clinic.refresh_from_db()
        self.assertEqual(self.clinic.status, ClinicStatus.ONBOARDING)

    def test_activates_with_multi_interval_business_hours(self):
        """ClinicBusinessHours now allows multiple rows per day (e.g. a
        lunch closure) — activation's readiness check is a plain
        `.exists()` on non-closed rows, so it must still work unchanged."""
        self._make_checklist_ready()
        ClinicBusinessHours.objects.create(
            clinic=self.clinic, day_of_week=0, open_time="13:30", close_time="17:00"
        )
        self.sub.status = SubscriptionStatus.ACTIVE
        self.sub.save(update_fields=["status"])

        maybe_activate_clinic(self.sub)

        self.clinic.refresh_from_db()
        self.assertEqual(self.clinic.status, ClinicStatus.ACTIVE)

    def test_already_active_clinic_is_untouched(self):
        self._make_checklist_ready()
        self.clinic.status = ClinicStatus.ACTIVE
        self.clinic.save(update_fields=["status"])
        self.sub.status = SubscriptionStatus.ACTIVE
        self.sub.save(update_fields=["status"])

        # Should be a no-op — not re-stamp onboarding_completed_at again.
        maybe_activate_clinic(self.sub)

        self.clinic.refresh_from_db()
        self.assertEqual(self.clinic.status, ClinicStatus.ACTIVE)
        self.assertIsNone(self.clinic.onboarding_completed_at)
