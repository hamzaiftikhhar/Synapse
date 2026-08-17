"""AI usage analytics + pricing + authz."""

from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.ai.models import AIOperation, AIProvider, AIUsageLog
from apps.ai.pricing import estimate_usd
from apps.api.platform.tests import make_super_admin
from apps.api.test_helpers import make_clinic_admin


class PricingTests(TestCase):
    def test_gpt_41_nano_matches_openai_list_price(self):
        # 1M input + 1M output → $0.10 + $0.40
        self.assertAlmostEqual(
            estimate_usd(model="gpt-4.1-nano", prompt_tokens=1_000_000, completion_tokens=1_000_000),
            0.50,
        )

    def test_gpt_41_mini_matches_openai_list_price(self):
        self.assertAlmostEqual(
            estimate_usd(model="gpt-4.1-mini", prompt_tokens=1_000_000, completion_tokens=1_000_000),
            2.00,
        )

    def test_embedding_has_no_output_rate(self):
        self.assertAlmostEqual(
            estimate_usd(
                model="text-embedding-3-small",
                prompt_tokens=1_000_000,
                completion_tokens=50_000,
            ),
            0.02,
        )

    def test_unknown_model_is_zero(self):
        self.assertEqual(
            estimate_usd(model="mystery-model", prompt_tokens=10_000, completion_tokens=10_000),
            0.0,
        )


class ClinicAnalyticsAuthzTests(TestCase):
    def setUp(self):
        self.owner, self.clinic, self.headers = make_clinic_admin(
            email="owner@analytics.test", clinic_slug="analytics-clinic"
        )
        _, self.other, self.other_headers = make_clinic_admin(
            email="other@analytics.test", clinic_slug="analytics-other"
        )
        self.admin, self.admin_headers = make_super_admin(email="root@analytics.test")
        now = timezone.now()
        a = AIUsageLog.objects.create(
            clinic=self.clinic,
            provider=AIProvider.OPENAI,
            operation=AIOperation.INTENT_CLASSIFICATION,
            model="gpt-4.1-nano",
            prompt_tokens=10_000,
            completion_tokens=2_000,
            total_tokens=12_000,
            latency_ms=80,
        )
        b = AIUsageLog.objects.create(
            clinic=self.other,
            provider=AIProvider.OPENAI,
            operation=AIOperation.INTENT_CLASSIFICATION,
            model="gpt-4.1-mini",
            prompt_tokens=5_000,
            completion_tokens=1_000,
            total_tokens=6_000,
            latency_ms=120,
        )
        AIUsageLog.objects.filter(id=a.id).update(created_at=now - timedelta(days=1))
        AIUsageLog.objects.filter(id=b.id).update(created_at=now - timedelta(days=1))

    def test_clinic_owner_sees_tokens_not_cost(self):
        resp = self.client.get("/api/v1/analytics", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["total_tokens"], 12_000)
        self.assertFalse(body["show_cost"])
        self.assertIsNone(body["estimated_usd"])
        self.assertEqual(body["rates"], [])
        self.assertIsNone(body["models"][0]["estimated_usd"])
        self.assertEqual(body["models"][0]["model"], "gpt-4.1-nano")

    def test_clinic_owner_cannot_see_other_clinic_tokens(self):
        resp = self.client.get("/api/v1/analytics", headers=self.headers)
        self.assertEqual(resp.json()["total_tokens"], 12_000)
        other = self.client.get("/api/v1/analytics", headers=self.other_headers)
        self.assertEqual(other.json()["total_tokens"], 6_000)

    def test_clinic_owner_cannot_hit_platform_ai_usage(self):
        resp = self.client.get("/api/v1/platform/ai-usage", headers=self.headers)
        self.assertEqual(resp.status_code, 403)

    def test_unauthenticated_rejected(self):
        self.assertEqual(self.client.get("/api/v1/analytics").status_code, 401)

    def test_super_admin_platform_sees_per_clinic_cost(self):
        resp = self.client.get("/api/v1/platform/ai-usage", headers=self.admin_headers)
        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()
        self.assertEqual(body["total_tokens"], 18_000)
        self.assertGreater(body["estimated_usd"], 0)
        slugs = {c["slug"]: c for c in body["clinics"]}
        self.assertIn("analytics-clinic", slugs)
        self.assertIn("analytics-other", slugs)
        nano_cost = estimate_usd(model="gpt-4.1-nano", prompt_tokens=10_000, completion_tokens=2_000)
        mini_cost = estimate_usd(model="gpt-4.1-mini", prompt_tokens=5_000, completion_tokens=1_000)
        self.assertAlmostEqual(slugs["analytics-clinic"]["estimated_usd"], nano_cost, places=6)
        self.assertAlmostEqual(slugs["analytics-other"]["estimated_usd"], mini_cost, places=6)
        self.assertTrue(any(r["model"] == "gpt-4.1-nano" for r in body["rates"]))
