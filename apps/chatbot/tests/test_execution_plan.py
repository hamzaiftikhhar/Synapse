"""ExecutionPlan planner: multi-task, capability tables, ignore LLM orchestration."""

from __future__ import annotations

from django.test import SimpleTestCase

from apps.chatbot.nlu.schemas import Intent, parse_nlu_payload
from apps.chatbot.planner import (
    build_execution_plan,
    build_planner_facts,
    choose_plan,
)
from apps.chatbot.routing.heuristics import apply_routing_heuristics
from apps.chatbot.routing.lanes import Lane


def _facts(**kwargs):
    nlu = kwargs.pop("nlu")
    defaults = dict(
        message="",
        is_booking_intent=False,
        soft_medical=False,
        knowledge_q=False,
        has_catalog=True,
        doc_match=True,
        degraded=False,
        doctor_ranking_request=False,
        instruction_injection=False,
        unknown_doctor_requested=False,
    )
    defaults.update(kwargs)
    return build_planner_facts(nlu=nlu, **defaults)


class ExecutionPlanTests(SimpleTestCase):
    def test_medicare_booking_plus_insurance_and_billing(self):
        nlu = parse_nlu_payload(
            {
                "intent": "book_appointment",
                "secondary_intents": ["insurance_accepted"],
                "confidence": 0.92,
                "topic": "billing_policy",
                "entities": {
                    "insurance_provider": "Medicare Part B",
                    "date": "today",
                },
                # Deprecated orchestration — must be ignored
                "needs_sql": False,
                "needs_vector": False,
                "sql_tool": None,
            }
        )
        msg = (
            "I have Medicare Part B. Can I book an appointment today, "
            "and will you bill Medicare directly for my visit?"
        )
        plan = build_execution_plan(
            nlu=nlu,
            facts=_facts(
                nlu=nlu,
                message=msg,
                is_booking_intent=True,
                knowledge_q=False,
            ),
        )
        self.assertTrue(plan.booking)
        self.assertIn("insurance", plan.sql_tasks)
        self.assertIn("billing_policy", plan.vector_tasks)
        self.assertTrue(plan.use_response_llm)
        self.assertEqual(plan.primary_lane, Lane.BOOKING)

    def test_secondary_insurance_topic_without_entity_is_not_trusted(self):
        """Regression: live-verifying the "Clarification flow" case found that
        gibberish input ("banana purple seven") gets classified intent=faq
        with topic="insurance" and secondary_intents=["insurance_verification"]
        hallucinated by the small NLU classifier — no insurance_provider entity
        was ever extracted, because there was nothing in the message to extract.
        That used to still attach a real insurance SQL task (and render an
        insurance card) on a reply whose own text says "could you clarify your
        question?". Only the primary intent should be trusted unconditionally;
        a topic or secondary intent needs a real entity to back it up."""
        nlu = parse_nlu_payload(
            {
                "intent": "faq",
                "secondary_intents": ["insurance_verification"],
                "confidence": 0.85,
                "topic": "insurance",
                "entities": {},
            }
        )
        msg = "banana purple seven"
        plan = build_execution_plan(
            nlu=nlu,
            facts=_facts(nlu=nlu, message=msg, knowledge_q=False),
        )
        self.assertNotIn("insurance", plan.sql_tasks)

    def test_primary_insurance_intent_stays_trusted_without_entity(self):
        """The primary intent is never gated — "do you accept Delta Dental?"
        with intent=insurance_accepted as the *primary* classification must
        still get the insurance SQL task even before any entity is resolved
        downstream."""
        nlu = parse_nlu_payload(
            {
                "intent": "insurance_accepted",
                "confidence": 0.95,
                "entities": {},
            }
        )
        msg = "do you accept Delta Dental?"
        plan = build_execution_plan(
            nlu=nlu,
            facts=_facts(nlu=nlu, message=msg, knowledge_q=False),
        )
        self.assertIn("insurance", plan.sql_tasks)

    def test_cancel_fee_is_vector_not_pricing_sql(self):
        nlu = parse_nlu_payload(
            {
                "intent": "pricing",
                "confidence": 0.9,
                "needs_sql": True,
                "sql_tool": "pricing",
            }
        )
        msg = "What is the cancel fee if I cancel less than 24 hours?"
        plan = build_execution_plan(
            nlu=nlu,
            facts=_facts(
                nlu=nlu,
                message=msg,
                knowledge_q=True,
                has_catalog=True,
                doc_match=True,
            ),
        )
        self.assertIn("cancellation", plan.vector_tasks)
        self.assertNotIn("pricing", plan.sql_tasks)
        self.assertEqual(plan.primary_lane, Lane.VECTOR_RAG)

    def test_hours_is_sql_only(self):
        nlu = parse_nlu_payload(
            {
                "intent": "clinic_hours",
                "confidence": 0.95,
                "needs_vector": True,  # deprecated noise — ignore
                "document_needed": True,
            }
        )
        plan = build_execution_plan(
            nlu=nlu,
            facts=_facts(nlu=nlu, message="What are your clinic hours?"),
        )
        self.assertEqual(plan.sql_tasks, ["hours"])
        self.assertEqual(plan.vector_tasks, [])
        self.assertFalse(plan.use_response_llm)
        self.assertEqual(plan.primary_lane, Lane.SQL_FAST)

    def test_choose_plan_wrapper_still_works(self):
        nlu = parse_nlu_payload(
            {"intent": "emergency", "is_emergency": True, "confidence": 0.99}
        )
        decision = choose_plan(
            nlu=nlu,
            is_booking_intent=True,
            soft_medical=False,
            needs_vector=True,
            doc_match=False,
            has_catalog=True,
            prefer_vector=False,
            prefer_clarify=False,
            degraded=False,
            doctor_ranking_request=False,
            instruction_injection=False,
            unknown_doctor_requested=False,
            message="chest pain radiating to arm",
        )
        self.assertEqual(decision.lane, Lane.DIRECT)
        self.assertEqual(decision.direct_mode, "emergency")
        self.assertIsNotNone(decision.execution_plan)
        self.assertTrue(decision.execution_plan.emergency)

    def test_ignores_llm_sql_tool_for_task_selection(self):
        nlu = parse_nlu_payload(
            {
                "intent": "faq",
                "confidence": 0.9,
                "sql_tool": "hours",
                "needs_sql": True,
                "topic": "cancellation",
            }
        )
        plan = build_execution_plan(
            nlu=nlu,
            facts=_facts(
                nlu=nlu,
                message="What is your cancellation refund policy?",
                knowledge_q=True,
            ),
        )
        self.assertNotIn("hours", plan.sql_tasks)
        self.assertTrue(plan.vector_tasks)

    def test_soft_schedule_faq_routes_to_availability_not_rag(self):
        nlu = parse_nlu_payload(
            {
                "intent": "faq",
                "confidence": 0.85,
                "entities": {
                    "date": ["Thursday"],
                    "time": ["afternoon", "night"],
                },
                "topic": "general_faq",
            }
        )
        plan = build_execution_plan(
            nlu=nlu,
            facts=_facts(
                nlu=nlu,
                message=(
                    "i was thinking about booking a slot for me "
                    "on thursday afternoon or might be night"
                ),
                knowledge_q=False,
                has_catalog=True,
            ),
        )
        self.assertIn("availability", plan.sql_tasks)
        self.assertNotIn("general_faq", plan.vector_tasks)
        self.assertFalse(plan.booking)

    def test_generic_book_without_date_does_not_run_availability(self):
        """A bare book request must open the wizard, not leftover-day slots."""
        nlu = parse_nlu_payload(
            {
                "intent": "book_appointment",
                "confidence": 0.85,
                "entities": {},
            }
        )
        plan = build_execution_plan(
            nlu=nlu,
            facts=_facts(
                nlu=nlu,
                message="I would like to book an appointment",
                is_booking_intent=True,
            ),
        )
        self.assertTrue(plan.booking)
        self.assertNotIn("availability", plan.sql_tasks)

    def test_hallucinated_view_on_book_typo_does_not_run_appointments_sql(self):
        nlu = parse_nlu_payload(
            {
                "intent": "view_appointments",
                "confidence": 0.95,
                "needs_sql": True,
                "sql_tool": "appointments",
            }
        )
        plan = build_execution_plan(
            nlu=nlu,
            facts=_facts(nlu=nlu, message="koob me", is_booking_intent=False),
        )
        self.assertNotIn("appointments", plan.sql_tasks)
        self.assertFalse(plan.booking)

    def test_typo_book_with_booking_intent_opens_wizard_not_lookup(self):
        nlu = parse_nlu_payload(
            {
                "intent": "book_appointment",
                "confidence": 0.2,
                "needs_sql": True,
                "sql_tool": "appointments",
            }
        )
        plan = build_execution_plan(
            nlu=nlu,
            facts=_facts(
                nlu=nlu,
                message="koob me",
                is_booking_intent=True,
                prefer_clarify=True,
            ),
        )
        self.assertTrue(plan.booking)
        self.assertNotIn("appointments", plan.sql_tasks)
        self.assertFalse(plan.clarify)

    def test_real_view_request_still_runs_appointments_sql(self):
        nlu = parse_nlu_payload(
            {
                "intent": "view_appointments",
                "confidence": 0.95,
                "needs_sql": True,
                "sql_tool": "appointments",
            }
        )
        plan = build_execution_plan(
            nlu=nlu,
            facts=_facts(
                nlu=nlu,
                message="show my appointments",
                is_booking_intent=False,
            ),
        )
        self.assertIn("appointments", plan.sql_tasks)
        self.assertFalse(plan.booking)

    def test_empty_availability_does_not_preauthorize_hybrid_rag(self):
        """Resolved 'no slots that day' is an answer. Documents must not
        invent openings — even when the catalog exists and hybrid is on."""
        nlu = parse_nlu_payload(
            {
                "intent": "doctor_availability",
                "confidence": 0.8,
                "entities": {"doctor_name": ["Maya"]},
            }
        )
        for message in (
            "when's the soonest Maya has a gap on Tuesday",
            "any openings with Lin that afternoon",
            "can she see me Tuesday or is she booked solid",
        ):
            with self.subTest(message=message):
                plan = build_execution_plan(
                    nlu=nlu,
                    facts=_facts(
                        nlu=nlu,
                        message=message,
                        has_catalog=True,
                        allow_hybrid=True,
                        knowledge_q=True,
                    ),
                )
                self.assertIn("availability", plan.sql_tasks, msg=message)
                self.assertEqual(plan.fallback_vector_tasks, [], msg=message)

    def test_empty_insurance_sql_still_may_hybrid(self):
        """Don't over-fix: a thin insurance miss can still consult policy docs."""
        nlu = parse_nlu_payload(
            {
                "intent": "insurance_accepted",
                "confidence": 0.9,
                "entities": {"insurance_provider": ["Cigna"]},
            }
        )
        plan = build_execution_plan(
            nlu=nlu,
            facts=_facts(
                nlu=nlu,
                message="is Cigna on the accepted list here",
                has_catalog=True,
                allow_hybrid=True,
            ),
        )
        self.assertIn("insurance", plan.sql_tasks)
        self.assertTrue(plan.fallback_vector_tasks)

    def test_empty_services_sql_still_may_hybrid(self):
        nlu = parse_nlu_payload(
            {"intent": "services_offered", "confidence": 0.9}
        )
        plan = build_execution_plan(
            nlu=nlu,
            facts=_facts(
                nlu=nlu,
                message="do you offer HydraFacial",
                has_catalog=True,
            ),
        )
        self.assertIn("services", plan.sql_tasks)
        self.assertTrue(plan.fallback_vector_tasks)


class BookingDateCorrectionSchedulesAvailabilityTests(SimpleTestCase):
    """Live-confirmed bug: engine.py's _compose_from_plan suppresses the
    generic "let's get you booked" text whenever entities.date/time is
    present on a booking turn, on the assumption the availability slots
    it's about to show will speak for themselves. That assumption used to
    only hold when is_doctor_availability_query's narrow keyword heuristic
    ("free"/"available"/"open"/"slot") *also* happened to match the same
    message. "book an appointment for Monday" hits both. The very next
    turn in the same conversation, "actually make that Tuesday" (a date
    correction — is_booking_intent still true, no availability keyword),
    suppressed the text but never scheduled the SQL task that would have
    filled it back in, producing a completely empty response bubble."""

    def test_booking_intent_with_date_schedules_availability_even_without_keyword(self):
        nlu = parse_nlu_payload(
            {
                "intent": "book_appointment",
                "confidence": 0.9,
                "entities": {"date": "tuesday"},
            }
        )
        plan = build_execution_plan(
            nlu=nlu,
            facts=_facts(
                nlu=nlu,
                message="actually make that Tuesday",
                is_booking_intent=True,
            ),
        )
        self.assertIn("availability", plan.sql_tasks)

    def test_booking_intent_with_time_only_also_schedules_availability(self):
        nlu = parse_nlu_payload(
            {
                "intent": "book_appointment",
                "confidence": 0.9,
                "entities": {"time": "3pm"},
            }
        )
        plan = build_execution_plan(
            nlu=nlu,
            facts=_facts(nlu=nlu, message="make it 3pm instead", is_booking_intent=True),
        )
        self.assertIn("availability", plan.sql_tasks)

    def test_non_booking_date_mention_does_not_force_availability(self):
        """Control: a date entity alone, without is_booking_intent, must
        not start pulling in availability SQL for unrelated turns."""
        nlu = parse_nlu_payload(
            {
                "intent": "clinic_hours",
                "confidence": 0.9,
                "entities": {"date": "tuesday"},
            }
        )
        plan = build_execution_plan(
            nlu=nlu,
            facts=_facts(nlu=nlu, message="what are your hours on Tuesday"),
        )
        self.assertNotIn("availability", plan.sql_tasks)


class FAQOverwriteRemovalTests(SimpleTestCase):
    """Regression for the heuristics.py fix: apply_routing_heuristics used
    to rewrite intent to FAQ for PRICING/SERVICES_OFFERED/CLINIC_HOURS/
    UNKNOWN whenever knowledge_q+catalog were true, which erased
    _INTENT_SQL_TASKS's lookup for the real intent with no benefit (vector
    routing is derived independently from facts.knowledge_q). Runs the full
    heuristics -> planner chain, not build_execution_plan alone, since the
    bug was specifically in what heuristics.py handed the planner."""

    def _catalog(self, keyword: str, summary: str) -> list[dict]:
        return [
            {
                "id": "doc1",
                "title": "Policy",
                "routing_keywords": [keyword],
                "routing_summary": summary,
            }
        ]

    def test_pricing_intent_keeps_its_sql_task_alongside_vector(self):
        nlu = parse_nlu_payload(
            {
                "intent": "pricing",
                "confidence": 0.7,
                "entities": {"service": "Annual Physical"},
            }
        )
        message = "how early should I arrive and how much is the annual physical"
        catalog = self._catalog("arrive", "arrive early instructions")
        heuristic_out = apply_routing_heuristics(
            message=message, nlu=nlu, document_catalog=catalog, service_catalog=[]
        )
        self.assertEqual(heuristic_out.intent, Intent.PRICING)
        plan = build_execution_plan(
            nlu=heuristic_out,
            facts=build_planner_facts(
                message=message,
                nlu=heuristic_out,
                knowledge_q=True,
                has_catalog=True,
                doc_match=True,
            ),
        )
        self.assertIn("pricing", plan.sql_tasks)
        self.assertIn("general_faq", plan.vector_tasks)

    def test_services_offered_intent_keeps_its_sql_task_alongside_vector(self):
        nlu = parse_nlu_payload(
            {
                "intent": "services_offered",
                "confidence": 0.7,
                "entities": {},
            }
        )
        message = "what should I know before my visit and what services do you offer"
        catalog = self._catalog("before", "pre-visit instructions")
        heuristic_out = apply_routing_heuristics(
            message=message, nlu=nlu, document_catalog=catalog, service_catalog=[]
        )
        self.assertEqual(heuristic_out.intent, Intent.SERVICES_OFFERED)
        plan = build_execution_plan(
            nlu=heuristic_out,
            facts=build_planner_facts(
                message=message,
                nlu=heuristic_out,
                knowledge_q=True,
                has_catalog=True,
                doc_match=True,
                service_list=True,
            ),
        )
        self.assertIn("services", plan.sql_tasks)
        self.assertIn("general_faq", plan.vector_tasks)

    def test_clinic_hours_intent_keeps_its_sql_task_alongside_vector(self):
        nlu = parse_nlu_payload(
            {
                "intent": "clinic_hours",
                "confidence": 0.7,
                "entities": {},
            }
        )
        message = "what should I bring and what are your hours"
        catalog = self._catalog("bring", "what to bring to your appointment")
        heuristic_out = apply_routing_heuristics(
            message=message, nlu=nlu, document_catalog=catalog, service_catalog=[]
        )
        self.assertEqual(heuristic_out.intent, Intent.CLINIC_HOURS)
        plan = build_execution_plan(
            nlu=heuristic_out,
            facts=build_planner_facts(
                message=message,
                nlu=heuristic_out,
                knowledge_q=True,
                has_catalog=True,
                doc_match=True,
            ),
        )
        self.assertIn("hours", plan.sql_tasks)
        self.assertIn("general_faq", plan.vector_tasks)


class MultiIntentCompoundTests(SimpleTestCase):
    """If the NLU correctly populates secondary_intents for a compound
    message (the contract the prompt strengthening targets), the planner's
    existing fan-out must actually answer both halves. This asserts the
    downstream contract works — LLM compliance itself is validated by the
    eval battery, not a unit test."""

    def test_insurance_plus_doctor_availability_both_attach(self):
        nlu = parse_nlu_payload(
            {
                "intent": "insurance_accepted",
                "secondary_intents": ["doctor_availability"],
                "confidence": 0.9,
                "entities": {
                    "insurance_provider": "Aetna",
                    "doctor_name": "Vance",
                    "date": "next tuesday",
                },
            }
        )
        message = "do you accept aetna and can i see dr vance next tuesday"
        plan = build_execution_plan(
            nlu=nlu,
            facts=build_planner_facts(
                message=message,
                nlu=nlu,
                doctor_availability_query=True,
            ),
        )
        self.assertIn("insurance", plan.sql_tasks)
        self.assertIn("availability", plan.sql_tasks)

    def test_pricing_plus_services_offered_both_attach(self):
        nlu = parse_nlu_payload(
            {
                "intent": "pricing",
                "secondary_intents": ["services_offered"],
                "confidence": 0.9,
                "entities": {"service": "Strep Test"},
            }
        )
        message = "what's the price of a strep test and can i walk in today"
        plan = build_execution_plan(
            nlu=nlu,
            facts=build_planner_facts(message=message, nlu=nlu),
        )
        self.assertIn("pricing", plan.sql_tasks)
        self.assertIn("services", plan.sql_tasks)


class EmergencyVsUrgentAvailabilityTests(SimpleTestCase):
    """The prompt now distinguishes danger-symptom emergencies from same-day
    urgency language. This locks the *downstream* contract: once NLU
    correctly emits is_emergency=False for pure scheduling urgency, the
    planner must route to availability, not the emergency short-circuit —
    and the reverse must still short-circuit to DIRECT immediately."""

    def test_urgent_scheduling_language_without_danger_routes_to_availability(self):
        nlu = parse_nlu_payload(
            {
                "intent": "doctor_availability",
                "confidence": 0.9,
                "is_emergency": False,
                "entities": {"date": "today"},
            }
        )
        message = "asap, need someone today"
        plan = build_execution_plan(
            nlu=nlu,
            facts=build_planner_facts(
                message=message,
                nlu=nlu,
                doctor_availability_query=True,
                urgent_availability=True,
            ),
        )
        self.assertFalse(plan.emergency)
        self.assertIn("availability", plan.sql_tasks)

    def test_genuine_emergency_still_short_circuits_regardless_of_urgency_signal(self):
        """The fix must never weaken real emergency detection — is_emergency
        still wins outright even if urgent_availability also happens to be
        true for the same message."""
        nlu = parse_nlu_payload(
            {
                "intent": "emergency",
                "confidence": 0.99,
                "is_emergency": True,
                "entities": {},
            }
        )
        plan = build_execution_plan(
            nlu=nlu,
            facts=build_planner_facts(
                message="chest pain, can't breathe, need help asap",
                nlu=nlu,
                urgent_availability=True,
            ),
        )
        self.assertTrue(plan.emergency)
        self.assertEqual(plan.direct_mode, "emergency")
