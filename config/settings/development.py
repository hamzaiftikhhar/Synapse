"""Development settings — local Postgres, debug tools, relaxed hosts."""

import copy

from django.utils.log import DEFAULT_LOGGING

from .base import *  # noqa: F401, F403

DEBUG = True

ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1", "[::1]"])  # noqa: F405

# Prefer an explicit local secret if none was provided via .env
if SECRET_KEY == "change-me-in-production":  # noqa: F405
    SECRET_KEY = "django-insecure-dev-only-do-not-use-in-production"

# Local CORS for widget development
CORS_ALLOWED_ORIGINS = env.list(  # noqa: F405
    "CORS_ALLOWED_ORIGINS",
    default=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
)

# Simpler static files in development (no manifest hashing required)
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Chat traces print to the runserver console unless .env sets this false.
# `pipeline_debug_enabled()` still forces them off under `manage.py test`
# / `run_chat_eval` so those commands stay quiet.
DEBUG_CHAT_PIPELINE = env.bool("DEBUG_CHAT_PIPELINE", default=True)  # noqa: F405

# App `logger.info` lines (chat_route, EMAIL provider=..., NLU, etc.) do not
# reach the terminal under Django's default config — only `django` /
# `django.server` do. Keep Django's defaults and add `apps.*` at INFO.
LOGGING = copy.deepcopy(DEFAULT_LOGGING)
LOGGING["loggers"]["apps"] = {
    "handlers": ["console"],
    "level": "INFO",
    "propagate": False,
}
