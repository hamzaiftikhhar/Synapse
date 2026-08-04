"""Large routing eval battery — rules + heuristics + confidence + lanes."""

from __future__ import annotations

from django.test import SimpleTestCase, override_settings

from apps.chatbot.eval import build_eval_cases, evaluate_cases
from apps.chatbot.routing.confidence import apply_confidence_policy, band_for_confidence
from apps.chatbot.nlu.schemas import parse_nlu_payload


class ConfidencePolicyTests(SimpleTestCase):
    def test_bands(self):
        self.assertEqual(band_for_confidence(0.95).value, "high")
        self.assertEqual(band_for_confidence(0.8).value, "mid")
        self.assertEqual(band_for_confidence(0.5).value, "low")
        self.assertEqual(band_for_confidence(0.2).value, "very_low")

    def test_very_low_with_catalog_prefers_vector(self):
        nlu = parse_nlu_payload(
            {
                "intent": "unknown",
                "confidence": 0.3,
                "clarification_needed": True,
            }
        )
        policy = apply_confidence_policy(
            nlu, has_catalog=True, knowledge_q=True
        )
        self.assertTrue(policy.prefer_vector)
        self.assertTrue(policy.nlu.needs_vector)
        self.assertFalse(policy.nlu.clarification_needed)


@override_settings(
    CHAT_CONFIDENCE_HIGH=0.90,
    CHAT_CONFIDENCE_MID=0.70,
    CHAT_CONFIDENCE_LOW=0.45,
)
class RoutingEvalBatteryTests(SimpleTestCase):
    """500+ paraphrased routing cases — fail if pass rate drops below bar."""

    def test_battery_size_and_pass_rate(self):
        cases = build_eval_cases(target=520)
        self.assertGreaterEqual(len(cases), 500)
        report = evaluate_cases(cases)
        # High bar: routing must be reliable without live LLM
        self.assertGreaterEqual(
            report.pass_rate,
            0.88,
            msg=(
                f"pass_rate={report.pass_rate:.1%} failures={report.failed} "
                f"confusions={report.by_lane_confusion} "
                f"sample={[ (f.expected_family, f.message[:60], f.predicted_lane) for f in report.failures[:8] ]}"
            ),
        )

    def test_duration_never_clinic_hours_intent(self):
        cases = [c for c in build_eval_cases(target=520) if c.expected_family == "duration"]
        report = evaluate_cases(cases)
        bad = [
            f
            for f in report.failures
            if f.predicted_intent == "clinic_hours"
        ]
        self.assertEqual(bad, [], msg=f"duration stolen by clinic_hours: {bad[:5]}")

    def test_find_doctor_please_is_sql(self):
        from apps.chatbot.eval.cases import EvalCase
        from apps.chatbot.eval.runner import evaluate_routing_case

        case = EvalCase(
            case_id="manual-doctor-please",
            message="find me a doctor please",
            expected_lane="sql_fast",
            expected_family="doctors",
            acceptable_lanes=frozenset({"sql_fast"}),
            services=(),
            documents=(),
        )
        result = evaluate_routing_case(case)
        self.assertTrue(result.passed, msg=as_msg(result))
        self.assertEqual(result.predicted_intent, "doctor_search")


def as_msg(result) -> str:
    return (
        f"lane={result.predicted_lane} intent={result.predicted_intent} "
        f"conf={result.confidence} q={result.message!r}"
    )
