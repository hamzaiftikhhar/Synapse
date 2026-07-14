"""Development settings — local Postgres, debug tools, relaxed hosts."""

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
