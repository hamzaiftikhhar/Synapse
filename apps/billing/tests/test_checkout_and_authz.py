"""Checkout security, owner authorization, tenant isolation."""

from __future__ import annotations

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from apps.accounts.models import ClinicStaff, UserRole
from apps.api.auth.jwt import create_staff_access_token
from apps.api.test_helpers import make_clinic_admin
from apps.billing.models import Plan, Subscription, SubscriptionStatus

User = get_user_model()

PLANS_URL = "/api/v1/billing/plans"
SUBSCRIPTION_URL = "/api/v1/billing/subscription"
CHECKOUT_URL = "/api/v1/billing/checkout"
CANCEL_URL = "/api/v1/billing/subscription/cancel"
RESUME_URL = "/api/v1/billing/subscription/resume"
CHANGE_PLAN_URL = "/api/v1/billing/subscription/change-plan"


def _non_owner_headers(*, clinic, email: str) -> dict:
    user = User.objects.create_user(
        username=email.split("@")[0], email=email, password="Sup3rSecret!",
        role=UserRole.STAFF, is_clinic_owner=False, is_active=True,
    )
    ClinicStaff.objects.create(user=user, clinic=clinic, is_active=True)
    token = create_staff_access_token(
        user_id=user.id, role=user.role, tenant=clinic.slug, clinic_id=clinic.id
    )
    return {"Authorization": f"Bearer {token}"}


@override_settings(PADDLE_API_KEY="test-key", PADDLE_ENVIRONMENT="sandbox")
class CheckoutSecurityTests(TestCase):
    def setUp(self):
        self.user, self.clinic, self.headers = make_clinic_admin(
            email="owner@example.com", clinic_slug="checkout-clinic"
        )
        self.plan = Plan.objects.create(
            slug="starter", name="Starter", paddle_price_id_sandbox="pri_starter_sandbox",
        )

    def test_client_cannot_supply_authoritative_price_id(self):
        """The checkout schema has no price_id field at all — a client
        trying to smuggle one in the body has no effect; the server always
        resolves the price from the local Plan row."""
        with patch(
            "apps.billing.services.paddle_client.create_customer", return_value="ctm_new"
        ) as mock_create:
            resp = self.client.post(
                CHECKOUT_URL,
                data={"plan_slug": "starter", "paddle_price_id": "pri_evil_free_plan"},
                content_type="application/json",
                headers=self.headers,
            )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["paddle_price_id"], "pri_starter_sandbox")
        mock_create.assert_called_once()

    def test_checkout_creates_incomplete_subscription_and_customer(self):
        with patch(
            "apps.billing.services.paddle_client.create_customer", return_value="ctm_new"
        ):
            resp = self.client.post(
                CHECKOUT_URL, data={"plan_slug": "starter"},
                content_type="application/json", headers=self.headers,
            )
        self.assertEqual(resp.status_code, 200)
        sub = Subscription.objects.get(clinic=self.clinic)
        self.assertEqual(sub.status, SubscriptionStatus.INCOMPLETE)
        self.assertEqual(sub.paddle_customer_id, "ctm_new")

    def test_checkout_without_paddle_configured_returns_503(self):
        with override_settings(PADDLE_API_KEY=""):
            resp = self.client.post(
                CHECKOUT_URL, data={"plan_slug": "starter"},
                content_type="application/json", headers=self.headers,
            )
        self.assertEqual(resp.status_code, 503)

    def test_non_owner_cannot_checkout(self):
        headers = _non_owner_headers(clinic=self.clinic, email="staff@example.com")
        resp = self.client.post(
            CHECKOUT_URL, data={"plan_slug": "starter"},
            content_type="application/json", headers=headers,
        )
        self.assertEqual(resp.status_code, 403)


@override_settings(PADDLE_API_KEY="test-key", PADDLE_ENVIRONMENT="sandbox")
class CancelAndChangePlanAuthzTests(TestCase):
    def setUp(self):
        self.user, self.clinic, self.headers = make_clinic_admin(
            email="owner2@example.com", clinic_slug="cancel-clinic"
        )
        self.plan = Plan.objects.create(
            slug="starter", name="Starter", paddle_price_id_sandbox="pri_starter_sandbox",
        )
        self.growth_plan = Plan.objects.create(
            slug="growth", name="Growth", paddle_price_id_sandbox="pri_growth_sandbox",
        )
        self.sub = Subscription.objects.create(
            clinic=self.clinic, plan=self.plan, paddle_customer_id="ctm_x",
            paddle_subscription_id="sub_x", status=SubscriptionStatus.ACTIVE,
        )

    def test_non_owner_cannot_cancel(self):
        headers = _non_owner_headers(clinic=self.clinic, email="staff2@example.com")
        resp = self.client.post(
            CANCEL_URL, data={"at_period_end": True},
            content_type="application/json", headers=headers,
        )
        self.assertEqual(resp.status_code, 403)

    def test_non_owner_cannot_change_plan(self):
        headers = _non_owner_headers(clinic=self.clinic, email="staff3@example.com")
        resp = self.client.post(
            CHANGE_PLAN_URL, data={"plan_slug": "growth"},
            content_type="application/json", headers=headers,
        )
        self.assertEqual(resp.status_code, 403)

    def test_cancel_at_period_end_does_not_mutate_local_status(self):
        """Webhook is authoritative — the cancel endpoint calling Paddle
        successfully must not itself flip Subscription.status. Access must
        remain until the webhook confirms the actual cancellation."""
        with patch(
            "apps.billing.services.paddle_client.cancel_subscription",
            return_value={"status": "active"},
        ) as mock_cancel:
            resp = self.client.post(
                CANCEL_URL, data={"at_period_end": True},
                content_type="application/json", headers=self.headers,
            )
        self.assertEqual(resp.status_code, 200)
        mock_cancel.assert_called_once_with("sub_x", at_period_end=True)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, SubscriptionStatus.ACTIVE)
        self.assertTrue(self.sub.has_access)

    def test_plan_change_does_not_mutate_local_plan_before_webhook(self):
        with patch(
            "apps.billing.services.paddle_client.change_subscription_price",
            return_value={"status": "active"},
        ) as mock_change:
            resp = self.client.post(
                CHANGE_PLAN_URL, data={"plan_slug": "growth"},
                content_type="application/json", headers=self.headers,
            )
        self.assertEqual(resp.status_code, 200)
        mock_change.assert_called_once_with("sub_x", price_id="pri_growth_sandbox")
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.plan_id, self.plan.id)  # unchanged — still starter

    def test_immediate_cancel_calls_paddle_with_at_period_end_false(self):
        with patch(
            "apps.billing.services.paddle_client.cancel_subscription",
            return_value={"status": "canceled"},
        ) as mock_cancel:
            resp = self.client.post(
                CANCEL_URL, data={"at_period_end": False},
                content_type="application/json", headers=self.headers,
            )
        self.assertEqual(resp.status_code, 200)
        mock_cancel.assert_called_once_with("sub_x", at_period_end=False)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, SubscriptionStatus.ACTIVE)

    def test_resume_clears_paddle_scheduled_change_without_local_mutate(self):
        self.sub.cancel_at_period_end = True
        self.sub.save(update_fields=["cancel_at_period_end"])
        with patch(
            "apps.billing.services.paddle_client.clear_scheduled_change",
            return_value={"status": "active", "scheduled_change": None},
        ) as mock_clear:
            resp = self.client.post(
                RESUME_URL, data={},
                content_type="application/json", headers=self.headers,
            )
        self.assertEqual(resp.status_code, 200)
        mock_clear.assert_called_once_with("sub_x")
        self.sub.refresh_from_db()
        self.assertTrue(self.sub.cancel_at_period_end)

    def test_non_owner_cannot_resume(self):
        headers = _non_owner_headers(clinic=self.clinic, email="staff4@example.com")
        resp = self.client.post(
            RESUME_URL, data={},
            content_type="application/json", headers=headers,
        )
        self.assertEqual(resp.status_code, 403)


@override_settings(PADDLE_API_KEY="test-key", PADDLE_ENVIRONMENT="sandbox")
class TenantIsolationTests(TestCase):
    def setUp(self):
        self.owner_a, self.clinic_a, self.headers_a = make_clinic_admin(
            email="ownera@example.com", clinic_slug="clinic-a"
        )
        self.owner_b, self.clinic_b, self.headers_b = make_clinic_admin(
            email="ownerb@example.com", clinic_slug="clinic-b"
        )
        self.plan = Plan.objects.create(slug="starter", name="Starter", paddle_price_id_sandbox="pri_a")
        self.sub_b = Subscription.objects.create(
            clinic=self.clinic_b, plan=self.plan, paddle_customer_id="ctm_b",
            paddle_subscription_id="sub_b", status=SubscriptionStatus.ACTIVE,
        )

    def test_clinic_a_sees_no_subscription_for_itself_not_clinic_b(self):
        resp = self.client.get(SUBSCRIPTION_URL, headers=self.headers_a)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["status"], "incomplete")  # clinic A has no subscription
        self.assertNotEqual(body.get("plan"), self.sub_b.plan_id)

    def test_clinic_a_cannot_cancel_clinic_bs_subscription(self):
        """clinic_from(request) derives the clinic strictly from clinic A's
        own JWT — there is no request field that could ever target clinic
        B's subscription, so this asserts clinic A's own (nonexistent)
        subscription is what's acted on, never clinic B's."""
        with patch("apps.billing.services.paddle_client.cancel_subscription") as mock_cancel:
            resp = self.client.post(
                CANCEL_URL, data={"at_period_end": True},
                content_type="application/json", headers=self.headers_a,
            )
        self.assertEqual(resp.status_code, 400)  # clinic A has no active subscription
        mock_cancel.assert_not_called()
        self.sub_b.refresh_from_db()
        self.assertEqual(self.sub_b.status, SubscriptionStatus.ACTIVE)
