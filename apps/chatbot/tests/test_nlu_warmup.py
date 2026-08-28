"""Phase 23 follow-up: the very first NLU call of a freshly (re)started
process pays a full DNS+TCP+TLS handshake to api.openai.com on top of real
inference time, which can tip an otherwise-normal call over the configured
NLU budget — reproduced live via a Django dev-server reload (see ROADMAP).
`ChatbotConfig.ready()` now warms the OpenAI client's connection pool at
process startup, mirroring `apps.knowledge.apps.KnowledgeConfig`'s existing
embedding-model warm-up.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from apps.chatbot.apps import should_warm_up_nlu
from apps.chatbot.nlu.base import NLUError
from apps.chatbot.nlu.factory import warm_up_nlu_provider
from apps.chatbot.nlu.openai_provider import OpenAINLUProvider


class ShouldWarmUpNluTests(SimpleTestCase):
    """Pure argv guard — no Django app-loading involved, safe to call directly."""

    def test_skips_test_runner(self):
        self.assertFalse(should_warm_up_nlu(["manage.py", "test"]))

    def test_skips_migrate_and_makemigrations(self):
        self.assertFalse(should_warm_up_nlu(["manage.py", "migrate"]))
        self.assertFalse(should_warm_up_nlu(["manage.py", "makemigrations"]))

    def test_skips_shell_and_admin_commands(self):
        self.assertFalse(should_warm_up_nlu(["manage.py", "shell"]))
        self.assertFalse(should_warm_up_nlu(["manage.py", "collectstatic"]))
        self.assertFalse(should_warm_up_nlu(["manage.py", "createsuperuser"]))

    def test_skips_eval_and_benchmark_tooling(self):
        # CLAUDE.md: run_chat_eval is explicitly offline/no-live-LLM-calls —
        # warming a real NLU connection for it buys nothing.
        self.assertFalse(should_warm_up_nlu(["manage.py", "run_chat_eval"]))
        self.assertFalse(should_warm_up_nlu(["manage.py", "benchmark_nlu_models"]))

    def test_warms_up_for_runserver(self):
        self.assertTrue(should_warm_up_nlu(["manage.py", "runserver"]))

    def test_warms_up_when_no_subcommand(self):
        # gunicorn/uwsgi import config.wsgi:application directly — argv is
        # the server binary's own, not a manage.py subcommand.
        self.assertTrue(should_warm_up_nlu(["gunicorn", "config.wsgi:application"]))
        self.assertTrue(should_warm_up_nlu(["manage.py"]))


class WarmUpNluProviderTests(SimpleTestCase):
    def test_calls_warm_up_on_the_configured_provider(self):
        fake_provider = MagicMock()
        with patch(
            "apps.chatbot.nlu.factory.get_nlu_provider", return_value=fake_provider
        ):
            warm_up_nlu_provider()
        fake_provider.warm_up.assert_called_once()

    def test_noop_for_a_provider_with_no_warm_up_method(self):
        """Gemini has no persistent-client concept to warm (raw urllib per
        call) and deliberately doesn't define warm_up() — this must not
        raise AttributeError."""

        class _NoWarmUpProvider:
            provider_name = "gemini"

        with patch(
            "apps.chatbot.nlu.factory.get_nlu_provider",
            return_value=_NoWarmUpProvider(),
        ):
            warm_up_nlu_provider()  # must not raise

    def test_swallows_provider_construction_failure(self):
        with patch(
            "apps.chatbot.nlu.factory.get_nlu_provider",
            side_effect=NLUError("Unknown NLU_PROVIDER: 'bogus'"),
        ):
            warm_up_nlu_provider()  # must not raise


class OpenAINLUProviderWarmUpTests(SimpleTestCase):
    def test_noop_when_api_key_missing(self):
        provider = OpenAINLUProvider(model_name="gpt-4.1-mini", api_key="")
        with patch.object(provider, "_get_client") as mock_get_client:
            provider.warm_up()
        mock_get_client.assert_not_called()

    def test_calls_models_list_on_the_cached_client_with_a_short_timeout(self):
        provider = OpenAINLUProvider(model_name="gpt-4.1-mini", api_key="sk-test")
        fake_client = MagicMock()
        with patch.object(provider, "_get_client", return_value=fake_client):
            provider.warm_up()
        fake_client.with_options.assert_called_once_with(timeout=3.0)
        fake_client.with_options.return_value.models.list.assert_called_once()

    def test_failure_is_swallowed_not_raised(self):
        provider = OpenAINLUProvider(model_name="gpt-4.1-mini", api_key="sk-test")
        with patch.object(
            provider, "_get_client", side_effect=RuntimeError("network is down")
        ):
            provider.warm_up()  # must not raise

    def test_warm_up_reuses_the_same_client_a_real_classify_call_would_use(self):
        """The whole point is warming the pool the real call actually uses
        — not a throwaway connection. Assert both paths hit the same
        cached client instance."""
        provider = OpenAINLUProvider(model_name="gpt-4.1-mini", api_key="sk-test")
        fake_client = MagicMock()
        with patch("openai.OpenAI", return_value=fake_client):
            provider.warm_up()
            client_from_warmup = provider._client
            client_from_classify = provider._get_client()
        self.assertIs(client_from_warmup, client_from_classify)
        self.assertIs(client_from_warmup, fake_client)
