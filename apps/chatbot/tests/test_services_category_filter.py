"""services_offered() category-mode fallback fix (Phase 2): previously any
category term outside a hardcoded 5-phrase list ("urgent care", "primary
care", "well child", "cancer screening", "physical") silently returned the
entire unfiltered catalog — e.g. "what laser services do you have" surfaced
Botox/filler/acne services too. Now falls back to the existing, clinic-agnostic
_match_services_strict() instead of returning everything."""

from __future__ import annotations

from django.test import TestCase

from apps.chatbot.nlu.schemas import ExtractedEntities, Intent, NLUResult, ResolvedIds
from apps.chatbot.sql_tool.base import SQLContext
from apps.chatbot.sql_tool.handlers.services import services_offered
from apps.clinics.models import Clinic
from apps.services.models import Service


def _category_nlu(intent: Intent = Intent.SERVICES_OFFERED) -> NLUResult:
    return NLUResult(
        intent=intent,
        confidence=0.9,
        entities=ExtractedEntities(),
        resolved_ids=ResolvedIds(),
        needs_sql=True,
        service_filter_mode="category",
    )


class ServicesCategoryFilterTests(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="services-category-clinic",
            name="Services Category Clinic",
            email="services-category@clinic.com",
            phone="+12125550010",
            timezone="America/New_York",
        )
        Service.objects.create(
            clinic=self.clinic, name="Laser Hair Removal", duration_min=45, price_cents=15000
        )
        Service.objects.create(
            clinic=self.clinic,
            name="Botox / Dysport Wrinkle Treatment",
            duration_min=30,
            price_cents=50000,
        )
        Service.objects.create(
            clinic=self.clinic, name="Chemical Peel Facial", duration_min=30, price_cents=12000
        )

    def test_uncategorized_term_no_longer_returns_full_catalog(self):
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=_category_nlu(),
            message="do you offer laser hair removal",
        )
        result = services_offered(ctx)
        names = [r["name"] for r in result.rows]
        self.assertIn("Laser Hair Removal", names)
        self.assertNotIn("Botox / Dysport Wrinkle Treatment", names)
        self.assertNotIn("Chemical Peel Facial", names)

    def test_hardcoded_phrase_still_works(self):
        Service.objects.create(
            clinic=self.clinic, name="Annual Physical Exam", duration_min=20, price_cents=8000
        )
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=_category_nlu(),
            message="do you offer a physical",
        )
        result = services_offered(ctx)
        names = [r["name"] for r in result.rows]
        self.assertIn("Annual Physical Exam", names)

    def test_no_signal_at_all_still_browses_full_catalog(self):
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=_category_nlu(),
            message="what do you have available",
        )
        result = services_offered(ctx)
        names = [r["name"] for r in result.rows]
        self.assertEqual(len(names), 3)

    def test_row_includes_price_cents_and_category(self):
        nlu = NLUResult(
            intent=Intent.SERVICES_OFFERED,
            confidence=0.9,
            entities=ExtractedEntities(),
            resolved_ids=ResolvedIds(),
            needs_sql=True,
            service_filter_mode="none",
        )
        ctx = SQLContext(clinic=self.clinic, nlu=nlu, message="")
        result = services_offered(ctx)
        row = next(r for r in result.rows if r["name"] == "Laser Hair Removal")
        self.assertEqual(row["price_cents"], 15000)
        self.assertIn("category", row)
