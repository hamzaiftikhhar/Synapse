from __future__ import annotations

import sys

from django.apps import AppConfig

# Management commands that never serve a real request — warming up a
# ~400MB local embedding model at the start of `manage.py test` (or
# migrate/shell/etc.) would tax every one of them for zero benefit. Anything
# not in this list (runserver, or no subcommand at all — e.g. gunicorn
# importing config.wsgi:application) is treated as a real serving process
# and gets the warm-up.
_SKIP_WARMUP_COMMANDS = frozenset(
    {
        "test",
        "makemigrations",
        "migrate",
        "collectstatic",
        "shell",
        "shell_plus",
        "dbshell",
        "check",
        "createsuperuser",
        "changepassword",
        "dumpdata",
        "loaddata",
        "showmigrations",
        "sqlmigrate",
        "diffsettings",
        "inspectdb",
        "flush",
        "startapp",
        "startproject",
        "compilemessages",
        "makemessages",
        "sendtestemail",
        "clearsessions",
        # Repo-specific measurement/dev tools — repeated-run, fast-iteration,
        # and (for run_chat_eval specifically, confirmed by running it) never
        # touch real vector search, so warm-up buys them nothing.
        "run_chat_eval",
        "benchmark_nlu_models",
        "export_openapi_schema",
    }
)


def should_warm_up_embeddings(argv: list[str]) -> bool:
    """True unless argv names a management command that doesn't serve requests."""
    command = argv[1] if len(argv) > 1 else ""
    return command not in _SKIP_WARMUP_COMMANDS


class KnowledgeConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.knowledge"
    label = "knowledge"
    verbose_name = "Knowledge"

    def ready(self) -> None:
        if not should_warm_up_embeddings(sys.argv):
            return
        from apps.knowledge.embeddings.factory import warm_up_embedding_service

        warm_up_embedding_service()
