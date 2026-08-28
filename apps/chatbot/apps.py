from __future__ import annotations

import sys

from django.apps import AppConfig

# Same rationale as apps.knowledge.apps.should_warm_up_embeddings: warming a
# live network connection to the NLU provider at the start of `manage.py
# test` (or migrate/shell/etc.) would tax every one of them for zero
# benefit — none of these serve a real chat request. Anything not in this
# list (runserver, or no subcommand at all — e.g. gunicorn importing
# config.wsgi:application) is treated as a real serving process and gets
# the warm-up. `run_chat_eval` is explicitly offline/no-live-LLM-calls
# (see CLAUDE.md), so it's skipped for the same reason as the embeddings
# warm-up.
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
        "run_chat_eval",
        "benchmark_nlu_models",
        "export_openapi_schema",
    }
)


def should_warm_up_nlu(argv: list[str]) -> bool:
    """True unless argv names a management command that doesn't serve requests."""
    command = argv[1] if len(argv) > 1 else ""
    return command not in _SKIP_WARMUP_COMMANDS


class ChatbotConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.chatbot"
    label = "chatbot"
    verbose_name = "Chatbot"

    def ready(self) -> None:
        if not should_warm_up_nlu(sys.argv):
            return
        from apps.chatbot.nlu.factory import warm_up_nlu_provider

        warm_up_nlu_provider()
