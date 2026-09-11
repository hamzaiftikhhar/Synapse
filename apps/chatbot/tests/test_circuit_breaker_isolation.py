"""Circuit-breaker workload isolation.

Confirmed root cause (live investigation): nlu/classifier.py and
response_llm.py (including capability_resolver.py, which routes through
_call_response_llm) all keyed the circuit breaker on the bare provider
name ("openai"/"gemini") -- a burst of failures from any one of them
could open the shared circuit and silence the others for the full
LLM_CIRCUIT_COOLDOWN_SECONDS window. Fixed by namespacing the key as
f"{provider}:{workload}" at each call site (openai:nlu, openai:response,
openai:capability) -- circuit_breaker.py itself is unchanged, still a
plain string-keyed dict.
"""

from __future__ import annotations

from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from apps.chatbot.providers import circuit_breaker


class CircuitBreakerKeyIsolationTests(SimpleTestCase):
    """Unit-level: circuit_breaker.py itself already treats any two
    distinct string keys as fully independent state -- these tests pin
    that down explicitly for the exact namespaced keys now in use, so a
    future change to the key format can't silently reintroduce coupling
    without a test noticing."""

    def setUp(self):
        circuit_breaker.reset()

    def tearDown(self):
        circuit_breaker.reset()

    @override_settings(LLM_CIRCUIT_FAILURE_THRESHOLD=3)
    def test_capability_failures_do_not_open_nlu_circuit(self):
        for _ in range(3):
            circuit_breaker.record_failure("openai:capability", "timeout")
        self.assertFalse(circuit_breaker.is_available("openai:capability"))
        self.assertTrue(circuit_breaker.is_available("openai:nlu"))

    @override_settings(LLM_CIRCUIT_FAILURE_THRESHOLD=3)
    def test_response_failures_do_not_open_nlu_circuit(self):
        for _ in range(3):
            circuit_breaker.record_failure("openai:response", "timeout")
        self.assertFalse(circuit_breaker.is_available("openai:response"))
        self.assertTrue(circuit_breaker.is_available("openai:nlu"))

    @override_settings(LLM_CIRCUIT_FAILURE_THRESHOLD=3)
    def test_nlu_failures_do_not_open_capability_circuit(self):
        for _ in range(3):
            circuit_breaker.record_failure("openai:nlu", "timeout")
        self.assertFalse(circuit_breaker.is_available("openai:nlu"))
        self.assertTrue(circuit_breaker.is_available("openai:capability"))

    @override_settings(LLM_CIRCUIT_FAILURE_THRESHOLD=3)
    def test_nlu_failures_do_not_open_response_circuit(self):
        for _ in range(3):
            circuit_breaker.record_failure("openai:nlu", "timeout")
        self.assertTrue(circuit_breaker.is_available("openai:response"))

    @override_settings(LLM_CIRCUIT_FAILURE_THRESHOLD=3)
    def test_three_workloads_of_the_same_provider_are_fully_independent(self):
        keys = ["openai:nlu", "openai:response", "openai:capability"]
        for i, key in enumerate(keys):
            for _ in range(i + 1):  # 1, 2, 3 failures respectively
                circuit_breaker.record_failure(key, "timeout")
        self.assertTrue(circuit_breaker.is_available("openai:nlu"))  # 1 failure
        self.assertTrue(circuit_breaker.is_available("openai:response"))  # 2 failures
        self.assertFalse(circuit_breaker.is_available("openai:capability"))  # 3 = threshold

    @override_settings(LLM_CIRCUIT_FAILURE_THRESHOLD=3, LLM_CIRCUIT_COOLDOWN_SECONDS=600.0)
    def test_cooldown_and_reset_still_work_with_a_namespaced_key(self):
        """The threshold/cooldown state machine itself is unchanged --
        this just confirms namespacing the key didn't break it."""
        key = "openai:capability"
        for _ in range(3):
            circuit_breaker.record_failure(key, "timeout")
        self.assertFalse(circuit_breaker.is_available(key))
        status = circuit_breaker.status(key)
        self.assertTrue(status["open"])
        self.assertEqual(status["failures"], 3)
        self.assertIn("timeout", status["last_error"])

        circuit_breaker.record_success(key)
        self.assertTrue(circuit_breaker.is_available(key))
        status = circuit_breaker.status(key)
        self.assertEqual(status["failures"], 0)
        self.assertFalse(status["open"])

    def test_timeout_and_quota_errors_remain_distinguishable_in_status(self):
        """The breaker itself doesn't classify error types -- it just
        stores whatever string the caller passed -- confirming that
        distinction survives into `status()` for later inspection."""
        circuit_breaker.record_failure("openai:nlu", "TimeoutError: operation exceeded 3.5s")
        self.assertIn("Timeout", circuit_breaker.status("openai:nlu")["last_error"])

        circuit_breaker.reset("openai:nlu")
        circuit_breaker.record_failure(
            "openai:nlu", "RateLimitError: insufficient_quota (429)"
        )
        self.assertIn("quota", circuit_breaker.status("openai:nlu")["last_error"])


class ResponseLlmWorkloadIsolationTests(SimpleTestCase):
    """Integration-level: response_llm._call_response_llm actually passes
    the namespaced key through to the real circuit breaker calls."""

    def setUp(self):
        circuit_breaker.reset()

    def tearDown(self):
        circuit_breaker.reset()

    @override_settings(
        CHAT_RESPONSE_PROVIDER="openai",
        CHAT_RESPONSE_SECONDARY_PROVIDER="",
        LLM_CIRCUIT_FAILURE_THRESHOLD=2,
    )
    def test_capability_workload_failures_open_only_the_capability_key(self):
        from apps.chatbot.response_llm import _call_response_llm

        with patch(
            "apps.chatbot.response_llm._openai_generate",
            side_effect=RuntimeError("boom"),
        ):
            for _ in range(2):
                # _call_response_llm re-raises whatever the provider raised
                # (here RuntimeError) once every provider is exhausted --
                # not always ResponseLLMError. Only its identity matters
                # for this test, not its type.
                with self.assertRaises(RuntimeError):
                    _call_response_llm(
                        system="s", user_block="u", workload="capability"
                    )

        self.assertFalse(circuit_breaker.is_available("openai:capability"))
        self.assertTrue(circuit_breaker.is_available("openai:response"))
        self.assertTrue(circuit_breaker.is_available("openai:nlu"))

    @override_settings(
        CHAT_RESPONSE_PROVIDER="openai",
        CHAT_RESPONSE_SECONDARY_PROVIDER="",
        LLM_CIRCUIT_FAILURE_THRESHOLD=2,
    )
    def test_default_workload_is_response_and_does_not_touch_capability(self):
        from apps.chatbot.response_llm import _call_response_llm

        with patch(
            "apps.chatbot.response_llm._openai_generate",
            side_effect=RuntimeError("boom"),
        ):
            for _ in range(2):
                with self.assertRaises(RuntimeError):
                    _call_response_llm(system="s", user_block="u")

        self.assertFalse(circuit_breaker.is_available("openai:response"))
        self.assertTrue(circuit_breaker.is_available("openai:capability"))

    @override_settings(CHAT_RESPONSE_PROVIDER="openai", CHAT_RESPONSE_SECONDARY_PROVIDER="")
    def test_a_healthy_capability_call_never_opens_the_response_circuit(self):
        from apps.chatbot.response_llm import _call_response_llm

        with patch(
            "apps.chatbot.response_llm._openai_generate", return_value="ok"
        ):
            text = _call_response_llm(system="s", user_block="u", workload="capability")
        self.assertEqual(text, "ok")
        self.assertTrue(circuit_breaker.is_available("openai:response"))


class NluClassifierWorkloadIsolationTests(SimpleTestCase):
    """Integration-level: nlu/classifier.py's own circuit-breaker calls
    use the openai:nlu / gemini:nlu namespace and cannot be affected by,
    or affect, the response/capability workloads."""

    def setUp(self):
        circuit_breaker.reset()

    def tearDown(self):
        circuit_breaker.reset()

    def _failing_provider(self, name="openai"):
        from apps.chatbot.nlu.base import NLUError

        class _FailingProvider:
            provider_name = name
            model_name = "test-model"

            def classify(self, *, message, conversation_context=None, timeout=None):
                raise NLUError("simulated timeout")

        return _FailingProvider()

    @override_settings(LLM_CIRCUIT_FAILURE_THRESHOLD=2)
    def test_nlu_failures_open_only_the_nlu_key(self):
        """classify_message never raises on a provider failure -- it falls
        through to a rules-based result (safety/fallback rules, or a final
        generic classification). What this test actually verifies is the
        circuit-breaker side effect of those failed attempts, independent
        of whatever classify_message ultimately returns."""
        from apps.chatbot.nlu.classifier import classify_message

        provider = self._failing_provider("openai")
        for _ in range(2):
            classify_message(message="xyzzy plugh unrelated text", provider=provider)

        self.assertFalse(circuit_breaker.is_available("openai:nlu"))
        self.assertTrue(circuit_breaker.is_available("openai:response"))
        self.assertTrue(circuit_breaker.is_available("openai:capability"))

    @override_settings(LLM_CIRCUIT_FAILURE_THRESHOLD=2)
    def test_capability_circuit_being_open_does_not_block_nlu(self):
        """The other direction: pre-open the capability circuit, confirm
        NLU classification (a healthy provider) is completely unaffected."""
        from apps.chatbot.nlu.classifier import classify_message

        for _ in range(2):
            circuit_breaker.record_failure("openai:capability", "timeout")
        self.assertFalse(circuit_breaker.is_available("openai:capability"))

        class _HealthyProvider:
            provider_name = "openai"
            model_name = "test-model"

            def classify(self, *, message, conversation_context=None, timeout=None):
                return {
                    "intent": "greeting",
                    "confidence": 0.9,
                    "entities": {},
                    "needs_sql": False,
                    "needs_vector": False,
                    "needs_llm": False,
                }

        result = classify_message(message="hi", provider=_HealthyProvider())
        self.assertEqual(result["intent"], "greeting")
