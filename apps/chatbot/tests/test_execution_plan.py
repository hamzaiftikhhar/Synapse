"""ExecutionPlan planner: multi-task, capability tables, ignore LLM orchestration."""

from __future__ import annotations

from django.test import SimpleTestCase

from apps.chatbot.nlu.schemas import Intent, parse_nlu_payload
from apps.chatbot.planner import (
    ExecutionPlan,
    apply_capability_resolution,
    build_execution_plan,
    build_planner_facts,
    choose_plan,
    resolve_plan_after_sql,
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


class ResolvePlanAfterSqlAuthoritativeGuardTests(SimpleTestCase):
    """Live-confirmed bug (real production trace, Horizon Family Medicine):
    a deliberate, authoritative SQL decline ("We don't have a specialist
    for that here") still activated the pre-authorized vector+Large-LLM
    fallback purely because found=False -- with zero awareness that the
    empty result was already a considered, final answer. A single
    weakly-related vector chunk (score 0.2513, just above CHAT_VECTOR_
    MIN_SCORE=0.25) then let the Large LLM synthesize a plausible-sounding
    but ungrounded claim ("Our Family Medicine team can help evaluate
    recurring urinary problems during a routine office visit") instead of
    using the answer Python had already decided on. `sql_authoritative`
    closes this at the one place an ExecutionPlan is allowed to change
    after SQL runs, before vector search is ever attempted -- not by
    tuning the retrieval threshold, which wouldn't address a SQL result
    that was always going to be authoritative regardless of score."""

    def _plan(self, **overrides):
        defaults = dict(fallback_vector_tasks=["general_faq"])
        defaults.update(overrides)
        return ExecutionPlan(**defaults)

    def test_authoritative_empty_result_does_not_activate_fallback(self):
        plan = self._plan()
        out = resolve_plan_after_sql(plan, sql_found=False, sql_authoritative=True)
        self.assertEqual(out.vector_tasks, [])
        self.assertFalse(out.use_response_llm)
        self.assertIs(out, plan)

    def test_non_authoritative_empty_result_still_activates_fallback(self):
        """Control: a genuine "SQL drew a blank" case must keep escalating
        exactly as before -- this guard is scoped to authoritative
        results only, not a blanket "never escalate" change."""
        plan = self._plan()
        out = resolve_plan_after_sql(plan, sql_found=False, sql_authoritative=False)
        self.assertIn("general_faq", out.vector_tasks)
        self.assertTrue(out.use_response_llm)

    def test_sql_found_still_never_activates_fallback_regardless(self):
        plan = self._plan()
        out = resolve_plan_after_sql(plan, sql_found=True, sql_authoritative=False)
        self.assertIs(out, plan)

    def test_no_fallback_tasks_preauthorized_is_a_no_op_either_way(self):
        plan = self._plan(fallback_vector_tasks=[])
        out = resolve_plan_after_sql(plan, sql_found=False, sql_authoritative=False)
        self.assertIs(out, plan)


class _FakeDecision:
    """Stand-in for capability_routing_policy.RoutingDecision -- avoids a
    live LLM call in these pure-mapping tests, same reasoning
    ResolvePlanAfterSqlAuthoritativeGuardTests uses fake sql_found/
    sql_authoritative facts instead of running real SQL."""

    def __init__(
        self,
        action,
        specialty_ids=None,
        service_ids=None,
        informational_service_candidates=None,
    ):
        self.action = action
        self.specialty_ids = specialty_ids or []
        self.service_ids = service_ids or []
        self.informational_service_candidates = informational_service_candidates or []


class ApplyCapabilityResolutionTests(SimpleTestCase):
    """apply_capability_resolution: the pure mapping from an
    already-computed RoutingDecision onto a plan. The live LLM call
    (resolve_capability) and the routing-policy computation (decide_
    routing) both happen in engine.py, before this function ever runs --
    this only tests the mapping, the same "pure function, no I/O" contract
    resolve_plan_after_sql above already establishes."""

    def test_provider_error_never_overrides_an_unclaimed_plan(self):
        """Rollback-safe: an infrastructure hiccup must degrade to
        whatever the plan already had (soft_medical's own reply), never a
        new, untested failure mode."""
        plan = ExecutionPlan(direct=True, direct_mode="soft_medical", soft_medical=True)
        out = apply_capability_resolution(
            plan, decision=_FakeDecision("unavailable"), was_unclaimed=True
        )
        self.assertIs(out, plan)

    def test_provider_error_never_overrides_an_already_dispatching_plan(self):
        plan = ExecutionPlan(sql_tasks=["doctors"])
        out = apply_capability_resolution(
            plan, decision=_FakeDecision("unavailable"), was_unclaimed=False
        )
        self.assertIs(out, plan)

    def test_unclaimed_decline_becomes_capability_not_offered(self):
        plan = ExecutionPlan(direct=True, direct_mode="soft_medical", soft_medical=True)
        out = apply_capability_resolution(
            plan, decision=_FakeDecision("decline"), was_unclaimed=True
        )
        self.assertTrue(out.direct)
        self.assertEqual(out.direct_mode, "capability_not_offered")
        self.assertTrue(out.capability_resolver_used)

    def test_unclaimed_filter_converts_direct_into_a_real_sql_task(self):
        """The central mechanism this vertical slice adds: a
        medical_question-concern that today never reaches SQL at all
        (direct=True, sql_tasks=[]) becomes a real doctor-search SQL task,
        filtered by the resolver's specialty ids."""
        plan = ExecutionPlan(direct=True, direct_mode="soft_medical", soft_medical=True)
        out = apply_capability_resolution(
            plan,
            decision=_FakeDecision("filter", specialty_ids=["spec-1"]),
            was_unclaimed=True,
        )
        self.assertFalse(out.direct)
        self.assertIsNone(out.direct_mode)
        self.assertEqual(out.sql_tasks, ["doctors"])
        self.assertEqual(out.resolved_specialty_ids, ["spec-1"])
        self.assertTrue(out.capability_resolver_used)

    def test_unclaimed_filter_resets_clarify_too(self):
        """Live-confirmed shape: a bare concern ("my teeth are a bit
        yellow") lands at direct=False, direct_mode=None, clarify=True --
        clarify must not survive the override and silently win back over
        the newly-set sql_tasks in a caller that checks it independently."""
        plan = ExecutionPlan(direct=False, direct_mode=None, clarify=True)
        out = apply_capability_resolution(
            plan,
            decision=_FakeDecision("filter", specialty_ids=["spec-1"]),
            was_unclaimed=True,
        )
        self.assertFalse(out.clarify)
        self.assertEqual(out.sql_tasks, ["doctors"])

    def test_already_dispatching_filter_only_refines_resolved_ids(self):
        """An already-SQL-dispatching plan (doctor_search/services_offered)
        must never have its dispatch decision touched -- only the resolved
        ids it filters by."""
        plan = ExecutionPlan(sql_tasks=["doctors"], direct=False)
        out = apply_capability_resolution(
            plan,
            decision=_FakeDecision("filter", service_ids=["svc-1"]),
            was_unclaimed=False,
        )
        self.assertEqual(out.sql_tasks, ["doctors"])
        self.assertFalse(out.direct)
        self.assertEqual(out.resolved_service_ids, ["svc-1"])

    def test_already_dispatching_decline_is_a_no_op_on_dispatch(self):
        """The SQL handler's own existing resolver chain already produces
        the correct honest decline independently (cardiologist/
        dermatologist, live-confirmed) -- this must not fight it."""
        plan = ExecutionPlan(sql_tasks=["doctors"], direct=False)
        out = apply_capability_resolution(
            plan, decision=_FakeDecision("decline"), was_unclaimed=False
        )
        self.assertEqual(out.sql_tasks, ["doctors"])
        self.assertEqual(out.resolved_service_ids, [])

    def test_never_drops_unrelated_fields(self):
        """Guards against the exact field-dropping bug found earlier this
        session (routing/heuristics.py, routing/confidence.py) -- must use
        dataclasses.replace, never reconstruct ExecutionPlan field-by-field."""
        plan = ExecutionPlan(
            direct=True,
            direct_mode="soft_medical",
            soft_medical=True,
            blocked_entity_fields={"doctors": frozenset({"doctor_id"})},
        )
        out = apply_capability_resolution(
            plan,
            decision=_FakeDecision("filter", specialty_ids=["spec-1"]),
            was_unclaimed=True,
        )
        self.assertEqual(out.blocked_entity_fields, {"doctors": frozenset({"doctor_id"})})

    def test_unclaimed_decline_carries_informational_service_candidates(self):
        """capability_routing_policy's "concern_no_specialty_candidate"
        case can still find a real service candidate with no specialty
        match at all -- previously computed, logged, and discarded. Must
        now reach the plan so engine.py's decline reply can name it."""
        plan = ExecutionPlan(direct=True, direct_mode="soft_medical", soft_medical=True)
        out = apply_capability_resolution(
            plan,
            decision=_FakeDecision(
                "decline", informational_service_candidates=["svc-1"]
            ),
            was_unclaimed=True,
        )
        self.assertEqual(out.direct_mode, "capability_not_offered")
        self.assertEqual(out.informational_service_candidates, ["svc-1"])

    def test_unclaimed_filter_carries_informational_service_candidates(self):
        plan = ExecutionPlan(direct=True, direct_mode="soft_medical", soft_medical=True)
        out = apply_capability_resolution(
            plan,
            decision=_FakeDecision(
                "filter",
                specialty_ids=["spec-1"],
                informational_service_candidates=["svc-1"],
            ),
            was_unclaimed=True,
        )
        self.assertEqual(out.informational_service_candidates, ["svc-1"])

    def test_already_dispatching_filter_carries_informational_service_candidates(self):
        plan = ExecutionPlan(sql_tasks=["doctors"], direct=False)
        out = apply_capability_resolution(
            plan,
            decision=_FakeDecision(
                "filter",
                service_ids=["svc-1"],
                informational_service_candidates=["svc-2"],
            ),
            was_unclaimed=False,
        )
        self.assertEqual(out.informational_service_candidates, ["svc-2"])


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


class AppointmentManagementDoesNotForceAvailabilityTests(SimpleTestCase):
    """Live-confirmed (stress test against real chatbot failure-mode
    research): "This is Dr. Rostova, I need you to cancel all of
    tomorrow's appointments for my patients" has entities.date=["tomorrow"]
    and the word "appointments", satisfying both of the "date/time +
    scheduling language -> availability" block's conditions regardless of
    intent -- so a cancel request got a random "Earliest opening: Dr. X
    at 8:00 AM" appended right after the phone-verification prompt. That
    block exists to rescue an *under-classified* booking request NLU
    mislabeled as faq/unknown/etc; appointment-management intents are
    already correctly classified and handled by their own SQL task, so
    they never needed rescuing and must not gain a nonsensical next-slot
    lookup on top of it."""

    def test_cancel_with_a_named_date_does_not_pull_in_availability(self):
        nlu = parse_nlu_payload(
            {
                "intent": "cancel_appointment",
                "confidence": 0.95,
                "entities": {"date": ["tomorrow"], "doctor_name": "Rostova"},
            }
        )
        plan = build_execution_plan(
            nlu=nlu,
            facts=_facts(
                nlu=nlu,
                message=(
                    "This is Dr. Rostova, I need you to cancel all of "
                    "tomorrow's appointments for my patients."
                ),
            ),
        )
        self.assertNotIn("availability", plan.sql_tasks)
        self.assertIn("appointments", plan.sql_tasks)

    def test_reschedule_with_a_named_date_does_not_pull_in_availability(self):
        nlu = parse_nlu_payload(
            {
                "intent": "reschedule_appointment",
                "confidence": 0.9,
                "entities": {"date": ["tomorrow"]},
            }
        )
        plan = build_execution_plan(
            nlu=nlu,
            facts=_facts(
                nlu=nlu, message="I need to reschedule my appointment for tomorrow"
            ),
        )
        self.assertNotIn("availability", plan.sql_tasks)

    def test_view_appointments_with_a_named_date_does_not_pull_in_availability(self):
        nlu = parse_nlu_payload(
            {
                "intent": "view_appointments",
                "confidence": 0.9,
                "entities": {"date": ["tomorrow"]},
            }
        )
        plan = build_execution_plan(
            nlu=nlu,
            facts=_facts(nlu=nlu, message="what appointments do I have tomorrow"),
        )
        self.assertNotIn("availability", plan.sql_tasks)

    def test_genuine_underclassified_booking_request_still_rescued(self):
        """Control: the original rescue this block exists for must keep
        working -- a booking-shaped message NLU mislabeled as faq/unknown
        still needs availability forced in."""
        nlu = parse_nlu_payload(
            {
                "intent": "faq",
                "confidence": 0.4,
                "entities": {"date": ["tomorrow"]},
            }
        )
        plan = build_execution_plan(
            nlu=nlu,
            facts=_facts(nlu=nlu, message="do you have any appointment openings tomorrow"),
        )
        self.assertIn("availability", plan.sql_tasks)


class MedicalQuestionModeRoutingTests(SimpleTestCase):
    """Live-confirmed bug (real production trace, StackUp Technologies):
    "What is hypothyroidism?" and "What is a crown in dentistry?" both got
    the generic "I can't diagnose symptoms, but I can help you find a
    doctor" soft_medical reply -- the user asked for a definition, not
    diagnosis. Root cause: medical_question intent alone was sufficient to
    trigger soft_medical, with no requirement the message actually
    disclose a personal symptom. See the approved plan ("Separate
    'explain a concept' / 'personal symptom' / 'risk question' inside
    medical_question") for the full routing invariant these tests lock
    in: semantic classification (medical_question_mode) must win over
    lexical medical-term detection (entities.symptom/looks_like_symptom),
    never the other way around."""

    def test_definitional_wins_even_with_a_symptom_entity_also_set(self):
        """The precise regression guard for the corrected precedence:
        entities.symptom being set (e.g. "hypothyroidism" -- a real
        illness word the NLU's own extraction rule always fills in,
        regardless of whether the message is asking for a definition or
        disclosing a personal symptom) must never re-open the old
        soft_medical path once medical_question_mode has already said
        "definitional". soft_medical is deliberately forced True here
        (simulating what the old, unfixed sensor computation would have
        produced) to prove the new direct_mode check wins regardless of
        that value, not just because soft_medical happens to be False."""
        nlu = parse_nlu_payload(
            {
                "intent": "medical_question",
                "confidence": 0.9,
                "entities": {"symptom": "hypothyroidism"},
                "medical_question_mode": "definitional",
            }
        )
        plan = build_execution_plan(
            nlu=nlu,
            facts=_facts(
                nlu=nlu, message="What is hypothyroidism?", soft_medical=True
            ),
        )
        self.assertEqual(plan.direct_mode, "general_medical_knowledge")
        self.assertNotEqual(plan.direct_mode, "soft_medical")

    def test_definitional_wins_even_with_looks_like_symptom_true(self):
        """Same guard, via the other lexical signal: a message containing
        a looks_like_symptom cue word ("crown" isn't one, but this proves
        the mechanism generally) must not override an explicit
        definitional classification either."""
        nlu = parse_nlu_payload(
            {
                "intent": "medical_question",
                "confidence": 0.9,
                "medical_question_mode": "definitional",
            }
        )
        plan = build_execution_plan(
            nlu=nlu,
            facts=_facts(
                nlu=nlu,
                message="What is the feeling of nausea, medically speaking?",
                soft_medical=True,
            ),
        )
        self.assertEqual(plan.direct_mode, "general_medical_knowledge")

    def test_personal_with_symptom_entity_still_routes_soft_medical(self):
        """The existing personal-symptom lane must remain fully
        reachable -- medical_question_mode == "personal" does not divert
        to the new path."""
        nlu = parse_nlu_payload(
            {
                "intent": "medical_question",
                "confidence": 0.9,
                "entities": {"symptom": "knee pain"},
                "medical_question_mode": "personal",
            }
        )
        plan = build_execution_plan(
            nlu=nlu,
            facts=_facts(nlu=nlu, message="I have knee pain", soft_medical=True),
        )
        self.assertNotEqual(plan.direct_mode, "general_medical_knowledge")
        self.assertNotEqual(plan.direct_mode, "medical_advice_refusal")

    def test_risk_mode_routes_to_medical_advice_refusal(self):
        nlu = parse_nlu_payload(
            {
                "intent": "medical_question",
                "confidence": 0.9,
                "medical_question_mode": "risk",
            }
        )
        plan = build_execution_plan(
            nlu=nlu,
            facts=_facts(
                nlu=nlu,
                message="Is it safe to take Clenbuterol being overweight and asthmatic?",
                soft_medical=True,
            ),
        )
        self.assertEqual(plan.direct_mode, "medical_advice_refusal")

    def test_generic_side_effect_question_is_not_risk(self):
        """A generic, non-personalized risk/side-effect question
        classifies definitional per the prompt instruction, not risk --
        this test locks in the *intended* NLU behavior at the planner
        level: if medical_question_mode ever legitimately comes back
        "definitional" for such a question, the planner must route it to
        general_medical_knowledge, never medical_advice_refusal, which
        would otherwise stonewall a perfectly answerable educational
        question."""
        nlu = parse_nlu_payload(
            {
                "intent": "medical_question",
                "confidence": 0.9,
                "medical_question_mode": "definitional",
            }
        )
        plan = build_execution_plan(
            nlu=nlu,
            facts=_facts(
                nlu=nlu, message="What are the side effects of ibuprofen?"
            ),
        )
        self.assertEqual(plan.direct_mode, "general_medical_knowledge")
        self.assertNotEqual(plan.direct_mode, "medical_advice_refusal")

    def test_none_mode_preserves_existing_soft_medical_fallback(self):
        """The fail-safe default: when the model doesn't populate
        medical_question_mode at all, behavior must be identical to
        before this change -- soft_medical's own value (computed
        upstream) is what decides, unchanged."""
        nlu = parse_nlu_payload({"intent": "medical_question", "confidence": 0.9})
        self.assertIsNone(nlu.medical_question_mode)
        plan = build_execution_plan(
            nlu=nlu,
            facts=_facts(nlu=nlu, message="I have a headache", soft_medical=True),
        )
        self.assertNotEqual(plan.direct_mode, "general_medical_knowledge")
        self.assertNotEqual(plan.direct_mode, "medical_advice_refusal")

    def test_emergency_wins_over_every_medical_question_mode(self):
        """is_emergency is an independent safety flag the NLU can set
        alongside any intent (see nlu/emergency_patterns.py's fail-closed
        design) -- it must win even when intent is medical_question and
        medical_question_mode was also populated."""
        nlu = parse_nlu_payload(
            {
                "intent": "medical_question",
                "confidence": 0.99,
                "is_emergency": True,
                "medical_question_mode": "definitional",
            }
        )
        self.assertEqual(nlu.medical_question_mode, "definitional")
        plan = build_execution_plan(
            nlu=nlu,
            facts=_facts(nlu=nlu, message="I can't breathe and my chest hurts"),
        )
        self.assertTrue(plan.emergency)
        self.assertEqual(plan.direct_mode, "emergency")


class SoftMedicalValidatedServiceBeatsDirectTests(SimpleTestCase):
    """Capability-resolution audit G1: when resolve_entities already set
    nlu.resolved_ids.service_id, soft_medical must not throw that validated
    clinic capability away for a canned decline. Gate on resolved_ids
    (DB-validated), never matched_service_ids (lexical coincidence)."""

    def test_resolved_service_routes_to_services_sql_not_soft_medical(self):
        from dataclasses import replace

        from apps.chatbot.nlu.schemas import ResolvedIds

        nlu = parse_nlu_payload(
            {
                "intent": "medical_question",
                "confidence": 0.9,
                "entities": {"service": "Routine Blood Draw (Venipuncture)"},
                "medical_question_mode": "personal",
            }
        )
        nlu = replace(
            nlu,
            resolved_ids=ResolvedIds(service_id="svc-blood-draw-1"),
        )
        plan = build_execution_plan(
            nlu=nlu,
            facts=_facts(
                nlu=nlu,
                message="I need to get my blood drawn",
                soft_medical=True,
                doc_match=False,
                has_catalog=True,
            ),
        )
        self.assertNotEqual(plan.direct_mode, "soft_medical")
        self.assertFalse(plan.direct)
        self.assertIn("services", plan.sql_tasks)
        self.assertEqual(plan.vector_tasks, [])

    def test_soft_medical_without_resolved_service_still_direct(self):
        nlu = parse_nlu_payload(
            {
                "intent": "medical_question",
                "confidence": 0.9,
                "entities": {"symptom": "knee pain"},
                "medical_question_mode": "personal",
            }
        )
        self.assertIsNone(nlu.resolved_ids.service_id)
        plan = build_execution_plan(
            nlu=nlu,
            facts=_facts(
                nlu=nlu,
                message="I have knee pain",
                soft_medical=True,
                doc_match=False,
            ),
        )
        self.assertEqual(plan.direct_mode, "soft_medical")
        self.assertEqual(plan.sql_tasks, [])

    def test_matched_service_ids_alone_do_not_gate(self):
        """Lexical matched_service_ids must NOT become an authoritative
        planner gate — that was the rejected first draft of G1."""
        nlu = parse_nlu_payload(
            {
                "intent": "medical_question",
                "confidence": 0.9,
                "entities": {"symptom": "sore throat"},
                "medical_question_mode": "personal",
            }
        )
        self.assertIsNone(nlu.resolved_ids.service_id)
        plan = build_execution_plan(
            nlu=nlu,
            facts=_facts(
                nlu=nlu,
                message="Do you offer anything for a sore throat and fever?",
                soft_medical=True,
                doc_match=False,
                matched_service_ids=["svc-lexical-coincidence"],
            ),
        )
        self.assertEqual(plan.direct_mode, "soft_medical")
        self.assertNotIn("services", plan.sql_tasks)

    def test_resolved_service_suppresses_soft_medical_vector_hybrid(self):
        from dataclasses import replace

        from apps.chatbot.nlu.schemas import ResolvedIds

        nlu = parse_nlu_payload(
            {
                "intent": "medical_question",
                "confidence": 0.9,
                "entities": {"service": "Rapid Strep / Flu Combo Swab"},
                "medical_question_mode": "personal",
            }
        )
        nlu = replace(
            nlu,
            resolved_ids=ResolvedIds(service_id="svc-flu-1"),
        )
        plan = build_execution_plan(
            nlu=nlu,
            facts=_facts(
                nlu=nlu,
                message="How much does your flu test cost?",
                soft_medical=True,
                doc_match=True,
                has_catalog=True,
            ),
        )
        self.assertIn("services", plan.sql_tasks)
        self.assertNotIn("general_faq", plan.vector_tasks)
        self.assertNotEqual(plan.direct_mode, "soft_medical")


class MedicalQuestionDocMatchGatingTests(SimpleTestCase):
    """Live-confirmed bug, already reproduced by an existing test
    (test_latency_stability.py::ComposeFromPlanSoftMedicalFallbackTests,
    "i have kidney stones"): a medical_question got doc_match=True merely
    because the clinic had ANY document uploaded at all -- typically a
    membership/policy contract, not a symptom glossary -- independent of
    whether matching_document_ids found any real keyword/topic overlap.
    That fired a real, costly vector search doomed to find nothing. These
    tests exercise compute_message_sensors's doc_match computation
    directly (the gating layer), not the composition-layer fallback the
    existing test already covers -- these are complementary, not
    duplicate coverage."""

    def _catalog(self):
        return [
            {
                "id": "doc-1",
                "title": "Membership Agreement",
                "routing_summary": "Monthly membership fees, cancellation, and billing policy.",
                "routing_keywords": ["membership", "fees", "cancellation", "billing"],
            }
        ]

    def test_medical_question_with_zero_overlap_gets_doc_match_false(self):
        from apps.chatbot.planner import compute_message_sensors

        nlu = parse_nlu_payload(
            {"intent": "medical_question", "confidence": 0.9, "entities": {"symptom": "kidney stones"}}
        )
        sensors = compute_message_sensors(
            message="i have kidney stones",
            nlu=nlu,
            document_catalog=self._catalog(),
            service_catalog=[],
        )
        self.assertFalse(sensors.doc_match)

    def test_medical_question_with_real_overlap_still_gets_doc_match_true(self):
        """The fix narrows the has_catalog-only shortcut -- it must not
        break the case where matching_document_ids finds genuine overlap."""
        from apps.chatbot.planner import compute_message_sensors

        nlu = parse_nlu_payload({"intent": "medical_question", "confidence": 0.9})
        sensors = compute_message_sensors(
            message="What's your policy on membership cancellation fees?",
            nlu=nlu,
            document_catalog=self._catalog(),
            service_catalog=[],
        )
        self.assertTrue(sensors.doc_match)

    def test_faq_with_zero_overlap_keeps_the_looser_existing_assumption(self):
        """FAQ/MEMBERSHIP intentionally keep the looser "any catalog is
        plausibly relevant" assumption -- this plan doesn't revisit that
        existing editorial call, only medical_question's."""
        from apps.chatbot.planner import compute_message_sensors

        nlu = parse_nlu_payload({"intent": "faq", "confidence": 0.9})
        sensors = compute_message_sensors(
            message="Can you tell me about your clinic policies in general?",
            nlu=nlu,
            document_catalog=self._catalog(),
            service_catalog=[],
        )
        self.assertTrue(sensors.doc_match)


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
