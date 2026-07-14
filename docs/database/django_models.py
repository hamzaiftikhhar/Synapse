"""
Synapse — Phase 1 Reference Django Models (v1.1)

NOT wired into a Django project yet.
Phase 3 will split these into apps and run migrations.

Dependencies:
    pip install django>=5.0 pgvector psycopg[binary]

Usage in Phase 3:
    1. Create Django apps: clinics, medical, patients, knowledge, chat, analytics
    2. Move models into appropriate apps
    3. Add SoftDeleteModel mixin to a shared module
    4. Run makemigrations && migrate
"""

import uuid

from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Q
from pgvector.django import HnswIndex, VectorField


# ─── Abstract Base ─────────────────────────────────────────────────────────────


class UUIDModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class SoftDeleteModel(models.Model):
    """Soft delete for catalog entities referenced by appointments / history."""

    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True


class TenantModel(UUIDModel):
    """All tenant-scoped models inherit clinic_id for multi-tenancy."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="%(class)ss",
    )

    class Meta:
        abstract = True


# ─── Clinic Management ─────────────────────────────────────────────────────────


class ClinicStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    SUSPENDED = "suspended", "Suspended"
    ONBOARDING = "onboarding", "Onboarding"


class Clinic(UUIDModel, TimestampedModel):
    slug = models.SlugField(max_length=64, unique=True)
    name = models.CharField(max_length=255)
    email = models.EmailField()
    phone = models.CharField(max_length=20, blank=True, default="")
    address = models.JSONField(default=dict, blank=True)
    timezone = models.CharField(max_length=50, default="America/New_York")
    status = models.CharField(
        max_length=20,
        choices=ClinicStatus.choices,
        default=ClinicStatus.ACTIVE,
    )

    class Meta:
        db_table = "clinics"
        indexes = [
            models.Index(fields=["status"]),
        ]

    def __str__(self) -> str:
        return self.name


class WidgetSettings(UUIDModel, TimestampedModel):
    clinic = models.OneToOneField(
        Clinic,
        on_delete=models.CASCADE,
        related_name="widget_settings",
    )
    # Single JSON: {widget, ai, booking, feature_flags}
    configuration = models.JSONField(default=dict)

    class Meta:
        db_table = "widget_settings"
        verbose_name_plural = "widget settings"

    def __str__(self) -> str:
        return f"Widget settings for {self.clinic.name}"


class ClinicBusinessHours(TenantModel, TimestampedModel):
    day_of_week = models.PositiveSmallIntegerField()  # 0=Monday
    open_time = models.TimeField(null=True, blank=True)
    close_time = models.TimeField(null=True, blank=True)
    is_closed = models.BooleanField(default=False)

    class Meta:
        db_table = "clinic_business_hours"
        verbose_name_plural = "clinic business hours"
        constraints = [
            models.UniqueConstraint(
                fields=["clinic", "day_of_week"],
                name="uq_clinic_business_hours_day",
            ),
            models.CheckConstraint(
                check=Q(day_of_week__gte=0) & Q(day_of_week__lte=6),
                name="chk_clinic_hours_day_of_week",
            ),
        ]
        indexes = [
            models.Index(fields=["clinic"]),
        ]


# ─── Medical Information ───────────────────────────────────────────────────────


class Specialty(TenantModel, TimestampedModel, SoftDeleteModel):
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100)
    description = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "specialties"
        verbose_name_plural = "specialties"
        constraints = [
            models.UniqueConstraint(
                fields=["clinic", "slug"],
                name="uq_specialty_clinic_slug",
            ),
        ]
        indexes = [
            models.Index(fields=["clinic", "is_active"]),
        ]

    def __str__(self) -> str:
        return self.name


class Doctor(TenantModel, TimestampedModel, SoftDeleteModel):
    full_name = models.CharField(max_length=255)
    title = models.CharField(max_length=50, blank=True, default="")
    bio = models.TextField(blank=True, default="")
    photo_url = models.URLField(max_length=500, blank=True, default="")
    languages = ArrayField(
        models.CharField(max_length=10),
        default=lambda: ["en"],
    )
    is_active = models.BooleanField(default=True)
    is_accepting_patients = models.BooleanField(default=True)
    metadata = models.JSONField(default=dict, blank=True)
    specialties = models.ManyToManyField(
        Specialty,
        through="DoctorSpecialty",
        related_name="doctors",
    )
    services = models.ManyToManyField(
        "Service",
        through="DoctorService",
        related_name="doctors",
    )
    insurance_plans = models.ManyToManyField(
        "InsurancePlan",
        through="DoctorInsurance",
        related_name="doctors",
    )

    class Meta:
        db_table = "doctors"
        indexes = [
            models.Index(fields=["clinic", "is_active"]),
        ]

    def __str__(self) -> str:
        return self.full_name


class DoctorSpecialty(models.Model):
    doctor = models.ForeignKey(
        Doctor,
        on_delete=models.CASCADE,
        related_name="doctor_specialties",
    )
    specialty = models.ForeignKey(
        Specialty,
        on_delete=models.CASCADE,
        related_name="doctor_specialties",
    )
    clinic = models.ForeignKey(
        Clinic,
        on_delete=models.CASCADE,
        related_name="doctor_specialties",
    )

    class Meta:
        db_table = "doctor_specialties"
        constraints = [
            models.UniqueConstraint(
                fields=["doctor", "specialty"],
                name="uq_doctor_specialty",
            ),
        ]
        indexes = [
            models.Index(fields=["clinic", "specialty"]),
            models.Index(fields=["clinic", "doctor"]),
        ]


class Service(TenantModel, TimestampedModel, SoftDeleteModel):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    duration_min = models.PositiveSmallIntegerField(default=30)
    price_cents = models.PositiveIntegerField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "services"
        indexes = [
            models.Index(fields=["clinic", "is_active"]),
        ]

    def __str__(self) -> str:
        return self.name


class DoctorService(models.Model):
    doctor = models.ForeignKey(
        Doctor,
        on_delete=models.CASCADE,
        related_name="doctor_services",
    )
    service = models.ForeignKey(
        Service,
        on_delete=models.CASCADE,
        related_name="doctor_services",
    )
    clinic = models.ForeignKey(
        Clinic,
        on_delete=models.CASCADE,
        related_name="doctor_services",
    )

    class Meta:
        db_table = "doctor_services"
        constraints = [
            models.UniqueConstraint(
                fields=["doctor", "service"],
                name="uq_doctor_service",
            ),
        ]
        indexes = [
            models.Index(fields=["clinic", "service"]),
            models.Index(fields=["clinic", "doctor"]),
        ]


class InsurancePlan(TenantModel, TimestampedModel, SoftDeleteModel):
    provider_name = models.CharField(max_length=255)
    plan_name = models.CharField(max_length=255, blank=True, default="")
    plan_type = models.CharField(max_length=50, blank=True, default="")
    is_accepted = models.BooleanField(default=True)
    notes = models.TextField(blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "insurance_plans"
        indexes = [
            models.Index(fields=["clinic", "is_accepted"]),
        ]

    def __str__(self) -> str:
        parts = [self.provider_name]
        if self.plan_name:
            parts.append(self.plan_name)
        return " — ".join(parts)


class DoctorInsurance(models.Model):
    doctor = models.ForeignKey(
        Doctor,
        on_delete=models.CASCADE,
        related_name="doctor_insurances",
    )
    insurance_plan = models.ForeignKey(
        InsurancePlan,
        on_delete=models.CASCADE,
        related_name="doctor_insurances",
    )
    clinic = models.ForeignKey(
        Clinic,
        on_delete=models.CASCADE,
        related_name="doctor_insurances",
    )

    class Meta:
        db_table = "doctor_insurance"
        constraints = [
            models.UniqueConstraint(
                fields=["doctor", "insurance_plan"],
                name="uq_doctor_insurance",
            ),
        ]
        indexes = [
            models.Index(fields=["clinic", "insurance_plan"]),
            models.Index(fields=["clinic", "doctor"]),
        ]


class DoctorSchedule(TenantModel, TimestampedModel):
    doctor = models.ForeignKey(
        Doctor,
        on_delete=models.CASCADE,
        related_name="schedules",
    )
    day_of_week = models.PositiveSmallIntegerField()  # 0=Monday
    start_time = models.TimeField()
    end_time = models.TimeField()
    slot_duration_min = models.PositiveSmallIntegerField(default=30)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "doctor_schedules"
        indexes = [
            models.Index(fields=["clinic", "doctor", "day_of_week"]),
            models.Index(fields=["clinic", "doctor", "is_active"]),
        ]
        constraints = [
            models.CheckConstraint(
                check=Q(day_of_week__gte=0) & Q(day_of_week__lte=6),
                name="chk_schedule_day_of_week",
            ),
        ]


class DoctorLeave(TenantModel, TimestampedModel):
    doctor = models.ForeignKey(
        Doctor,
        on_delete=models.CASCADE,
        related_name="leaves",
    )
    start_at = models.DateTimeField()
    end_at = models.DateTimeField()
    reason = models.CharField(max_length=255, blank=True, default="")
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "doctor_leaves"
        indexes = [
            models.Index(fields=["clinic", "doctor", "start_at", "end_at"]),
            models.Index(fields=["clinic", "doctor", "is_active"]),
        ]
        constraints = [
            models.CheckConstraint(
                check=Q(end_at__gt=models.F("start_at")),
                name="chk_leave_end_after_start",
            ),
        ]


# ─── Patient System ────────────────────────────────────────────────────────────


class Patient(TenantModel, TimestampedModel):
    phone = models.CharField(max_length=20)  # required for OTP
    email = models.EmailField(blank=True, default="")
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    date_of_birth = models.DateField(null=True, blank=True)
    preferred_language = models.CharField(max_length=10, default="en")
    is_verified = models.BooleanField(default=False)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "patients"
        constraints = [
            models.UniqueConstraint(
                fields=["clinic", "phone"],
                name="uq_patient_clinic_phone",
            ),
            models.UniqueConstraint(
                fields=["clinic", "email"],
                condition=~Q(email=""),
                name="uq_patient_clinic_email",
            ),
        ]
        indexes = [
            models.Index(fields=["clinic", "first_name"]),
            models.Index(fields=["clinic", "last_name"]),
        ]

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    def __str__(self) -> str:
        return self.full_name or self.phone


class AppointmentStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    CONFIRMED = "confirmed", "Confirmed"
    CANCELLED = "cancelled", "Cancelled"
    COMPLETED = "completed", "Completed"
    NO_SHOW = "no_show", "No Show"
    RESCHEDULED = "rescheduled", "Rescheduled"


class AppointmentSource(models.TextChoices):
    CHATBOT = "chatbot", "Chatbot"
    ADMIN = "admin", "Admin"
    PHONE = "phone", "Phone"
    WALK_IN = "walk_in", "Walk-in"
    IMPORT = "import", "Import"


class Appointment(TenantModel, TimestampedModel):
    doctor = models.ForeignKey(
        Doctor,
        on_delete=models.PROTECT,
        related_name="appointments",
    )
    patient = models.ForeignKey(
        Patient,
        on_delete=models.PROTECT,
        related_name="appointments",
    )
    service = models.ForeignKey(
        Service,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="appointments",
    )
    insurance_plan = models.ForeignKey(
        InsurancePlan,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="appointments",
    )
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    status = models.CharField(
        max_length=20,
        choices=AppointmentStatus.choices,
        default=AppointmentStatus.PENDING,
    )
    confirmation_code = models.CharField(max_length=10, unique=True)
    notes = models.TextField(blank=True, default="")
    source = models.CharField(
        max_length=20,
        choices=AppointmentSource.choices,
        default=AppointmentSource.CHATBOT,
    )

    class Meta:
        db_table = "appointments"
        indexes = [
            models.Index(fields=["clinic", "doctor", "start_time"]),
            models.Index(fields=["clinic", "patient"]),
            models.Index(fields=["clinic", "status", "start_time"]),
        ]
        constraints = [
            models.CheckConstraint(
                check=Q(end_time__gt=models.F("start_time")),
                name="chk_appointment_end_after_start",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.patient} with {self.doctor} at {self.start_time}"


# ─── AI Knowledge ──────────────────────────────────────────────────────────────


class DocumentStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    PROCESSING = "processing", "Processing"
    INDEXED = "indexed", "Indexed"
    FAILED = "failed", "Failed"


class Document(TenantModel, TimestampedModel, SoftDeleteModel):
    title = models.CharField(max_length=255)
    file_name = models.CharField(max_length=255)
    file_type = models.CharField(max_length=50)
    storage_path = models.CharField(max_length=500)
    file_size_bytes = models.PositiveIntegerField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=DocumentStatus.choices,
        default=DocumentStatus.PENDING,
    )
    chunk_count = models.PositiveIntegerField(default=0)
    # Nullable until clinic admin users exist (Phase 4/8)
    uploaded_by = models.UUIDField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True, default="")

    class Meta:
        db_table = "documents"
        indexes = [
            models.Index(fields=["clinic", "status"]),
            models.Index(fields=["clinic", "created_at"]),
        ]

    def __str__(self) -> str:
        return self.title


class KnowledgeChunk(TenantModel):
    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name="chunks",
    )
    chunk_number = models.PositiveIntegerField()
    page_number = models.PositiveIntegerField(null=True, blank=True)
    content = models.TextField()
    token_count = models.PositiveIntegerField(null=True, blank=True)
    embedding = VectorField(dimensions=1536, null=True, blank=True)
    embedding_model = models.CharField(
        max_length=50,
        default="text-embedding-3-small",
    )
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "knowledge_chunks"
        constraints = [
            models.UniqueConstraint(
                fields=["document", "chunk_number"],
                name="uq_chunk_document_number",
            ),
        ]
        indexes = [
            models.Index(fields=["clinic", "document"]),
            models.Index(fields=["document", "page_number"]),
            HnswIndex(
                name="idx_knowledge_chunks_embedding_hnsw",
                fields=["embedding"],
                opclasses=["vector_cosine_ops"],
                m=16,
                ef_construction=64,
            ),
            # Full-text index via RunSQL in migration:
            # CREATE INDEX ... USING gin (to_tsvector('english', content))
        ]

    def __str__(self) -> str:
        return f"Chunk {self.chunk_number} of {self.document.title}"


# ─── Chat System ───────────────────────────────────────────────────────────────


class ChatSessionStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    CLOSED = "closed", "Closed"
    ESCALATED = "escalated", "Escalated"


class ChatSession(TenantModel):
    patient = models.ForeignKey(
        Patient,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="chat_sessions",
    )
    session_token = models.CharField(max_length=64, unique=True)
    ip_hash = models.CharField(max_length=64, blank=True, default="")
    user_agent = models.CharField(max_length=500, blank=True, default="")
    locale = models.CharField(max_length=10, default="en")
    conversation_context = models.JSONField(default=dict, blank=True)
    is_authenticated = models.BooleanField(default=False)
    status = models.CharField(
        max_length=20,
        choices=ChatSessionStatus.choices,
        default=ChatSessionStatus.ACTIVE,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_active_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "chat_sessions"
        indexes = [
            models.Index(fields=["clinic", "status"]),
            models.Index(fields=["clinic", "last_active_at"]),
            models.Index(fields=["clinic", "patient"]),
        ]

    def __str__(self) -> str:
        return f"Session {self.session_token[:8]}…"


class MessageRole(models.TextChoices):
    USER = "user", "User"
    ASSISTANT = "assistant", "Assistant"
    SYSTEM = "system", "System"
    TOOL = "tool", "Tool"


class MessageType(models.TextChoices):
    TEXT = "text", "Text"
    TOOL_CALL = "tool_call", "Tool Call"
    TOOL_RESULT = "tool_result", "Tool Result"
    SYSTEM = "system", "System"
    ERROR = "error", "Error"


class ChatMessage(TenantModel):
    session = models.ForeignKey(
        ChatSession,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    role = models.CharField(max_length=20, choices=MessageRole.choices)
    message_type = models.CharField(
        max_length=20,
        choices=MessageType.choices,
        default=MessageType.TEXT,
    )
    content = models.TextField()
    # Expected metadata shape:
    # {
    #   "intent": "BOOK_APPOINTMENT",
    #   "entities": {"doctor": "Rajat", "date": "Tomorrow"},
    #   "latency": 310,
    #   "tool_called": "check_availability"
    # }
    metadata = models.JSONField(default=dict, blank=True)
    token_count = models.PositiveIntegerField(null=True, blank=True)
    sequence_number = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "chat_messages"
        ordering = ["sequence_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["session", "sequence_number"],
                name="uq_message_session_sequence",
            ),
        ]
        indexes = [
            models.Index(fields=["session", "created_at"]),
            models.Index(fields=["clinic", "created_at"]),
            models.Index(fields=["session", "message_type"]),
        ]

    def __str__(self) -> str:
        return f"{self.role}/{self.message_type}: {self.content[:50]}"


# ─── Authentication ────────────────────────────────────────────────────────────


class OTPVerification(TenantModel):
    session = models.ForeignKey(
        ChatSession,
        on_delete=models.CASCADE,
        related_name="otp_verifications",
    )
    patient = models.ForeignKey(
        Patient,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="otp_verifications",
    )
    phone = models.CharField(max_length=20)
    code_hash = models.CharField(max_length=128)
    attempts = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=3)
    expires_at = models.DateTimeField()
    verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "otp_verifications"
        indexes = [
            models.Index(fields=["session", "created_at"]),
            models.Index(fields=["clinic", "phone", "expires_at"]),
        ]


# ─── Analytics ─────────────────────────────────────────────────────────────────


class AIProvider(models.TextChoices):
    OPENAI = "openai", "OpenAI"
    ANTHROPIC = "anthropic", "Anthropic"
    GEMINI = "gemini", "Gemini"
    CACHE = "cache", "Cache"


class AIOperation(models.TextChoices):
    CHAT_COMPLETION = "chat_completion", "Chat Completion"
    EMBEDDING = "embedding", "Embedding"
    INTENT_CLASSIFICATION = "intent_classification", "Intent Classification"


class AIUsageLog(TenantModel):
    session = models.ForeignKey(
        ChatSession,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ai_usage_logs",
    )
    message = models.ForeignKey(
        ChatMessage,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ai_usage_logs",
    )
    provider = models.CharField(
        max_length=50,
        choices=AIProvider.choices,
        default=AIProvider.OPENAI,
    )
    operation = models.CharField(max_length=50, choices=AIOperation.choices)
    model = models.CharField(max_length=50)
    prompt_tokens = models.PositiveIntegerField(default=0)
    completion_tokens = models.PositiveIntegerField(default=0)
    total_tokens = models.PositiveIntegerField(default=0)
    latency_ms = models.PositiveIntegerField(default=0)
    cost_microcents = models.BigIntegerField(default=0)
    cached_response = models.BooleanField(default=False)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ai_usage_logs"
        indexes = [
            models.Index(fields=["clinic", "created_at"]),
            models.Index(fields=["clinic", "operation", "created_at"]),
            models.Index(fields=["clinic", "cached_response", "created_at"]),
            models.Index(fields=["session", "created_at"]),
        ]

    def __str__(self) -> str:
        cache_tag = " [cached]" if self.cached_response else ""
        return f"{self.provider}/{self.operation} — {self.total_tokens} tokens{cache_tag}"
