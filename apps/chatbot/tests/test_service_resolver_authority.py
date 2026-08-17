"""Phase 4: SQL handlers must defer to the planner-authorized service match
(ExecutionPlan.resolved_service_ids -> SQLContext.resolved_service_ids)
instead of re-matching the message themselves. The legacy in-handler
matcher (_match_services_strict) stays only as a fallback for call sites
that bypass the planner (e.g. SQLTool.run) — see sql_tool/handlers/services.py.
"""

from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase

from apps.chatbot.nlu.schemas import ExtractedEntities, Intent, NLUResult, ResolvedIds
from apps.chatbot.sql_tool.base import SQLContext
from apps.chatbot.sql_tool.handlers.services import services_offered
from apps.clinics.models import Clinic
from apps.services.models import Service


def _nlu(mode: str, intent: Intent = Intent.SERVICES_OFFERED) -> NLUResult:
    return NLUResult(
        intent=intent,
        confidence=0.9,
        entities=ExtractedEntities(),
        resolved_ids=ResolvedIds(),
        needs_sql=True,
        service_filter_mode=mode,
    )


class ServiceResolverAuthorityTests(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="resolver-authority-clinic",
            name="Resolver Authority Clinic",
            email="resolver-authority@clinic.com",
            phone="+12125550020",
            timezone="America/New_York",
        )
        self.laser = Service.objects.create(
            clinic=self.clinic, name="Laser Hair Removal", duration_min=45, price_cents=15000
        )
        self.botox = Service.objects.create(
            clinic=self.clinic,
            name="Botox / Dysport Wrinkle Treatment",
            duration_min=30,
            price_cents=50000,
        )
        self.peel = Service.objects.create(
            clinic=self.clinic, name="Chemical Peel Facial", duration_min=30, price_cents=12000
        )

    def test_resolved_service_ids_take_precedence_in_category_mode(self):
        # Message is deliberately generic — _match_services_strict alone
        # would find no distinctive tokens and leave the query unfiltered
        # (all 3 services). resolved_service_ids being set must still
        # narrow the result to exactly the authorized service.
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=_nlu("category"),
            message="tell me about your special treatments",
            resolved_service_ids=[str(self.laser.id)],
        )
        result = services_offered(ctx)
        names = [r["name"] for r in result.rows]
        self.assertEqual(names, ["Laser Hair Removal"])

    def test_resolved_service_ids_take_precedence_in_named_mode_fallback(self):
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=_nlu("named"),
            message="tell me about your special treatments",
            resolved_service_ids=[str(self.peel.id)],
        )
        result = services_offered(ctx)
        names = [r["name"] for r in result.rows]
        self.assertEqual(names, ["Chemical Peel Facial"])

    def test_empty_resolved_service_ids_falls_back_to_strict_matcher(self):
        # No resolved_service_ids (defaults to []) — behavior must be
        # identical to before this phase: the legacy in-handler matcher
        # still runs and still finds "Laser Hair Removal" from the message.
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=_nlu("category"),
            message="do you offer laser hair removal",
        )
        result = services_offered(ctx)
        names = [r["name"] for r in result.rows]
        self.assertIn("Laser Hair Removal", names)
        self.assertNotIn("Botox / Dysport Wrinkle Treatment", names)

    @patch("apps.chatbot.sql_tool.handlers.services._match_services_strict")
    def test_nonempty_resolved_service_ids_skips_legacy_matcher_entirely(self, mock_strict):
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=_nlu("category"),
            message="tell me about your special treatments",
            resolved_service_ids=[str(self.botox.id)],
        )
        services_offered(ctx)
        mock_strict.assert_not_called()

    @patch("apps.chatbot.sql_tool.handlers.services._match_services_strict")
    def test_empty_resolved_service_ids_still_calls_legacy_matcher(self, mock_strict):
        mock_strict.return_value = []
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=_nlu("category"),
            message="tell me about your special treatments",
        )
        services_offered(ctx)
        mock_strict.assert_called_once()


class LegacyMatcherCatalogLimitTests(TestCase):
    """Phase 6 audit finding: _match_services_strict is NOT provably
    redundant with resolved_service_ids (Algorithm 1) despite the two
    matching *algorithms* agreeing on every message tried empirically.
    They read from different data: resolved_service_ids comes from
    match_services_in_message() against build_service_catalog(clinic,
    limit=40) — capped, alphabetical. _match_services_strict queries
    Service.objects directly with no cap. For a clinic with more than 40
    active services, a service sorted past #40 is invisible to the
    planner's resolver entirely (never even a candidate), but still
    reachable by the legacy handler-local fallback. This is why Phase 6
    does not delete _match_services_strict — see the phase report.
    """

    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="catalog-limit-clinic",
            name="Catalog Limit Clinic",
            email="catalog-limit@clinic.com",
            phone="+12125550040",
            timezone="America/New_York",
        )
        # 45 services, alphabetically named so the target service sorts
        # well past build_service_catalog's limit=40 cutoff.
        for i in range(45):
            Service.objects.create(
                clinic=self.clinic,
                name=f"Service {i:02d} Zzzoloft Screening" if i == 44 else f"Service {i:02d} Filler",
                duration_min=20,
                price_cents=5000,
            )
        self.late_service = Service.objects.get(name="Service 44 Zzzoloft Screening")

    def test_capped_catalog_cannot_see_the_service_at_all(self):
        from apps.chatbot.routing.doc_catalog import build_service_catalog
        from apps.chatbot.routing.signals import match_services_in_message

        catalog = build_service_catalog(self.clinic)
        self.assertEqual(len(catalog), 40)
        self.assertNotIn(str(self.late_service.id), {c["id"] for c in catalog})

        hits = match_services_in_message("do you offer zzzoloft screening", catalog)
        self.assertEqual(hits, [])

    def test_legacy_matcher_still_finds_it_via_fresh_unlimited_query(self):
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=_nlu("category"),
            message="do you offer zzzoloft screening",
            # Simulates what the planner would actually compute for this
            # clinic: empty, because match_services_in_message never saw
            # this service in its capped catalog in the first place.
            resolved_service_ids=[],
        )
        result = services_offered(ctx)
        names = [r["name"] for r in result.rows]
        self.assertIn("Service 44 Zzzoloft Screening", names)
