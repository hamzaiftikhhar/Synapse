"""Owner invite acceptance — POST /auth/accept-invite."""

from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import ClinicStaff, StaffAuthToken, StaffAuthTokenPurpose, UserRole
from apps.api.test_helpers import make_clinic_admin
from apps.billing.models import Plan, Subscription, SubscriptionStatus
from apps.clinics.models import Clinic, ClinicStatus

User = get_user_model()
URL = "/api/v1/auth/accept-invite"


class AcceptInviteTests(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="invited-clinic", name="Invited Clinic", email="owner@invited.example.com",
            status=ClinicStatus.ONBOARDING,
        )
        self.owner = User.objects.create_user(
            username="invitedowner", email="owner@invited.example.com",
            role=UserRole.CLINIC_ADMIN, is_clinic_owner=True, is_active=False,
        )
        ClinicStaff.objects.create(user=self.owner, clinic=self.clinic, is_active=True)
        self.row, self.raw_token = StaffAuthToken.issue(
            user=self.owner, purpose=StaffAuthTokenPurpose.INVITE, ttl_hours=24 * 7
        )

    def test_valid_invite_activates_and_logs_in_scoped_to_clinic(self):
        resp = self.client.post(
            URL, data={"token": self.raw_token, "password": "BrandNewPass1!"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["clinic"]["slug"], self.clinic.slug)
        self.assertTrue(body["access_token"])

        self.owner.refresh_from_db()
        self.assertTrue(self.owner.is_active)
        self.assertTrue(self.owner.check_password("BrandNewPass1!"))
        self.assertIsNotNone(self.owner.email_verified_at)

        self.row.refresh_from_db()
        self.assertIsNotNone(self.row.used_at)

    def test_token_is_one_time_use(self):
        self.client.post(
            URL, data={"token": self.raw_token, "password": "BrandNewPass1!"},
            content_type="application/json",
        )
        resp = self.client.post(
            URL, data={"token": self.raw_token, "password": "AnotherPass2!"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_expired_token_rejected(self):
        self.row.expires_at = timezone.now() - timedelta(hours=1)
        self.row.save(update_fields=["expires_at"])
        resp = self.client.post(
            URL, data={"token": self.raw_token, "password": "BrandNewPass1!"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
        self.owner.refresh_from_db()
        self.assertFalse(self.owner.is_active)

    def test_wrong_purpose_token_rejected(self):
        _, raw = StaffAuthToken.issue(
            user=self.owner, purpose=StaffAuthTokenPurpose.PASSWORD_RESET, ttl_hours=2
        )
        resp = self.client.post(
            URL, data={"token": raw, "password": "BrandNewPass1!"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_garbage_token_rejected(self):
        resp = self.client.post(
            URL, data={"token": "not-a-real-token", "password": "BrandNewPass1!"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_weak_password_rejected(self):
        resp = self.client.post(
            URL, data={"token": self.raw_token, "password": "short"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
        self.owner.refresh_from_db()
        self.assertFalse(self.owner.is_active)

    def test_invited_owner_cannot_see_another_clinics_data_via_token(self):
        """The invite only ever resolves through this owner's own ClinicStaff
        row — there is no field in the request an attacker could supply to
        redirect the session to a different clinic."""
        other_clinic = Clinic.objects.create(
            slug="other-clinic", name="Other Clinic", email="x@other.example.com",
        )
        ClinicStaff.objects.create(user=self.owner, clinic=other_clinic, is_active=False)

        resp = self.client.post(
            URL, data={"token": self.raw_token, "password": "BrandNewPass1!"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        # Only the active membership (the real invited clinic) is honored.
        self.assertEqual(resp.json()["clinic"]["slug"], self.clinic.slug)


class AuthEndpointRateLimitTests(TestCase):
    """login/register/forgot-password are unauthenticated and public —
    the only thing standing between them and credential-stuffing / signup
    spam / inbox-bombing is core.ratelimit."""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def test_login_rate_limited_per_email_before_touching_credentials(self):
        # Deliberately wrong credentials — proves the limiter fires before/
        # regardless of whether authentication itself would have succeeded.
        payload = {"email": "nobody@example.com", "password": "wrong"}
        for _ in range(10):
            resp = self.client.post(
                "/api/v1/auth/login", data=payload, content_type="application/json"
            )
            self.assertEqual(resp.status_code, 401)
        resp = self.client.post(
            "/api/v1/auth/login", data=payload, content_type="application/json"
        )
        self.assertEqual(resp.status_code, 429)

    def test_login_rate_limit_is_scoped_per_email_not_global(self):
        # Distinct simulated IPs isolate the per-email dimension from the
        # per-IP one — both limiters are real and would otherwise interfere.
        for _ in range(10):
            self.client.post(
                "/api/v1/auth/login",
                data={"email": "a@example.com", "password": "wrong"},
                content_type="application/json",
                headers={"X-Forwarded-For": "10.0.0.1"},
            )
        # A different email, from a different IP, must not be blocked by
        # a's exhausted per-email budget.
        resp = self.client.post(
            "/api/v1/auth/login",
            data={"email": "b@example.com", "password": "wrong"},
            content_type="application/json",
            headers={"X-Forwarded-For": "10.0.0.2"},
        )
        self.assertEqual(resp.status_code, 401)  # not 429

    def test_register_rate_limited_per_ip(self):
        for i in range(5):
            resp = self.client.post(
                "/api/v1/auth/register",
                data={
                    "email": f"newuser{i}@example.com",
                    "password": "Sup3rSecret1!",
                    "first_name": "New",
                    "last_name": "User",
                },
                content_type="application/json",
            )
            self.assertEqual(resp.status_code, 200)
        resp = self.client.post(
            "/api/v1/auth/register",
            data={
                "email": "onemore@example.com",
                "password": "Sup3rSecret1!",
                "first_name": "New",
                "last_name": "User",
            },
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 429)

    def test_forgot_password_rate_limited_and_still_never_reveals_existence(self):
        payload = {"email": "maybe-exists@example.com"}
        for _ in range(5):
            resp = self.client.post(
                "/api/v1/auth/forgot-password", data=payload, content_type="application/json"
            )
            self.assertEqual(resp.status_code, 200)
            self.assertIn("If an account exists", resp.json()["message"])
        resp = self.client.post(
            "/api/v1/auth/forgot-password", data=payload, content_type="application/json"
        )
        self.assertEqual(resp.status_code, 429)


class BillingAccessEnforcementTests(TestCase):
    """Subscription.access_status is enforced on every authenticated
    request via StaffJWTAuth.authenticate() (apps/api/auth/deps.py), not
    just at login — a JWT issued before a subscription went bad still gets
    blocked on its very next use."""

    def setUp(self):
        self.user, self.clinic, self.headers = make_clinic_admin(
            email="owner@billing-enforce.example.com", clinic_slug="billing-enforce-clinic"
        )
        self.plan = Plan.objects.create(slug="enforce-plan", name="Enforce Plan")

    def test_no_subscription_at_all_is_never_blocked(self):
        """Preserves current behavior for clinics without billing set up
        (super-admin-created clinics, seed/demo data) — confirmed no
        Subscription row exists for this clinic via make_clinic_admin."""
        self.assertFalse(Subscription.objects.filter(clinic=self.clinic).exists())
        resp = self.client.get("/api/v1/auth/me", headers=self.headers)
        self.assertEqual(resp.status_code, 200)

    def test_active_subscription_is_not_blocked(self):
        Subscription.objects.create(
            clinic=self.clinic, plan=self.plan, status=SubscriptionStatus.ACTIVE,
        )
        resp = self.client.get("/api/v1/auth/me", headers=self.headers)
        self.assertEqual(resp.status_code, 200)

    def test_incomplete_subscription_is_not_blocked(self):
        """Regression: a clinic mid-onboarding (checkout not confirmed yet)
        must be able to keep using its own account to finish checkout —
        this was originally broken (401) before access_status correctly
        excluded INCOMPLETE from SUSPENDED."""
        Subscription.objects.create(
            clinic=self.clinic, plan=self.plan, status=SubscriptionStatus.INCOMPLETE,
        )
        resp = self.client.get("/api/v1/auth/me", headers=self.headers)
        self.assertEqual(resp.status_code, 200)

    def test_grace_period_is_not_blocked(self):
        Subscription.objects.create(
            clinic=self.clinic, plan=self.plan, status=SubscriptionStatus.PAST_DUE,
            grace_period_started_at=timezone.now(),
        )
        resp = self.client.get("/api/v1/auth/me", headers=self.headers)
        self.assertEqual(resp.status_code, 200)

    def test_grace_period_exhausted_is_blocked(self):
        Subscription.objects.create(
            clinic=self.clinic, plan=self.plan, status=SubscriptionStatus.PAST_DUE,
            grace_period_started_at=timezone.now() - timedelta(days=30),
        )
        resp = self.client.get("/api/v1/auth/me", headers=self.headers)
        self.assertEqual(resp.status_code, 401)

    def test_canceled_subscription_is_blocked(self):
        Subscription.objects.create(
            clinic=self.clinic, plan=self.plan, status=SubscriptionStatus.CANCELED,
        )
        resp = self.client.get("/api/v1/auth/me", headers=self.headers)
        self.assertEqual(resp.status_code, 401)

    def test_paused_subscription_is_blocked(self):
        Subscription.objects.create(
            clinic=self.clinic, plan=self.plan, status=SubscriptionStatus.PAUSED,
        )
        resp = self.client.get("/api/v1/auth/me", headers=self.headers)
        self.assertEqual(resp.status_code, 401)

    def test_clinic_status_suspension_still_works_independently_of_billing(self):
        """Confirms this change is additive — the pre-existing, unrelated
        Clinic.status-based suspension path (used by super admin for
        non-billing reasons) is untouched."""
        self.clinic.status = ClinicStatus.SUSPENDED
        self.clinic.save(update_fields=["status"])
        resp = self.client.get("/api/v1/auth/me", headers=self.headers)
        self.assertEqual(resp.status_code, 401)
