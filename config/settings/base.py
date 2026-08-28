"""
Synapse Django settings — base configuration.

Environment-specific settings live in:
  - config.settings.development
  - config.settings.production
"""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, []),
)

# Read .env from project root (if present)
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY")
DEBUG = env.bool("DEBUG", default=False)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[])

# ─── Application definition ─────────────────────────────────────────────────

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "corsheaders",
]

LOCAL_APPS = [
    "core.apps.CoreConfig",
    "apps.accounts.apps.AccountsConfig",
    "apps.api.apps.ApiConfig",
    "apps.clinics.apps.ClinicsConfig",
    "apps.doctors.apps.DoctorsConfig",
    "apps.patients.apps.PatientsConfig",
    "apps.appointments.apps.AppointmentsConfig",
    "apps.specialties.apps.SpecialtiesConfig",
    "apps.services.apps.ServicesConfig",
    "apps.insurance.apps.InsuranceConfig",
    "apps.knowledge.apps.KnowledgeConfig",
    "apps.chatbot.apps.ChatbotConfig",
    "apps.ai.apps.AiConfig",
    "apps.widget.apps.WidgetConfig",
    "apps.notifications.apps.NotificationsConfig",
    "apps.billing.apps.BillingConfig",
    "apps.importer.apps.ImporterConfig",
    "apps.verification.apps.VerificationConfig",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# ─── Database (PostgreSQL + pgvector) ───────────────────────────────────────

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB", default="synapse"),
        "USER": env("POSTGRES_USER", default="synapse"),
        "PASSWORD": env("POSTGRES_PASSWORD", default=""),
        "HOST": env("POSTGRES_HOST", default="localhost"),
        "PORT": env("POSTGRES_PORT", default="5432"),
        "CONN_MAX_AGE": env.int("CONN_MAX_AGE", default=60),
        # Verifies a pooled connection is still alive before reuse instead
        # of handing a worker a dead one — matters once this runs as
        # multiple long-lived AWS workers behind RDS, where a failover or
        # idle-connection reap would otherwise surface as a random request
        # failure instead of a transparent reconnect.
        "CONN_HEALTH_CHECKS": True,
        "OPTIONS": {
            "connect_timeout": 10,
        },
    }
}

# ─── Password validation ────────────────────────────────────────────────────

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ─── Internationalization ───────────────────────────────────────────────────

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# ─── Static & media files ───────────────────────────────────────────────────

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# ─── Defaults ───────────────────────────────────────────────────────────────

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# UUID primary keys are defined explicitly on domain models (Phase 3).
# Staff identity uses custom User (accounts.User); patients never use it.

AUTH_USER_MODEL = "accounts.User"

# ─── CORS (widget embed — tighten in production) ────────────────────────────

from corsheaders.defaults import default_headers

CORS_ALLOW_CREDENTIALS = True
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[])
CORS_ALLOW_HEADERS = list(default_headers) + ["x-tenant-id", "x-synapse-visitor-id"]

# ─── JWT — dual auth (staff portal vs patient widget) ─────────────────────────

JWT_SECRET_KEY = env("JWT_SECRET_KEY", default=SECRET_KEY)
JWT_ALGORITHM = "HS256"

# Staff / admin portal (email + password)
JWT_STAFF_ACCESS_TOKEN_EXPIRE_MINUTES = env.int(
    "JWT_STAFF_ACCESS_TOKEN_EXPIRE_MINUTES",
    default=env.int("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", default=480),
)
JWT_STAFF_REFRESH_TOKEN_EXPIRE_DAYS = env.int(
    "JWT_STAFF_REFRESH_TOKEN_EXPIRE_DAYS",
    default=14,
)

# Patient widget (phone OTP) — short-lived, no password account
JWT_PATIENT_ACCESS_TOKEN_EXPIRE_MINUTES = env.int(
    "JWT_PATIENT_ACCESS_TOKEN_EXPIRE_MINUTES",
    default=120,
)

# OTP delivery (Twilio in production; console log in DEBUG when unset)
TWILIO_ACCOUNT_SID = env("TWILIO_ACCOUNT_SID", default="")
TWILIO_AUTH_TOKEN = env("TWILIO_AUTH_TOKEN", default="")
TWILIO_FROM_NUMBER = env("TWILIO_FROM_NUMBER", default="")
OTP_CODE_LENGTH = env.int("OTP_CODE_LENGTH", default=6)
OTP_EXPIRE_MINUTES = env.int("OTP_EXPIRE_MINUTES", default=10)

# apps.verification — provider-agnostic account/sensitive-action verification.
# Separate from the OTP_*/TWILIO_* block above, which belongs to the existing
# patient-booking OTP flow (apps.chatbot.services.otp_service) and is
# untouched by this app. TWILIO_API_KEY/SECRET (not the main auth token)
# are Twilio's recommended production credential shape for a Verify Service.
OTP_PROVIDER = env("OTP_PROVIDER", default="mock")
TWILIO_API_KEY = env("TWILIO_API_KEY", default="")
TWILIO_API_SECRET = env("TWILIO_API_SECRET", default="")
TWILIO_VERIFY_SERVICE_SID = env("TWILIO_VERIFY_SERVICE_SID", default="")
VERIFICATION_CODE_LENGTH = env.int("VERIFICATION_CODE_LENGTH", default=6)
VERIFICATION_CODE_TTL_SECONDS = env.int("VERIFICATION_CODE_TTL_SECONDS", default=600)
VERIFICATION_RESEND_COOLDOWN_SECONDS = env.int(
    "VERIFICATION_RESEND_COOLDOWN_SECONDS", default=30
)
VERIFICATION_MAX_CHECK_ATTEMPTS = env.int("VERIFICATION_MAX_CHECK_ATTEMPTS", default=5)

# Paddle Billing — SaaS subscriptions (clinic owner → plan). Sandbox by
# default so local/dev/test never accidentally talk to live Paddle.
PADDLE_ENVIRONMENT = env("PADDLE_ENVIRONMENT", default="sandbox")  # "sandbox" | "live"
PADDLE_API_KEY = env("PADDLE_API_KEY", default="")
PADDLE_WEBHOOK_SECRET = env("PADDLE_WEBHOOK_SECRET", default="")
# How long a past_due subscription keeps full access before
# Subscription.access_status reports SUSPENDED (see apps/billing/models.py).
BILLING_GRACE_PERIOD_DAYS = env.int("BILLING_GRACE_PERIOD_DAYS", default=7)

# Frontend / email
FRONTEND_URL = env("FRONTEND_URL", default="http://localhost:3000")
# onboarding@resend.dev is Resend's shared test sender — works with no
# domain verification. Swap to a verified domain address once one exists;
# this is the only place that needs to change.
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="Synapse <onboarding@resend.dev>")
RESEND_API_KEY = env("RESEND_API_KEY", default="")
EMAIL_HOST = env("EMAIL_HOST", default="")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
# Internal recipient for platform notifications (new demo requests/
# applications). Optional — sending is skipped with a log line when unset.
PLATFORM_NOTIFICATION_EMAIL = env("PLATFORM_NOTIFICATION_EMAIL", default="")

# ─── OpenAI (embeddings + chat) ───────────────────────────────────────────────

OPENAI_API_KEY = env("OPENAI_API_KEY", default="")
# Legacy aliases — prefer EMBEDDING_MODEL / EMBEDDING_DIMENSIONS for both providers
OPENAI_EMBEDDING_MODEL = env(
    "OPENAI_EMBEDDING_MODEL",
    default="text-embedding-3-small",
)
OPENAI_EMBEDDING_DIMENSIONS = env.int("OPENAI_EMBEDDING_DIMENSIONS", default=1536)

# ─── Knowledge ingestion ──────────────────────────────────────────────────────

KNOWLEDGE_CHUNK_SIZE = env.int("KNOWLEDGE_CHUNK_SIZE", default=1000)
KNOWLEDGE_CHUNK_OVERLAP = env.int("KNOWLEDGE_CHUNK_OVERLAP", default=150)
KNOWLEDGE_CHUNK_MIN_CHARS = env.int("KNOWLEDGE_CHUNK_MIN_CHARS", default=40)
# Phase 3: embed + index on upload (set False to chunk-only for debugging)
KNOWLEDGE_RUN_EMBEDDINGS = env.bool("KNOWLEDGE_RUN_EMBEDDINGS", default=True)

# Embedding provider — OpenAI only (ARCHITECTURE.md §9).
# Local SentenceTransformer / BGE was removed; do not set EMBEDDING_PROVIDER=local.
EMBEDDING_PROVIDER = env("EMBEDDING_PROVIDER", default="openai")
EMBEDDING_MODEL = env("EMBEDDING_MODEL", default="text-embedding-3-small")
EMBEDDING_DIMENSIONS = env.int("EMBEDDING_DIMENSIONS", default=1536)

# ─── Intent & Entity NLU (chatbot routing) ────────────────────────────────────
# OpenAI primary (nano) for reliability; Gemini secondary when key is valid AIza…
NLU_PROVIDER = env("NLU_PROVIDER", default="openai")
NLU_MODEL = env("NLU_MODEL", default="gpt-4.1-nano")
GOOGLE_API_KEY = env("GOOGLE_API_KEY", default="")
NLU_API_TIMEOUT_SECONDS = env.float("NLU_API_TIMEOUT_SECONDS", default=5.0)
# Wall-clock ceiling for the whole provider chain (primary → mini fallback →
# secondary). Per-provider timeouts still apply per attempt; this stops
# sequential attempts from stacking them. Raised from 3.5/5.0 after measuring
# real primary-provider latency directly against production traffic patterns:
# successful calls routinely land in the 1.4-3.1s range with real, wide
# variance (cloud LLM latency, not a code bug), and the old 3.5s per-provider
# cap left too little margin — occasional legitimate-but-slow calls were
# getting cut off and falling through to the generic clarification fallback,
# most visibly on a session's first message. See ROADMAP.md "NLU cold-first-
# message failures" for the measured evidence.
NLU_TOTAL_BUDGET_SECONDS = env.float("NLU_TOTAL_BUDGET_SECONDS", default=7.0)
NLU_CONFIDENCE_THRESHOLD = env.float("NLU_CONFIDENCE_THRESHOLD", default=0.75)
CHAT_CONFIDENCE_HIGH = env.float("CHAT_CONFIDENCE_HIGH", default=0.90)
CHAT_CONFIDENCE_MID = env.float("CHAT_CONFIDENCE_MID", default=0.70)
CHAT_CONFIDENCE_LOW = env.float("CHAT_CONFIDENCE_LOW", default=0.45)

NLU_ENABLE_RULES = env.bool("NLU_ENABLE_RULES", default=True)
NLU_RULES_BEFORE_LLM = env.bool("NLU_RULES_BEFORE_LLM", default=False)
# Secondary provider after primary failure (circuit-breaker aware)
NLU_SECONDARY_PROVIDER = env("NLU_SECONDARY_PROVIDER", default="gemini")
NLU_FALLBACK_OPENAI = env.bool("NLU_FALLBACK_OPENAI", default=True)
NLU_FALLBACK_ON_TIMEOUT = env.bool("NLU_FALLBACK_ON_TIMEOUT", default=True)
NLU_FALLBACK_MODEL = env("NLU_FALLBACK_MODEL", default="gpt-4.1-mini")

# ─── Chat / RAG response generation (separate from NLU) ───────────────────────
CHAT_RESPONSE_PROVIDER = env("CHAT_RESPONSE_PROVIDER", default="openai")
CHAT_RESPONSE_MODEL = env("CHAT_RESPONSE_MODEL", default="gpt-4.1-mini")
CHAT_RESPONSE_FALLBACK_MODELS = env(
    "CHAT_RESPONSE_FALLBACK_MODELS",
    default="",
)
CHAT_RESPONSE_SECONDARY_PROVIDER = env(
    "CHAT_RESPONSE_SECONDARY_PROVIDER", default="gemini"
)
CHAT_PREMIUM_MODEL = env("CHAT_PREMIUM_MODEL", default="gpt-4o-mini")
# Hard wall-clock for ALL response-LLM attempts combined
CHAT_RESPONSE_TIMEOUT_SECONDS = env.float("CHAT_RESPONSE_TIMEOUT_SECONDS", default=8.0)
CHAT_VECTOR_MIN_SCORE = env.float("CHAT_VECTOR_MIN_SCORE", default=0.25)
# End-to-end server budget — skip Large LLM when remaining time is too low
CHAT_REQUEST_BUDGET_SECONDS = env.float("CHAT_REQUEST_BUDGET_SECONDS", default=20.0)
CHAT_RESPONSE_MIN_REMAINING_SECONDS = env.float(
    "CHAT_RESPONSE_MIN_REMAINING_SECONDS", default=2.0
)
# Circuit breaker for failing LLM providers
LLM_CIRCUIT_FAILURE_THRESHOLD = env.int("LLM_CIRCUIT_FAILURE_THRESHOLD", default=5)
LLM_CIRCUIT_COOLDOWN_SECONDS = env.float("LLM_CIRCUIT_COOLDOWN_SECONDS", default=600.0)
# Cache TTL for stable clinic SQL facts (hours/doctors/insurance/services)
CLINIC_FACT_CACHE_TTL_SECONDS = env.int("CLINIC_FACT_CACHE_TTL_SECONDS", default=600)

# Structured AI pipeline debugger (terminal + optional logs/chat/*.json)
# Development settings default this True; production stays False. Use this
# — not Swagger — to inspect Small LLM prompts, planner scores, SQL rows,
# vector chunks, Large LLM prompts, and final replies.
DEBUG_CHAT_PIPELINE = env.bool("DEBUG_CHAT_PIPELINE", default=False)
DEBUG_CHAT_PIPELINE_SAVE_JSON = env.bool("DEBUG_CHAT_PIPELINE_SAVE_JSON", default=True)
# Token streaming for RAG replies (designed; off until budgets are proven)
CHAT_RESPONSE_STREAMING = env.bool("CHAT_RESPONSE_STREAMING", default=False)

# ─── Spreadsheet data import (onboarding bulk-import pipeline) ────────────────
IMPORTER_MAX_FILE_SIZE_BYTES = env.int("IMPORTER_MAX_FILE_SIZE_BYTES", default=5 * 1024 * 1024)
IMPORTER_MAX_ROWS = env.int("IMPORTER_MAX_ROWS", default=2000)
IMPORTER_MAX_COLUMNS = env.int("IMPORTER_MAX_COLUMNS", default=60)
IMPORTER_LLM_TIMEOUT_SECONDS = env.float("IMPORTER_LLM_TIMEOUT_SECONDS", default=8.0)
IMPORTER_LLM_MODEL = env("IMPORTER_LLM_MODEL", default="gpt-4.1-mini")
# Below this, an extracted field is flagged "needs review" instead of
# being trusted for auto-commit.
IMPORTER_CONFIDENCE_THRESHOLD = env.float("IMPORTER_CONFIDENCE_THRESHOLD", default=0.7)

