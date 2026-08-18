"""Phase 9B: the local embedding model must load at process startup, not on
the first real vector search. See apps/knowledge/embeddings/local.py's
_get_sentence_transformer (lazy, ~20s cold on this machine — see the phase
report) and apps/knowledge/apps.py::KnowledgeConfig.ready().
"""

from __future__ import annotations

from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from apps.knowledge.apps import should_warm_up_embeddings
from apps.knowledge.embeddings import local as local_module
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
        # Confirmed by actually running it: run_chat_eval never touches
        # real vector search (routing-lane simulation only), so warming up
        # for it would only slow down a command developers run repeatedly.
        self.assertFalse(should_warm_up_embeddings(["manage.py", "run_chat_eval"]))
        self.assertFalse(should_warm_up_embeddings(["manage.py", "benchmark_nlu_models"]))

    def test_warms_up_for_runserver(self):
        self.assertTrue(should_warm_up_embeddings(["manage.py", "runserver"]))

    def test_warms_up_when_no_subcommand(self):
        # gunicorn/uwsgi import config.wsgi:application directly — argv is
        # the server binary's own, not a manage.py subcommand.
        self.assertTrue(should_warm_up_embeddings(["gunicorn", "config.wsgi:application"]))
        self.assertTrue(should_warm_up_embeddings(["manage.py"]))


@override_settings(
    EMBEDDING_PROVIDER="local",
    EMBEDDING_MODEL="test-warmup-model",
    EMBEDDING_DIMENSIONS=768,
)
class WarmUpEmbeddingServiceTests(SimpleTestCase):
    def setUp(self):
        reset_embedding_service()
        local_module._model_cache.clear()
        self.addCleanup(reset_embedding_service)
        self.addCleanup(local_module._model_cache.clear)

    @override_settings(EMBEDDING_PROVIDER="openai")
    def test_noop_for_openai_provider(self):
        with patch(
            "apps.knowledge.embeddings.factory.get_embedding_service"
        ) as mock_get_service:
            attempted = warm_up_embedding_service()
        self.assertFalse(attempted)
        mock_get_service.assert_not_called()

    def test_failure_is_swallowed_not_raised(self):
        with patch(
            "apps.knowledge.embeddings.factory.get_embedding_service",
            side_effect=RuntimeError("model download failed"),
        ):
            attempted = warm_up_embedding_service()  # must not raise
        self.assertTrue(attempted)

    def test_model_loads_before_first_request_not_merely_lazily_earlier(self):
        """The load must happen during warm-up itself, and a subsequent
        "real" query must reuse it rather than triggering a second load —
        proving genuine pre-loading, not just an earlier call to the same
        lazy path."""
        import sys
        import types

        import numpy as np

        fake_vector = np.array([0.1] * 768)

        class _FakeSentenceTransformer:
            init_calls = 0

            def __init__(self, model_name):
                type(self).init_calls += 1
                self.model_name = model_name

            def encode(self, inputs, **kwargs):
                return [fake_vector for _ in inputs]

        # local.py does `from sentence_transformers import SentenceTransformer`
        # inside the function body. Patching the real module's attribute
        # would first have to *import* the real (heavy, ~10s-to-import on
        # this machine) package just to locate it — defeating the point of
        # faking it out. Install a stand-in module in sys.modules instead,
        # so the local import resolves to the fake without ever touching
        # the real package.
        fake_module = types.ModuleType("sentence_transformers")
        fake_module.SentenceTransformer = _FakeSentenceTransformer
        with patch.dict(sys.modules, {"sentence_transformers": fake_module}):
            attempted = warm_up_embedding_service()
            self.assertTrue(attempted)
            self.assertEqual(
                _FakeSentenceTransformer.init_calls,
                1,
                "warm-up must load the model immediately, not defer it",
            )

            # Simulate the first real user request arriving after warm-up.
            from apps.knowledge.embeddings.factory import get_embedding_service

            get_embedding_service().embed_query("do you have hydrafacial")

            self.assertEqual(
                _FakeSentenceTransformer.init_calls,
                1,
                "the first real request must reuse the warmed-up model, "
                "not load it a second time",
            )
