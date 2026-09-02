"""Phase 50 — compound-message entity scoping.

Root cause (verified live, not assumed): search_doctors, insurance_accepted,
and services_offered each applied resolved_ids.doctor_id (and, for
search_doctors, resolved_ids.service_id) as an unconditional "bonus"
narrowing filter — correct for a genuine single-clause message ("does Dr.
Smith accept Aetna"), wrong the moment the entity actually belongs to a
different clause of a compound message. Confirmed with real data: a doctor
who accepts none of the clinic's Aetna plans made "do you accept aetna and
is dr X available tomorrow" answer "not accepted" for a clinic that does
accept Aetna; a doctor who doesn't perform a service made "how much is X
and is dr Y available" answer "no services found" for a real, priced
service.

The fix (planner._compute_blocked_entity_fields) is a single, table-driven,
intent-shape-based mechanism computed once in the planner and consulted by
each handler via a two-line guard — not per-handler hardcoded logic.

The "poison doctor" pattern used throughout: a doctor who explicitly does
NOT accept a plan / perform a service the clinic otherwise does, so a
passing test can only mean the contamination genuinely didn't happen — not
that the poisoned and correct answers coincidentally matched.
"""

from __future__ import annotations

from dataclasses import replace

from django.test import TestCase

from apps.chatbot.nlu.resolvers import resolve_entities
from apps.chatbot.nlu.schemas import Intent, parse_nlu_payload
from apps.chatbot.planner import (
    _compute_blocked_entity_fields,
    build_execution_plan,
    build_planner_facts,
)
from apps.chatbot.sql_tool.service import SQLTool
from apps.clinics.models import Clinic
from apps.doctors.models import Doctor, DoctorInsurance, DoctorService
from apps.insurance.models import InsurancePlan
from apps.services.models import Service


def _nlu(intent, secondary_intents, entities, **extra):
    payload = {
        "intent": intent,
        "secondary_intents": secondary_intents,
        "confidence": 0.9,
        "entities": entities,
    }
    payload.update(extra)
    return parse_nlu_payload(payload)


class ComputeBlockedEntityFieldsUnitTests(TestCase):
    """Pure function, no DB — tests the tier/priority logic directly."""

    def test_single_intent_never_blocks_anything(self):
        nlu = _nlu("insurance_verification", [], {"insurance_provider": "Aetna", "doctor_name": "Smith"})
        self.assertEqual(_compute_blocked_entity_fields(nlu), {})

    def test_no_entity_value_never_blocks_anything(self):
        nlu = _nlu("insurance_verification", ["doctor_availability"], {"insurance_provider": "Aetna"})
        self.assertEqual(_compute_blocked_entity_fields(nlu), {})

    def test_insurance_blocked_from_doctor_when_booking_present(self):
        nlu = _nlu(
            "insurance_verification", ["book_appointment"],
            {"insurance_provider": "Aetna", "doctor_name": "Vance"},
        )
        blocked = _compute_blocked_entity_fields(nlu)
        self.assertIn("doctor_id", blocked.get("insurance", frozenset()))

    def test_insurance_blocked_from_doctor_when_availability_present(self):
        nlu = _nlu(
            "insurance_accepted", ["doctor_availability"],
            {"insurance_provider": "Aetna", "doctor_name": "Vance"},
        )
        blocked = _compute_blocked_entity_fields(nlu)
        self.assertIn("doctor_id", blocked.get("insurance", frozenset()))

    def test_services_and_pricing_both_blocked_from_doctor(self):
        nlu = _nlu(
            "pricing", ["book_appointment"],
            {"service": "Physical", "doctor_name": "Whitaker"},
        )
        blocked = _compute_blocked_entity_fields(nlu)
        self.assertIn("doctor_id", blocked.get("services", frozenset()))
        self.assertIn("doctor_id", blocked.get("pricing", frozenset()))

    def test_doctors_task_blocked_from_doctor_when_booking_present(self):
        """The self-contamination case: DOCTOR_SEARCH primary, doctor named
        only to anchor a secondary book_appointment."""
        nlu = _nlu("doctor_search", ["book_appointment"], {"doctor_name": "Vance"})
        blocked = _compute_blocked_entity_fields(nlu)
        self.assertIn("doctor_id", blocked.get("doctors", frozenset()))

    def test_doctors_task_blocked_from_service_when_pricing_present(self):
        nlu = _nlu("doctor_search", ["pricing"], {"service": "Strep Test"})
        blocked = _compute_blocked_entity_fields(nlu)
        self.assertIn("service_id", blocked.get("doctors", frozenset()))

    def test_availability_never_blocked_from_its_own_doctor(self):
        """doctor_availability is always the top-priority owner of a named
        doctor — it must never have its own doctor scope withheld."""
        nlu = _nlu(
            "insurance_verification", ["doctor_availability"],
            {"insurance_provider": "Aetna", "doctor_name": "Vance"},
        )
        blocked = _compute_blocked_entity_fields(nlu)
        self.assertNotIn("availability", blocked)

    def test_single_clause_doctor_specific_insurance_not_blocked(self):
        """"does Dr. Smith accept Aetna" — no competing intent present at
        all, so the doctor genuinely belongs to the only intent asking."""
        nlu = _nlu("insurance_verification", [], {"insurance_provider": "Aetna", "doctor_name": "Smith"})
        blocked = _compute_blocked_entity_fields(nlu)
        self.assertNotIn("insurance", blocked)

    def test_three_intent_blocks_every_non_winning_task(self):
        nlu = _nlu(
            "multi_intent",
            ["insurance_verification", "pricing", "doctor_search"],
            {"insurance_provider": "Aetna", "service": "Physical", "doctor_name": "Whitaker"},
            service_filter_mode="named",
        )
        blocked = _compute_blocked_entity_fields(nlu)
        self.assertIn("doctor_id", blocked.get("insurance", frozenset()))
        self.assertIn("doctor_id", blocked.get("services", frozenset()))
        self.assertIn("doctor_id", blocked.get("pricing", frozenset()))
        # doctor_search itself is the winning tier for the doctor entity —
        # it must NOT be blocked from its own doctor (it IS correctly
        # blocked from the unrelated service entity, since pricing is also
        # present and wins that separate contest — checked precisely, not
        # just "not blocked at all").
        self.assertNotIn("doctor_id", blocked.get("doctors", frozenset()))
        self.assertIn("service_id", blocked.get("doctors", frozenset()))

    def test_no_doctor_owning_intent_present_blocks_nothing(self):
        """insurance + pricing (no service entity this time) with a doctor
        entity present, but no intent that actually owns doctor_name is
        present at all — nothing contests the doctor field, so it is not
        blocked from anything. (Not a realistic NLU output on its own —
        pricing without a service entity — but the function must degrade
        safely rather than block on the mere presence of a doctor value.)"""
        nlu = _nlu(
            "insurance_verification", ["pricing"],
            {"insurance_provider": "Aetna", "doctor_name": "Whitaker"},
        )
        blocked = _compute_blocked_entity_fields(nlu)
        self.assertNotIn("doctor_id", blocked.get("insurance", frozenset()))


class CompoundEntityScopingIntegrationTests(TestCase):
    """End-to-end: real clinic data, real handlers, real planner. Every
    'poison' doctor genuinely does not accept the named plan / perform the
    named service, so found=True here can only mean the fix works."""

    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="entity-scoping-clinic", name="Entity Scoping Clinic",
            email="e@s.com", phone="+12125550000",
            address={"street": "1 Main St", "city": "Boston", "state": "MA", "zip": "02101"},
            timezone="America/New_York",
        )
        self.aetna = InsurancePlan.objects.create(
            clinic=self.clinic, provider_name="Aetna", plan_name="PPO", is_accepted=True
        )
        self.physical = Service.objects.create(
            clinic=self.clinic, name="Adult Physical", duration_min=30, price_cents=18500
        )
        # Accepts Aetna, performs physicals -- the "control" doctor.
        self.vance = Doctor.objects.create(
            clinic=self.clinic, full_name="Dr. Marcus Vance", title="MD", is_active=True
        )
        DoctorInsurance.objects.create(clinic=self.clinic, doctor=self.vance, insurance_plan=self.aetna)
        DoctorService.objects.create(clinic=self.clinic, doctor=self.vance, service=self.physical)
        # Poison doctor: exists, is real, but accepts no Aetna plan and
        # performs no physical -- any narrowing to him produces a wrong answer.
        self.whitaker = Doctor.objects.create(
            clinic=self.clinic, full_name="James Whitaker", title="PA", is_active=True
        )

    def _plan_and_run(self, message, payload):
        nlu = parse_nlu_payload(payload)
        nlu = replace(nlu, resolved_ids=resolve_entities(self.clinic, nlu.entities))
        facts = build_planner_facts(message=message, nlu=nlu, is_booking_intent=False)
        plan = build_execution_plan(nlu=nlu, facts=facts)
        results = SQLTool.run_tasks(
            self.clinic, nlu, plan.sql_tasks, message=message,
            resolved_service_ids=plan.resolved_service_ids,
            blocked_entity_fields=plan.blocked_entity_fields,
        )
        return plan, {r.handler: r for r in results}

    def test_insurance_plus_availability_not_contaminated(self):
        plan, results = self._plan_and_run(
            "do you accept aetna and is dr whitaker available tomorrow",
            {
                "intent": "insurance_verification", "secondary_intents": ["doctor_availability"],
                "confidence": 0.9,
                "entities": {"insurance_provider": "Aetna", "doctor_name": "Whitaker", "date": "tomorrow"},
            },
        )
        self.assertTrue(results["insurance_accepted"].found)
        self.assertIn("Aetna", results["insurance_accepted"].summary)

    def test_insurance_plus_booking_not_contaminated(self):
        plan, results = self._plan_and_run(
            "do you accept aetna and can i book with dr whitaker",
            {
                "intent": "insurance_verification", "secondary_intents": ["book_appointment"],
                "confidence": 0.9,
                "entities": {"insurance_provider": "Aetna", "doctor_name": "Whitaker"},
            },
        )
        self.assertTrue(results["insurance_accepted"].found)

    def test_pricing_plus_availability_not_contaminated(self):
        plan, results = self._plan_and_run(
            "how much is a physical and is dr whitaker available tomorrow",
            {
                "intent": "pricing", "secondary_intents": ["doctor_availability"], "confidence": 0.9,
                "entities": {"service": "Adult Physical", "doctor_name": "Whitaker", "date": "tomorrow"},
                "service_filter_mode": "named",
            },
        )
        self.assertTrue(results["services_offered"].found)
        self.assertIn("185", results["services_offered"].summary)

    def test_pricing_plus_booking_not_contaminated(self):
        plan, results = self._plan_and_run(
            "how much is a physical and can i book with dr whitaker",
            {
                "intent": "pricing", "secondary_intents": ["book_appointment"], "confidence": 0.9,
                "entities": {"service": "Adult Physical", "doctor_name": "Whitaker"},
                "service_filter_mode": "named",
            },
        )
        self.assertTrue(results["services_offered"].found)

    def test_doctor_listing_plus_booking_not_narrowed(self):
        plan, results = self._plan_and_run(
            "who are your doctors and can i book with dr vance",
            {
                "intent": "doctor_search", "secondary_intents": ["book_appointment"], "confidence": 0.9,
                "entities": {"doctor_name": "Vance"},
            },
        )
        names = {r["full_name"] for r in results["search_doctors"].rows}
        self.assertIn("James Whitaker", names, "the browse must include every doctor, not just Vance")
        self.assertIn("Dr. Marcus Vance", names)

    def test_doctor_listing_plus_pricing_not_narrowed_by_service(self):
        plan, results = self._plan_and_run(
            "who are your doctors and how much is a physical",
            {
                "intent": "doctor_search", "secondary_intents": ["pricing"], "confidence": 0.9,
                "entities": {"service": "Adult Physical"}, "service_filter_mode": "named",
            },
        )
        names = {r["full_name"] for r in results["search_doctors"].rows}
        self.assertIn("James Whitaker", names, "Whitaker doesn't perform physicals but must still be listed")

    def test_three_intent_neither_insurance_nor_pricing_contaminated(self):
        plan, results = self._plan_and_run(
            "do you take aetna, how much is a physical, and can i book with dr whitaker",
            {
                "intent": "multi_intent",
                "secondary_intents": ["insurance_verification", "pricing", "doctor_search"],
                "confidence": 0.95,
                "entities": {
                    "insurance_provider": "Aetna", "service": "Adult Physical", "doctor_name": "Whitaker",
                },
                "service_filter_mode": "named",
            },
        )
        self.assertTrue(results["insurance_accepted"].found)
        self.assertTrue(results["services_offered"].found)
        # search_doctors correctly still narrows to Whitaker -- doctor_search
        # is the genuine winning owner of the doctor entity here (there is
        # no separate "doctors" task competing for it).
        self.assertEqual(
            {r["full_name"] for r in results["search_doctors"].rows}, {"James Whitaker"}
        )

    def test_single_clause_doctor_specific_insurance_still_narrows(self):
        """Regression: a genuine single-clause "does Dr. Whitaker accept
        Aetna" must still correctly report he doesn't — the fix must not
        make doctor-specific insurance questions stop working."""
        plan, results = self._plan_and_run(
            "does dr whitaker accept aetna",
            {
                "intent": "insurance_verification", "secondary_intents": [], "confidence": 0.9,
                "entities": {"insurance_provider": "Aetna", "doctor_name": "Whitaker"},
            },
        )
        self.assertFalse(
            results["insurance_accepted"].found,
            "Whitaker genuinely doesn't accept Aetna -- must still say so for a real single-clause question",
        )

    def test_single_clause_doctor_specific_pricing_still_narrows(self):
        plan, results = self._plan_and_run(
            "how much is a physical with dr whitaker",
            {
                "intent": "pricing", "secondary_intents": [], "confidence": 0.9,
                "entities": {"service": "Adult Physical", "doctor_name": "Whitaker"},
                "service_filter_mode": "named",
            },
        )
        self.assertFalse(
            results["services_offered"].found,
            "Whitaker genuinely doesn't perform physicals -- must still say so for a real single-clause question",
        )

    def test_plain_single_intent_doctor_listing_unaffected(self):
        plan, results = self._plan_and_run(
            "who are your doctors",
            {"intent": "doctor_search", "secondary_intents": [], "confidence": 0.95, "entities": {}},
        )
        self.assertEqual(plan.blocked_entity_fields, {})
        self.assertEqual(len(results["search_doctors"].rows), 2)

    def test_insurance_plus_pricing_no_doctor_entity_unaffected(self):
        plan, results = self._plan_and_run(
            "do you accept aetna and how much is a physical",
            {
                "intent": "insurance_verification", "secondary_intents": ["pricing"], "confidence": 0.9,
                "entities": {"insurance_provider": "Aetna", "service": "Adult Physical"},
                "service_filter_mode": "named",
            },
        )
        self.assertTrue(results["insurance_accepted"].found)
        self.assertTrue(results["services_offered"].found)
