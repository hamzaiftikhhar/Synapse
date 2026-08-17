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


class CategoryModeResolvedIdAuthorityTests(TestCase):
    """Phase 5: category mode must give resolved_ids.service_id (Algorithm 2,
    NLU entity -> DB fuzzy match) the same priority the mode == "named"
    branch already gives it, instead of losing a confidently resolved
    service behind a raw entities.service icontains that can silently
    match zero rows for a paraphrase (e.g. "laser treatment" isn't a
    literal substring of any real service name)."""

    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="category-resolved-id-clinic",
            name="Category Resolved ID Clinic",
            email="category-resolved-id@clinic.com",
            phone="+12125550030",
            timezone="America/New_York",
        )
        self.laser = Service.objects.create(
            clinic=self.clinic, name="Laser Hair Removal", duration_min=45, price_cents=15000
        )
        self.resurfacing = Service.objects.create(
            clinic=self.clinic, name="Laser Skin Resurfacing", duration_min=40, price_cents=30000
        )
        Service.objects.create(
            clinic=self.clinic,
            name="Botox / Dysport Wrinkle Treatment",
            duration_min=30,
            price_cents=50000,
        )

    def _nlu(self, *, service_id: str | None = None, entity_service: str | None = None) -> NLUResult:
        return NLUResult(
            intent=Intent.SERVICES_OFFERED,
            confidence=0.9,
            entities=ExtractedEntities(service=entity_service),
            resolved_ids=ResolvedIds(service_id=service_id),
            needs_sql=True,
            service_filter_mode="category",
        )

    def test_resolved_id_wins_despite_paraphrase_that_icontains_would_miss(self):
        # "laser treatment" is not a literal substring of either laser
        # service's name — the old code's name__icontains=entities.service
        # branch would have matched zero rows here.
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=self._nlu(service_id=str(self.laser.id), entity_service="laser treatment"),
            message="how much is laser treatment",
        )
        result = services_offered(ctx)
        names = [r["name"] for r in result.rows]
        self.assertEqual(names, ["Laser Hair Removal"])
        self.assertTrue(result.found)

    def test_resolved_id_wins_over_disagreeing_message_resolver(self):
        # The raw message matches BOTH laser services via the message
        # resolver (Algorithm 1, ExecutionPlan.resolved_service_ids) —
        # that's what makes mode == "category" in the first place.
        # resolved_ids.service_id (Algorithm 2) confidently picked just
        # one of them; that must still win.
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=self._nlu(service_id=str(self.resurfacing.id)),
            message="tell me about your laser services",
            resolved_service_ids=[str(self.laser.id), str(self.resurfacing.id)],
        )
        result = services_offered(ctx)
        names = [r["name"] for r in result.rows]
        self.assertEqual(names, ["Laser Skin Resurfacing"])

    def test_no_resolved_id_paraphrase_falls_through_to_message_resolver(self):
        # No resolved_ids.service_id this time. entities.service is still a
        # paraphrase, but category mode no longer attempts an icontains
        # against it at all — it falls straight through to the
        # planner-authorized resolved_service_ids (Algorithm 1, grounded in
        # the real message text) instead of silently returning zero rows.
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=self._nlu(entity_service="laser treatment"),
            message="how much is laser hair removal",
            resolved_service_ids=[str(self.laser.id)],
        )
        result = services_offered(ctx)
        names = [r["name"] for r in result.rows]
        self.assertEqual(names, ["Laser Hair Removal"])
