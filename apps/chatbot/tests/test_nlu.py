"""Unit tests for Decision Engine, rules, entities, and NLU parsing."""

from django.test import SimpleTestCase, override_settings

from apps.chatbot.nlu.base import NLUError
from apps.chatbot.nlu.decision import EMERGENCY_SAFETY_MESSAGE, DecisionEngine
from apps.chatbot.nlu.entity_extract import (
    extract_emergency_symptoms,
    extract_entities,
    has_symptom_cues,
    looks_like_compound,
)
from apps.chatbot.nlu.intent_entity import IntentEntityService, _apply_confidence_threshold
from apps.chatbot.nlu.json_utils import parse_json_response
from apps.chatbot.nlu.rules import try_rule_classify
from apps.chatbot.nlu.schemas import Intent, Route, parse_nlu_payload


class ParseNLUPayloadTests(SimpleTestCase):
    def test_unknown_intent_fallback(self):
        result = parse_nlu_payload({"intent": "not_a_real_intent", "confidence": 0.5})
        self.assertEqual(result.intent, Intent.UNKNOWN)

    def test_parses_entities_and_flags(self):
        result = parse_nlu_payload(
            {
                "intent": "book_appointment",
                "secondary_intents": ["doctor_availability"],
                "confidence": 0.91,
                "entities": {"specialty": "cardiology", "date": "Tuesday"},
                "needs_sql": True,
                "needs_llm": True,
            },
            provider="gemini",
            model="gemini-1.5-flash",
        )
        self.assertEqual(result.intent, Intent.BOOK_APPOINTMENT)
        self.assertEqual(result.entities.specialty, "cardiology")
        self.assertTrue(result.needs_sql)

    def test_comma_string_becomes_list(self):
        result = parse_nlu_payload(
            {
                "intent": "doctor_availability",
                "entities": {"doctor_name": "rjet, sharma"},
            }
        )
        self.assertEqual(result.entities.doctor_name, ["rjet", "sharma"])

    def test_confidence_clamped(self):
        result = parse_nlu_payload({"intent": "greeting", "confidence": 5})
        self.assertEqual(result.confidence, 1.0)


class JsonUtilsTests(SimpleTestCase):
    def test_strips_markdown_fence(self):
        data = parse_json_response('```json\n{"intent": "greeting"}\n```')
        self.assertEqual(data["intent"], "greeting")

    def test_empty_raises(self):
        with self.assertRaises(NLUError):
            parse_json_response("   ")


class DecisionEngineTests(SimpleTestCase):
    def test_emergency_route(self):
        nlu = parse_nlu_payload(
            {
                "intent": "emergency",
                "confidence": 0.99,
                "is_emergency": True,
                "can_respond_directly": True,
            }
        )
        decision = DecisionEngine.decide(nlu)
        self.assertEqual(decision.route, Route.EMERGENCY)
        self.assertEqual(decision.safety_message, EMERGENCY_SAFETY_MESSAGE)

    def test_clarify_route(self):
        nlu = parse_nlu_payload(
            {
                "intent": "unknown",
                "clarification_needed": True,
                "clarification_question": "Which doctor?",
            }
        )
        self.assertEqual(DecisionEngine.decide(nlu).route, Route.CLARIFY)

    def test_direct_greeting(self):
        nlu = parse_nlu_payload(
            {"intent": "greeting", "confidence": 0.98, "can_respond_directly": True}
        )
        self.assertEqual(DecisionEngine.decide(nlu).route, Route.DIRECT_RESPONSE)

    def test_sql_only_booking_flags(self):
        # needs_llm without needs_vector is dropped — booking uses SQL_ONLY at decision;
        # ChatEngine maps book intents to the booking lane separately.
        nlu = parse_nlu_payload(
            {"intent": "book_appointment", "needs_sql": True, "needs_llm": True}
        )
        decision = DecisionEngine.decide(nlu)
        self.assertEqual(decision.route, Route.SQL_ONLY)
        self.assertFalse(decision.needs_llm)


class RuleClassifierTests(SimpleTestCase):
    def test_greeting_fast_path(self):
        for msg in ("Hi there!", "hi, how are you?", "hi how are you doing?"):
            hit = try_rule_classify(msg, tier="fast")
            self.assertIsNotNone(hit, msg)
            self.assertEqual(hit["intent"], "greeting", msg)

    def test_how_is_everything_going_is_a_greeting_not_an_llm_round_trip(self):
        """Regression: "how is everything going on" fell through the
        existing "how are you" rule coverage (close but not an exact/regex
        match), burning a full LLM call that landed on intent=faq and an
        oddly formal clarify reply for what's plainly small talk."""
        for msg in (
            "how is everything going on",
            "how's everything going on?",
            "How is everything going",
            "how's everything",
        ):
            hit = try_rule_classify(msg, tier="fast")
            self.assertIsNotNone(hit, msg)
            self.assertEqual(hit["intent"], "greeting", msg)

    def test_fast_path_does_not_steal_booking_with_schedule(self):
        """Booking language must reach Small LLM — rules_fast used to return
        book_appointment with empty entities and dump the discovery wizard."""
        hit = try_rule_classify(
            "can you please help me to book a slot of doctor for 9 pm wednesday",
            tier="fast",
        )
        self.assertIsNone(hit)

    def test_negation_blocks_reschedule(self):
        hit = try_rule_classify("I dont want to reschedule it", tier="strong")
        self.assertIsNone(hit)

    def test_book_appointment_with_entities(self):
        hit = try_rule_classify(
            "can you please book an appointment for tomorrow morning?",
            tier="strong",
        )
        self.assertIsNotNone(hit)
        self.assertEqual(hit["intent"], "book_appointment")
        self.assertIn("tomorrow", hit["entities"]["date"])
        self.assertIn("morning", hit["entities"]["time"])

    def test_doctor_name_extracted_on_book(self):
        hit = try_rule_classify(
            "Is dr rajat available tomorrow? I want to schedule an appointment",
            tier="strong",
        )
        # Compound with "?" x1 and schedule — may be strong or bypassed as compound
        # "and" not present; single ?. Should match book with doctor.
        if hit is None:
            # compound detector may skip — still extract entities works
            entities = extract_entities(
                "Is dr rajat available tomorrow? I want to schedule an appointment"
            )
            self.assertIsNotNone(entities["doctor_name"])
            self.assertTrue(
                any("rajat" in n.lower() for n in entities["doctor_name"])
            )
        else:
            self.assertEqual(hit["intent"], "book_appointment")
            names = hit["entities"]["doctor_name"]
            self.assertTrue(any("rajat" in n.lower() for n in names))

    def test_insurance_extracts_provider(self):
        hit = try_rule_classify(
            "do you guys accept blue cross origin insurance?",
            tier="strong",
        )
        self.assertIsNotNone(hit)
        self.assertEqual(hit["intent"], "insurance_accepted")
        providers = hit["entities"]["insurance_provider"]
        self.assertTrue(any("blue cross" in p.lower() for p in providers))

    def test_compound_skips_strong_rules(self):
        hit = try_rule_classify(
            "do you accept blue cross? also tell can dr rajat treat me tomorrow?",
            tier="strong",
        )
        self.assertIsNone(hit)

    def test_services_and_faq_rules(self):
        hit = try_rule_classify("What services do you provide?", tier="strong")
        self.assertIsNotNone(hit)
        self.assertEqual(hit["intent"], "services_offered")

        hit = try_rule_classify("Do I need referrals for specialists?", tier="strong")
        self.assertIsNotNone(hit)
        self.assertEqual(hit["intent"], "faq")

    def test_medicaid_entity_clean(self):
        hit = try_rule_classify(
            "Do you accept Medicaid for adult primary care?",
            tier="strong",
        )
        self.assertIsNotNone(hit)
        self.assertEqual(hit["entities"]["insurance_provider"], ["Medicaid"])


    def test_availability_slots_rule(self):
        hit = try_rule_classify(
            "are there any slots available for tomorrow?",
            tier="strong",
        )
        self.assertIsNotNone(hit)
        self.assertEqual(hit["intent"], "doctor_availability")

    def test_informal_fit_me_in_reaches_availability_not_faq(self):
        """Regression: these exact phrasings reached the Small LLM in
        production and were sometimes classified as faq instead of
        doctor_availability, stranding the patient in prose negotiation
        instead of ever running real SQL availability. Must be caught at
        the fast tier (unconditional pre-LLM), not the dormant strong tier
        (opt-in via NLU_RULES_BEFORE_LLM, off by default)."""
        for msg, expect_date in (
            ("can you hope me in for tue night", "tue"),
            ("can you slip me in for sat morning", None),
            ("can you hop me in tomorrow", "tomorrow"),
            ("can you fit me in this week", "this week"),
            ("can you pencil me in for friday", "friday"),
        ):
            with self.subTest(msg=msg):
                hit = try_rule_classify(msg, tier="fast")
                self.assertIsNotNone(hit, msg)
                self.assertEqual(hit["intent"], "doctor_availability")
                self.assertEqual(hit["_classifier_source"], "rules_fast")
                if expect_date:
                    self.assertIn(expect_date, hit["entities"]["date"])
                else:
                    self.assertIsNotNone(hit["entities"]["date"])

    def test_fast_path_hours_yields_to_llm_when_message_is_compound(self):
        """Regression: "what are your hours and where are you located" used
        to short-circuit at the fast tier on "hours" alone, so the LLM never
        saw the "and where are you located" half — the second request was
        silently dropped with no secondary_intents chance at all. A fast-tier
        rule can only ever answer the part it matched, so a compound message
        must fall through to the LLM instead (reuses looks_like_compound,
        the same guard already gating the strong tier just below)."""
        for msg in (
            "what are your hours and where are you located",
            "when do you open and what's your address",
        ):
            with self.subTest(msg=msg):
                hit = try_rule_classify(msg, tier="fast")
                self.assertIsNone(hit, msg)

    def test_fast_path_hours_still_fires_for_a_plain_single_request(self):
        """The compound guard must not make the fast path itself dormant —
        an ordinary, non-compound hours question still short-circuits."""
        hit = try_rule_classify("what are your hours", tier="fast")
        self.assertIsNotNone(hit)
        self.assertEqual(hit["intent"], "clinic_hours")
        self.assertEqual(hit["_classifier_source"], "rules_fast")

    def test_fit_me_in_false_positive_guards(self):
        """"hope"/"work" are common words — must not fire outside the
        specific "<verb> me in" idiom."""
        for msg in (
            "I hope the doctor is available",
            "I hope you can help me",
            "can you work on my prescription",
        ):
            with self.subTest(msg=msg):
                hit = try_rule_classify(msg, tier="fast")
                if hit is not None:
                    self.assertNotEqual(hit["intent"], "doctor_availability", msg)

    def test_squeeze_me_in_unaffected_by_fast_tier_change(self):
        """"squeeze me in" is deliberately not part of the new fast-tier
        pattern — it stays governed by the separate, pre-existing
        strong-tier rule only (dormant by default; entangled with the
        long-standing adversarial_booking_slang_squeeze eval case, out of
        scope here). Confirms this fix didn't touch that."""
        hit = try_rule_classify("yo can yall squeeze me in today", tier="fast")
        self.assertIsNone(hit)

    def test_emergency_symptoms_clean(self):
        text = "I have intense chest pain and left arm numbness, when can I see a doctor?"
        hit = try_rule_classify(text, tier="safety")
        self.assertIsNotNone(hit)
        self.assertTrue(hit["is_emergency"])
        self.assertEqual(
            hit["entities"]["symptom"],
            extract_emergency_symptoms(text),
        )
        self.assertIn("chest pain", hit["entities"]["symptom"])
        self.assertNotEqual(hit["entities"]["symptom"], text)

    def test_emergency_narrative_chest_pressure(self):
        hit = try_rule_classify(
            "chest pressure into my arm for an hour right now",
            tier="safety",
        )
        self.assertIsNotNone(hit)
        self.assertTrue(hit["is_emergency"])
        self.assertEqual(hit["intent"], "emergency")

    def test_informational_stroke_question_is_not_emergency(self):
        """Phase 40: real HealthSearchQA samples "What are the 4 causes of a
        stroke?" and (a larger follow-up sample) "What is shortness of
        breath symptom of?" were hard-triggering the 911 override — these
        are EMERGENCY_RE/SYMPTOM_CUE_RE terms with no narrative-phrase
        anchor, so any WH question about the condition matched them too."""
        for text in (
            "What are the 4 causes of a stroke?",
            "What causes a heart attack?",
            "What are the warning signs of a heart attack?",
            "How is a stroke treated?",
            "What is shortness of breath symptom of?",
            "What causes difficulty breathing?",
        ):
            with self.subTest(text=text):
                self.assertIsNone(try_rule_classify(text, tier="safety"))
                self.assertFalse(has_symptom_cues(text))

    def test_live_stroke_or_heart_attack_report_still_emergency(self):
        """The informational-question exception must not swallow a real,
        currently-happening report phrased the same way a WH question
        would be ("is this a stroke")."""
        for text in (
            "I think I'm having a stroke right now",
            "my dad is having a heart attack",
            "is this a stroke",
            "I have chest pain",
            "I'm having shortness of breath",
            "she has difficulty breathing right now",
        ):
            with self.subTest(text=text):
                hit = try_rule_classify(text, tier="safety")
                self.assertIsNotNone(hit, text)
                self.assertTrue(hit["is_emergency"], text)

        # has_symptom_cues (SYMPTOM_CUE_RE) never covered "difficulty
        # breathing" in the first place (pre-existing, out of scope here) —
        # checked separately against only the terms it does recognize.
        for text in (
            "I think I'm having a stroke right now",
            "my dad is having a heart attack",
            "is this a stroke",
            "I have chest pain",
            "I'm having shortness of breath",
        ):
            with self.subTest(text=text):
                self.assertTrue(has_symptom_cues(text), text)
                self.assertTrue(has_symptom_cues(text), text)

    def test_low_confidence_triggers_clarify(self):
        nlu = parse_nlu_payload({"intent": "unknown", "confidence": 0.5})
        adjusted = _apply_confidence_threshold(nlu)
        self.assertTrue(adjusted.clarification_needed)


class EntityExtractTests(SimpleTestCase):
    def test_multi_doctor_names(self):
        entities = extract_entities("Is dr rjet or dr. sharma available this friday?")
        names = [n.lower() for n in entities["doctor_name"]]
        self.assertTrue(any("rjet" in n for n in names))
        self.assertTrue(any("sharma" in n for n in names))

    def test_trailing_temporal_words_are_not_surnames(self):
        cases = (
            ("can you please book me with dr maya yesterday afternoon", "maya"),
            ("book appointment with dr maya instantly", "maya"),
            ("is dr lin available immediately", "lin"),
            ("see dr hamza tomorrow morning", "hamza"),
        )
        for message, expected in cases:
            with self.subTest(message=message):
                names = [n.lower() for n in (extract_entities(message)["doctor_name"] or [])]
                self.assertTrue(any(expected in n for n in names), names)
                self.assertFalse(
                    any(
                        junk in n
                        for n in names
                        for junk in ("yesterday", "instantly", "immediately", "tomorrow")
                    ),
                    names,
                )

    def test_two_part_name_survives_a_following_day_word(self):
        names = [n.lower() for n in extract_entities(
            "book with dr maya lin tomorrow afternoon"
        )["doctor_name"]]
        self.assertTrue(any("maya" in n and "lin" in n for n in names), names)

    def test_specialty_and_insurance(self):
        entities = extract_entities(
            "book an appointment with a dermatologist tomorrow, and also do you accept Aetna PPO?"
        )
        self.assertIn("dermatologist", entities["specialty"])
        self.assertTrue(
            any("aetna" in p.lower() for p in entities["insurance_provider"])
        )

    def test_day_abbreviations_extracted(self):
        for message, token in (
            ("is there any doctor available on thurs afternoon", "thurs"),
            ("is there any doctor available on fri afternoon", "fri"),
            ("is there any doctor available on sun afternoon", "sun"),
            ("anything on tues", "tues"),
        ):
            with self.subTest(message=message):
                dates = extract_entities(message)["date"]
                self.assertIsNotNone(dates, f"no date entity for {message!r}")
                self.assertTrue(
                    any(token in d for d in dates),
                    f"{token!r} missing from {dates!r}",
                )

    def test_sun_words_are_not_read_as_sunday(self):
        # A dermatology clinic talks about sun constantly — none of it is a day.
        for message in (
            "i have sun damage on my cheeks",
            "do you treat sunburn",
            "which sunscreen do you recommend",
            "we picked a date after the wedding",
        ):
            with self.subTest(message=message):
                self.assertIsNone(extract_entities(message)["date"])


@override_settings(
    NLU_ENABLE_RULES=False,
    NLU_RULES_BEFORE_LLM=False,
    NLU_CONFIDENCE_THRESHOLD=0.75,
    NLU_API_TIMEOUT_SECONDS=6.5,
)
class IntentEntityServiceMockedTests(SimpleTestCase):
    def test_analyze_with_fake_provider(self):
        class FakeProvider:
            provider_name = "gemini"
            model_name = "gemini-1.5-flash"

            def classify(self, *, message, conversation_context=None, timeout=None):
                return {
                    "intent": "clinic_hours",
                    "confidence": 0.9,
                    "entities": {"date": "Saturday"},
                    "needs_sql": True,
                    "needs_vector": True,
                    "needs_llm": True,
                    "_usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 20,
                        "total_tokens": 30,
                    },
                }

        class FakeClinic:
            id = "00000000-0000-0000-0000-000000000001"

        service = IntentEntityService(provider=FakeProvider())
        from unittest.mock import patch

        with (
            patch(
                "apps.chatbot.nlu.intent_entity.resolve_entities",
                return_value=parse_nlu_payload({}).resolved_ids,
            ),
            patch.object(IntentEntityService, "_log_usage"),
        ):
            result = service.analyze(
                clinic=FakeClinic(),  # type: ignore[arg-type]
                message="What are your Saturday hours?",
                log_usage=False,
            )

        self.assertEqual(result.intent, Intent.CLINIC_HOURS)
        self.assertEqual(DecisionEngine.decide(result).route, Route.SQL_VECTOR_LLM)

    def test_timeout_returns_clarify_fallback(self):
        class SlowProvider:
            provider_name = "gemini"
            model_name = "gemini-3.1-flash-lite"

            def classify(self, *, message, conversation_context=None, timeout=None):
                raise NLUError(f"Gemini API timed out after {timeout}s")

        class FakeClinic:
            id = "00000000-0000-0000-0000-000000000001"

        service = IntentEntityService(provider=SlowProvider())
        from unittest.mock import patch

        with (
            patch(
                "apps.chatbot.nlu.intent_entity.resolve_entities",
                return_value=parse_nlu_payload({}).resolved_ids,
            ),
            patch.object(IntentEntityService, "_log_usage"),
            override_settings(NLU_FALLBACK_OPENAI=False, NLU_ENABLE_RULES=True),
        ):
            result = service.analyze(
                clinic=FakeClinic(),  # type: ignore[arg-type]
                message="are there any slots available for tomorrow?",
                log_usage=False,
            )

        # Degraded clarify — never invent availability from timeout
        self.assertTrue(result.clarification_needed or result.intent == Intent.UNKNOWN)
        self.assertLess(result.timings.total_ms, 100)
        self.assertLessEqual(result.confidence, 0.5)


class _FakeClock:
    """Deterministic monotonic clock — advances only when a provider is called."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _RecordingProvider:
    """Records the timeout it was handed and burns that much simulated time."""

    def __init__(self, name, clock, *, burn=None, payload=None):
        self.provider_name = name
        self.model_name = f"{name}-model"
        self._clock = clock
        self._burn = burn
        self._payload = payload
        self.timeouts: list[float] = []

    def classify(self, *, message, conversation_context=None, timeout=None):
        self.timeouts.append(timeout)
        self._clock.advance(self._burn if self._burn is not None else float(timeout))
        if self._payload is not None:
            return dict(self._payload)
        raise NLUError(f"{self.provider_name} API timed out after {timeout}s")


@override_settings(
    NLU_ENABLE_RULES=False,
    NLU_RULES_BEFORE_LLM=False,
    NLU_API_TIMEOUT_SECONDS=3.5,
    NLU_TOTAL_BUDGET_SECONDS=5.0,
)
class NLUTotalBudgetTests(SimpleTestCase):
    """One deadline across the provider chain — attempts cannot stack timeouts.

    Deterministic: a fake monotonic clock advances by exactly the timeout each
    provider is handed, so nothing depends on real wall-clock timing.
    """

    MESSAGE = "what are your saturday hours"

    def setUp(self):
        from apps.chatbot.providers import circuit_breaker

        circuit_breaker.reset()
        self.addCleanup(circuit_breaker.reset)

    # Caps _provider_attempts() builds in production: primary uncapped (falls
    # back to NLU_API_TIMEOUT_SECONDS), then min(NLU_API_TIMEOUT_SECONDS, 3.0).
    CAPS = [None, 3.0, 3.0]

    def _run(self, providers):
        """Run classify_message against a fixed chain with per-provider caps."""
        from unittest.mock import patch

        from apps.chatbot.nlu import classifier

        clock = providers[0]._clock
        attempts = [
            {"name": p.provider_name, "provider": p, "timeout": cap}
            for p, cap in zip(providers, self.CAPS)
        ]
        with (
            patch.object(classifier, "_provider_attempts", return_value=attempts),
            patch.object(classifier.time, "monotonic", clock),
        ):
            result = classifier.classify_message(message=self.MESSAGE)
        return result, clock

    def _chain(self, *, primary_payload=None):
        """Production-shaped chain: openai 3.5s → openai_fallback 3.0s → gemini 3.0s."""
        clock = _FakeClock()
        return [
            _RecordingProvider("openai", clock, payload=primary_payload),
            _RecordingProvider("openai_fallback", clock),
            _RecordingProvider("gemini", clock),
        ]

    def test_primary_keeps_its_full_per_provider_cap(self):
        chain = self._chain()
        self._run(chain)
        # Not budget/3 — the primary's own cap is preserved so today's
        # successful ~2.3s classifications keep succeeding.
        self.assertEqual(chain[0].timeouts, [3.5])

    def test_second_attempt_gets_only_the_remaining_budget(self):
        chain = self._chain()
        self._run(chain)
        # 5.0 budget - 3.5 spent = 1.5, which is below its own 3.0 cap.
        self.assertEqual(chain[1].timeouts, [1.5])

    def test_exhausted_budget_skips_provider_without_tripping_breaker(self):
        from apps.chatbot.providers import circuit_breaker

        chain = self._chain()
        self._run(chain)
        self.assertEqual(chain[2].timeouts, [])
        self.assertEqual(circuit_breaker.status("gemini")["failures"], 0)
        self.assertFalse(circuit_breaker.status("gemini")["open"])

    def test_total_attempt_budget_is_never_exceeded(self):
        chain = self._chain()
        _, clock = self._run(chain)
        handed_out = sum(t for p in chain for t in p.timeouts)
        self.assertLessEqual(handed_out, 5.0)
        self.assertLessEqual(clock.now - 1000.0, 5.0)

    def test_all_providers_failing_still_returns_degraded_clarify(self):
        chain = self._chain()
        result, _ = self._run(chain)
        self.assertEqual(result["_classifier_source"], "rules_fallback")
        self.assertTrue(result["_degraded"])
        self.assertTrue(result["clarification_needed"])

    def test_successful_primary_does_not_consume_fallbacks(self):
        chain = self._chain(
            primary_payload={"intent": "clinic_hours", "confidence": 0.9, "entities": {}}
        )
        result, _ = self._run(chain)
        self.assertEqual(result["intent"], "clinic_hours")
        self.assertEqual(chain[1].timeouts, [])
        self.assertEqual(chain[2].timeouts, [])

    def test_slow_primary_leaves_nothing_for_the_chain(self):
        clock = _FakeClock()
        chain = [
            _RecordingProvider("openai", clock, burn=5.0),
            _RecordingProvider("openai_fallback", clock),
            _RecordingProvider("gemini", clock),
        ]
        self._run(chain)
        self.assertEqual(chain[0].timeouts, [3.5])
        self.assertEqual(chain[1].timeouts, [])
        self.assertEqual(chain[2].timeouts, [])

    def test_real_session_total_outage_converges_to_instant_degradation(self):
        """Simulates what the original bug report actually was: a patient
        sending several messages back to back while every configured
        provider is down. Each of Cursor's other tests resets the circuit
        breaker per call, which is right for isolating the budget math, but
        none of them show what a real multi-turn conversation experiences
        over a sustained outage.

        First finding (not a bug, just not obvious from a single call):
        openai_fallback fails on every turn same as openai, so its breaker
        opens in lockstep with openai's after 5 turns. gemini, third in the
        chain, gets starved of budget for those first 5 turns and is never
        actually called — so it hasn't accumulated any failures yet, and
        turn 6 hands it the *entire* budget alone. Only after 5 more turns
        of gemini failing on its own does its breaker finally open too.

        The reassuring end state: once all three breakers are open, the
        whole provider loop skips every attempt without touching the clock
        at all, and classify_message returns near-instantly instead of
        continuing to pay latency turn after turn during a real outage.
        """
        chain = self._chain()  # same 3.5s/3.0s/3.0s production-shaped chain

        # Turns 0-4: openai (3.5s) then openai_fallback (leftover 1.5s) are
        # tried every time; gemini never gets reached (budget exhausted).
        # LLM_CIRCUIT_FAILURE_THRESHOLD defaults to 5 consecutive failures,
        # so both of their breakers open right at the end of this block.
        for turn in range(5):
            result, _ = self._run(chain)
            self.assertTrue(result["_degraded"], f"turn {turn} should still degrade")
            self.assertEqual(chain[0].timeouts[turn], 3.5)
            self.assertEqual(chain[1].timeouts[turn], 1.5)
        self.assertEqual(chain[2].timeouts, [], "gemini never reached — budget ran out first")

        # Turns 5-9: openai and openai_fallback are now skipped via the
        # breaker (not attempted, not timed out again) — gemini alone gets
        # the freed-up budget, capped at its own 3.0s, for 5 more turns
        # until its failures reach the same threshold.
        for turn in range(5):
            result, _ = self._run(chain)
            self.assertTrue(result["_degraded"], f"turn {5 + turn} should still degrade")
            self.assertEqual(chain[2].timeouts[turn], 3.0)
        self.assertEqual(len(chain[0].timeouts), 5, "openai stayed skipped")
        self.assertEqual(len(chain[1].timeouts), 5, "openai_fallback stayed skipped")

        # Turn 10: total outage — all three breakers are open. The loop
        # should skip every attempt without calling any provider or
        # advancing the clock, and still return the same degraded fallback
        # a patient would have gotten on turn 0, just without paying ~5s
        # of latency for it.
        clock_before = chain[0]._clock.now
        result, clock = self._run(chain)
        self.assertTrue(result["_degraded"])
        self.assertEqual(result["_classifier_source"], "rules_fallback")
        self.assertEqual(len(chain[0].timeouts), 5)
        self.assertEqual(len(chain[1].timeouts), 5)
        self.assertEqual(len(chain[2].timeouts), 5)
        self.assertEqual(clock.now, clock_before, "no provider was actually called")


class LooksLikeCompoundCoverageTests(SimpleTestCase):
    """Phase 2 eval slice: _COMPOUND_RE missed real casual patient phrasing
    -- an apostrophe-less contraction ("whats") right after "and" doesn't
    match a plain \\bwhat\\b boundary, and a comma-joined second question
    with no "and" at all wasn't covered by any alternative. Both were
    live-confirmed to let a genuinely compound message get silently
    resolved to a single intent (see routing/signals.py::
    is_unresolved_compound and its callers). These lock in recognition
    itself, independent of the downstream lane outcome, so a future
    rewiring of the guard can't silently regress the detector while still
    passing at the lane-eval level for the wrong reason."""

    def test_and_contraction_without_apostrophe_is_recognized(self):
        for msg in (
            "are you open sunday and whats your address",
            "tell me about Dr Lee and is he available friday",
            "who is your best dentist and are they free tomorrow",
        ):
            with self.subTest(msg=msg):
                self.assertTrue(looks_like_compound(msg))

    def test_comma_joined_second_question_is_recognized(self):
        self.assertTrue(
            looks_like_compound("whats the cost of a filling, do you offer root canals too")
        )

    def test_same_category_conjunction_is_not_falsely_flagged(self):
        for msg in ("Do you accept Aetna and Cigna?", "Do you accept Aetna or Blue Cross?"):
            with self.subTest(msg=msg):
                self.assertFalse(looks_like_compound(msg))

    def test_dental_symptom_compound_queries_are_recognized(self):
        """From ROADMAP.md's dental-vocabulary 30-query set (group F):
        confirms the Phase 2 compound guard and the dental keyword fix
        compose correctly -- a message that's both dental-symptom-shaped
        AND compound must still be recognized as compound, so it clarifies
        instead of the sensor-driven paths (specialty_list/service_list/
        doctor_availability_query) silently locking onto just one half."""
        for msg in (
            "do you do whitening and is anyone free tomorrow",
            "I have a cavity and also want to know your hours",
        ):
            with self.subTest(msg=msg):
                self.assertTrue(looks_like_compound(msg))
