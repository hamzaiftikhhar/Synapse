"""Embedding warm-up is a no-op now that local SentenceTransformer is gone.

The argv skip list on KnowledgeConfig.ready() is still real (it must not
tax `manage.py test` / migrate if warm-up ever does work again). OpenAI
embeddings are an HTTP call with nothing to preload, so
warm_up_embedding_service() must never import torch or download a model —
including when a leftover EMBEDDING_PROVIDER=local is still in the env.
"""

from __future__ import annotations

from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from apps.knowledge.apps import should_warm_up_embeddings
from apps.knowledge.embeddings.factory import (
    reset_embedding_service,
    warm_up_embedding_service,
)


class ShouldWarmUpEmbeddingsTests(SimpleTestCase):
    """Pure argv guard — no Django app-loading involved, safe to call directly."""

    def test_skips_test_runner(self):
        self.assertFalse(should_warm_up_embeddings(["manage.py", "test"]))

    def test_skips_migrate_and_makemigrations(self):
        self.assertFalse(should_warm_up_embeddings(["manage.py", "migrate"]))
        self.assertFalse(should_warm_up_embeddings(["manage.py", "makemigrations"]))

    def test_skips_shell_and_admin_commands(self):
        self.assertFalse(should_warm_up_embeddings(["manage.py", "shell"]))
        self.assertFalse(should_warm_up_embeddings(["manage.py", "collectstatic"]))
        self.assertFalse(should_warm_up_embeddings(["manage.py", "createsuperuser"]))

    def test_skips_eval_and_benchmark_tooling(self):
        self.assertFalse(should_warm_up_embeddings(["manage.py", "run_chat_eval"]))
        self.assertFalse(should_warm_up_embeddings(["manage.py", "benchmark_nlu_models"]))

    def test_warms_up_for_runserver(self):
        self.assertTrue(should_warm_up_embeddings(["manage.py", "runserver"]))

    def test_warms_up_when_no_subcommand(self):
        self.assertTrue(should_warm_up_embeddings(["gunicorn", "config.wsgi:application"]))
        self.assertTrue(should_warm_up_embeddings(["manage.py"]))


class WarmUpEmbeddingServiceTests(SimpleTestCase):
    def setUp(self):
        reset_embedding_service()
        self.addCleanup(reset_embedding_service)

    def test_noop_for_openai_provider(self):
        with patch(
            "apps.knowledge.embeddings.factory.get_embedding_service"
        ) as mock_get_service:
            attempted = warm_up_embedding_service()
        self.assertFalse(attempted)
        mock_get_service.assert_not_called()

    @override_settings(EMBEDDING_PROVIDER="local")
    def test_noop_even_if_env_still_says_local(self):
        """A leftover EMBEDDING_PROVIDER=local must not try to load BGE/torch
        at gunicorn start — that was the AWS deploy break."""
        with patch(
            "apps.knowledge.embeddings.factory.get_embedding_service"
        ) as mock_get_service:
            attempted = warm_up_embedding_service()
        self.assertFalse(attempted)
        mock_get_service.assert_not_called()
