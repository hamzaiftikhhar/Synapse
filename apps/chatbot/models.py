"""Chat sessions, messages, and OTP verification."""

from django.db import models

from core.models import TenantModel


class ChatSessionStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    CLOSED = "closed", "Closed"
    ESCALATED = "escalated", "Escalated"


class ChatSession(TenantModel):
    patient = models.ForeignKey(
        "patients.Patient",
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


class OTPVerification(TenantModel):
    session = models.ForeignKey(
        ChatSession,
        on_delete=models.CASCADE,
        related_name="otp_verifications",
    )
    patient = models.ForeignKey(
        "patients.Patient",
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

    def __str__(self) -> str:
        return f"OTP {self.phone} ({self.session_id})"
