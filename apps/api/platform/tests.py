"""Super Admin application review/provisioning — GET/approve/reject."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.models import ClinicStaff, StaffAuthToken, StaffAuthTokenPurpose, UserRole
from apps.api.auth.jwt import create_staff_access_token
from apps.api.test_helpers import make_clinic_admin
from apps.billing.models import Plan, Subscription, SubscriptionStatus
from apps.clinics.models import (
    Clinic,
    ClinicApplication,
    ClinicApplicationSource,
    ClinicApplicationStatus,
    ClinicStatus,
)

User = get_user_model()


def make_super_admin(*, email: str) -> tuple:
    user = User.objects.create_user(
        username=email.split("@")[0], email=email, password="Sup3rSecret!",
        role=UserRole.SUPER_ADMIN, is_active=True,
    )
    token = create_staff_access_token(user_id=user.id, role=user.role, tenant=None, clinic_id=None)
    return user, {"Authorization": f"Bearer {token}"}


class ApplicationReviewAuthzTests(TestCase):
    def setUp(self):
        self.plan = Plan.objects.create(slug="growth", name="Growth", is_active=True)
        self.app = ClinicApplication.objects.create(
            clinic_name="Test Clinic", owner_name="Owner Name",
            work_email="owner@testclinic.example.com", plan_slug="growth",
        )

    def test_non_super_admin_cannot_list_applications(self):
        _, _, headers = make_clinic_admin(email="staff@x.test", clinic_slug="staff-x-clinic")
        resp = self.client.get("/api/v1/platform/applications", headers=headers)
        self.assertEqual(resp.status_code, 403)

    def test_non_super_admin_cannot_approve(self):
        _, _, headers = make_clinic_admin(email="staff2@x.test", clinic_slug="staff2-x-clinic")
        resp = self.client.post(
            f"/api/v1/platform/applications/{self.app.id}/approve",
            data={}, content_type="application/json", headers=headers,
        )
        self.assertEqual(resp.status_code, 403)
        self.app.refresh_from_db()
        self.assertEqual(self.app.status, ClinicApplicationStatus.PENDING)

    def test_unauthenticated_cannot_approve(self):
        resp = self.client.post(
            f"/api/v1/platform/applications/{self.app.id}/approve",
            data={}, content_type="application/json",
        )
        self.assertEqual(resp.status_code, 401)


class ApplicationApprovalProvisioningTests(TestCase):
    def setUp(self):
        self.plan = Plan.objects.create(slug="growth", name="Growth", is_active=True)
        self.admin, self.admin_headers = make_super_admin(email="root@synapse.test")
        self.app = ClinicApplication.objects.create(
            clinic_name="Beula Medical Family Clinic", owner_name="Ali Hamza",
            work_email="ali@beula.example.com", plan_slug="growth",
        )

    def test_approve_provisions_clinic_owner_and_subscription(self):
        resp = self.client.post(
            f"/api/v1/platform/applications/{self.app.id}/approve",
            data={}, content_type="application/json", headers=self.admin_headers,
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["application"]["status"], "converted")
        clinic_id = body["clinic"]["id"]

        clinic = Clinic.objects.get(id=clinic_id)
        self.assertEqual(clinic.status, ClinicStatus.ONBOARDING)
        self.assertEqual(clinic.name, "Beula Medical Family Clinic")

        owner = User.objects.get(email="ali@beula.example.com")
        self.assertTrue(owner.is_clinic_owner)
        self.assertFalse(owner.is_active)  # not active until invite accepted
        self.assertTrue(
            ClinicStaff.objects.filter(user=owner, clinic=clinic, is_active=True).exists()
        )

        sub = Subscription.objects.get(clinic=clinic)
        self.assertEqual(sub.plan_id, self.plan.id)
        self.assertEqual(sub.status, SubscriptionStatus.INCOMPLETE)
        self.assertFalse(sub.has_access)

        self.app.refresh_from_db()
        self.assertEqual(self.app.status, ClinicApplicationStatus.CONVERTED)
        self.assertEqual(self.app.converted_clinic_id, clinic.id)
        self.assertIsNotNone(self.app.reviewed_at)
        self.assertEqual(self.app.reviewed_by_id, self.admin.id)

        invite = StaffAuthToken.objects.filter(
            user=owner, purpose=StaffAuthTokenPurpose.INVITE
        ).first()
        self.assertIsNotNone(invite)
        self.assertTrue(invite.is_valid)

    def test_approve_twice_rejected(self):
        self.client.post(
            f"/api/v1/platform/applications/{self.app.id}/approve",
            data={}, content_type="application/json", headers=self.admin_headers,
        )
        resp = self.client.post(
            f"/api/v1/platform/applications/{self.app.id}/approve",
            data={}, content_type="application/json", headers=self.admin_headers,
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(Clinic.objects.count(), 1)  # no duplicate provisioning

    def test_approve_with_unavailable_plan_rejected(self):
        self.plan.is_active = False
        self.plan.save()
        resp = self.client.post(
            f"/api/v1/platform/applications/{self.app.id}/approve",
            data={}, content_type="application/json", headers=self.admin_headers,
        )
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(Clinic.objects.exists())

    def test_approving_two_applications_does_not_collide_on_subscription(self):
        """Regression: Subscription.paddle_subscription_id is unique=True —
        two clinics provisioned before either has a real Paddle subscription
        must not both get "" (which Postgres treats as equal, unlike NULL)."""
        second_app = ClinicApplication.objects.create(
            clinic_name="Second Clinic", owner_name="Second Owner",
            work_email="second@example.com", plan_slug="starter",
        )
        Plan.objects.create(slug="starter", name="Starter", is_active=True)

        resp1 = self.client.post(
            f"/api/v1/platform/applications/{self.app.id}/approve",
            data={}, content_type="application/json", headers=self.admin_headers,
        )
        resp2 = self.client.post(
            f"/api/v1/platform/applications/{second_app.id}/approve",
            data={}, content_type="application/json", headers=self.admin_headers,
        )
        self.assertEqual(resp1.status_code, 200)
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(Subscription.objects.count(), 2)
        for sub in Subscription.objects.all():
            self.assertIsNone(sub.paddle_subscription_id)

    def test_reject_sets_reason_and_status(self):
        resp = self.client.post(
            f"/api/v1/platform/applications/{self.app.id}/reject",
            data={"reason": "Not a good fit at this time"},
            content_type="application/json", headers=self.admin_headers,
        )
        self.assertEqual(resp.status_code, 200)
        self.app.refresh_from_db()
        self.assertEqual(self.app.status, ClinicApplicationStatus.REJECTED)
        self.assertEqual(self.app.rejection_reason, "Not a good fit at this time")
        self.assertFalse(Clinic.objects.exists())

    def test_reject_then_approve_rejected(self):
        self.client.post(
            f"/api/v1/platform/applications/{self.app.id}/reject",
            data={"reason": "no"}, content_type="application/json", headers=self.admin_headers,
        )
        resp = self.client.post(
            f"/api/v1/platform/applications/{self.app.id}/approve",
            data={}, content_type="application/json", headers=self.admin_headers,
        )
        self.assertEqual(resp.status_code, 400)


class DemoRequestApprovalTests(TestCase):
    """A demo request has no plan_slug of its own — approval must accept
    one in the request body rather than assuming/guessing a default."""

    def setUp(self):
        self.plan = Plan.objects.create(slug="growth", name="Growth", is_active=True)
        self.admin, self.admin_headers = make_super_admin(email="root2@synapse.test")
        self.app = ClinicApplication.objects.create(
            clinic_name="Riverside Dental", owner_name="Sam Rivera",
            work_email="sam@riverside.example.com", plan_slug="",
            source=ClinicApplicationSource.DEMO_REQUEST,
        )

    def test_approve_without_a_plan_is_rejected_with_a_clear_message(self):
        resp = self.client.post(
            f"/api/v1/platform/applications/{self.app.id}/approve",
            data={}, content_type="application/json", headers=self.admin_headers,
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("plan", resp.json()["detail"].lower())
        self.assertFalse(Clinic.objects.exists())

    def test_approve_with_plan_slug_override_provisions_correctly(self):
        resp = self.client.post(
            f"/api/v1/platform/applications/{self.app.id}/approve",
            data={"plan_slug": "growth"}, content_type="application/json",
            headers=self.admin_headers,
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["application"]["status"], "converted")
        clinic = Clinic.objects.get(id=body["clinic"]["id"])
        sub = Subscription.objects.get(clinic=clinic)
        self.assertEqual(sub.plan_id, self.plan.id)

    def test_approve_with_unknown_plan_slug_override_rejected(self):
        resp = self.client.post(
            f"/api/v1/platform/applications/{self.app.id}/approve",
            data={"plan_slug": "does-not-exist"}, content_type="application/json",
            headers=self.admin_headers,
        )
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(Clinic.objects.exists())


class PlatformOpsTests(TestCase):
    def setUp(self):
        self.admin, self.admin_headers = make_super_admin(email="ops@synapse.test")
        self.owner, self.clinic, self.owner_headers = make_clinic_admin(
            email="owner@ops.test", clinic_slug="ops-clinic"
        )
        Plan.objects.get_or_create(
            slug="starter",
            defaults={"name": "Starter", "is_active": True, "display_price_cents": 2900},
        )

    def test_clinic_owner_cannot_list_users(self):
        resp = self.client.get("/api/v1/platform/users", headers=self.owner_headers)
        self.assertEqual(resp.status_code, 403)

    def test_list_users_includes_owner(self):
        resp = self.client.get("/api/v1/platform/users", headers=self.admin_headers)
        self.assertEqual(resp.status_code, 200)
        emails = {u["email"] for u in resp.json()}
        self.assertIn("owner@ops.test", emails)

    def test_invite_staff_creates_membership(self):
        resp = self.client.post(
            "/api/v1/platform/users/invite",
            data={
                "email": "front@ops.test",
                "first_name": "Front",
                "clinic_id": str(self.clinic.id),
                "role": "STAFF",
            },
            content_type="application/json",
            headers=self.admin_headers,
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()
        self.assertEqual(body["email"], "front@ops.test")
        self.assertEqual(body["role"], "STAFF")
        self.assertTrue(
            ClinicStaff.objects.filter(user__email="front@ops.test", clinic=self.clinic).exists()
        )

    def test_cannot_deactivate_self(self):
        resp = self.client.patch(
            f"/api/v1/platform/users/{self.admin.id}",
            data={"is_active": False},
            content_type="application/json",
            headers=self.admin_headers,
        )
        self.assertEqual(resp.status_code, 400)

    def test_subscriptions_and_plans_list(self):
        plan = Plan.objects.get(slug="starter")
        Subscription.objects.create(clinic=self.clinic, plan=plan)
        subs = self.client.get("/api/v1/platform/subscriptions", headers=self.admin_headers)
        self.assertEqual(subs.status_code, 200)
        self.assertTrue(any(s["clinic_slug"] == "ops-clinic" for s in subs.json()))
        plans = self.client.get("/api/v1/platform/plans", headers=self.admin_headers)
        self.assertEqual(plans.status_code, 200)
        self.assertTrue(any(p["slug"] == "starter" for p in plans.json()))

    def test_patch_plan_updates_price(self):
        plan = Plan.objects.get(slug="starter")
        resp = self.client.patch(
            f"/api/v1/platform/plans/{plan.id}",
            data={"display_price_cents": 4900, "name": "Starter+"},
            content_type="application/json",
            headers=self.admin_headers,
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        plan.refresh_from_db()
        self.assertEqual(plan.display_price_cents, 4900)
        self.assertEqual(plan.name, "Starter+")

    def test_audit_and_settings_and_monitoring(self):
        audit = self.client.get("/api/v1/platform/audit", headers=self.admin_headers)
        self.assertEqual(audit.status_code, 200)
        settings_resp = self.client.get("/api/v1/platform/settings", headers=self.admin_headers)
        self.assertEqual(settings_resp.status_code, 200)
        self.assertIn("integrations", settings_resp.json())
        mon = self.client.get("/api/v1/platform/ai-monitoring", headers=self.admin_headers)
        self.assertEqual(mon.status_code, 200)
        self.assertIn("avg_latency_ms", mon.json())

    def test_documents_list(self):
        resp = self.client.get("/api/v1/platform/documents", headers=self.admin_headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), [])

    def test_patch_me(self):
        resp = self.client.patch(
            "/api/v1/auth/me",
            data={"first_name": "Root", "last_name": "Admin", "phone_number": "555-0100"},
            content_type="application/json",
            headers=self.admin_headers,
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()["first_name"], "Root")
        self.assertEqual(resp.json()["phone_number"], "555-0100")
