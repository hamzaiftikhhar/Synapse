"""Chat sessions, messages, and OTP verification."""

from django.db import models

from core.models import TenantModel


class ChatSessionStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    CLOSED = "closed", "Closed"
    ESCALATED = "escalated", "Escalated"


class ChatVisitor(TenantModel):
    """A stable anonymous browser identity, independent of any one
    conversation. One visitor can have many `ChatSession`s (e.g. a closed
    conversation followed by a new one) — linking `patient` here, once,
    is what makes every one of that visitor's sessions resolve to the same
    identity without ever copying or recreating conversation rows. See
    ROADMAP.md's persistent-chat-history phase for the full design and the
    explicit privacy boundary: resolving to the same patient as another
    visitor never grants access to that other visitor's conversations."""

    visitor_key = models.CharField(max_length=64, unique=True)
    patient = models.ForeignKey(
        "patients.Patient",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="chat_visitors",
    )
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "chat_visitors"
        indexes = [
            models.Index(fields=["clinic", "patient"]),
        ]

    def __str__(self) -> str:
        return f"Visitor {self.visitor_key[:8]}…"


class ChatSession(TenantModel):
    visitor = models.ForeignKey(
        ChatVisitor,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="chat_sessions",
    )
    patient = models.ForeignKey(
        "patients.Patient",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="chat_sessions",
    )
    # Set only for staff/QA sessions (apps.api.chat.router's
    # /message/staff — clinic staff or a super admin testing the bot from
    # the dashboard, never the patient-facing widget). Lets resume find
    # "my own most recent QA session in this clinic" without mixing up
    # different staff members testing the same clinic concurrently, and
    # without mixing up a super admin's sessions across different clinics
    # they've entered — SET_NULL rather than CASCADE so a deleted staff
    # account doesn't destroy the conversation, only the attribution.
    created_by_user = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="chat_sessions_created",
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
            # The resume-flow's core query: "this visitor's most recent
            # session," regardless of status (see ROADMAP.md — v1
            # deliberately has no auto-close, so status isn't part of this
            # lookup).
            models.Index(fields=["visitor", "last_active_at"]),
            # Same idea, for staff/QA resume: "this staff user's most
            # recent QA session in this clinic."
            models.Index(fields=["clinic", "created_by_user", "last_active_at"]),
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
    class Channel(models.TextChoices):
        SMS = "sms", "SMS"
        EMAIL = "email", "Email"

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
    phone = models.CharField(max_length=20, blank=True, default="")
    email = models.EmailField(blank=True, default="")
    channel = models.CharField(
        max_length=16,
        choices=Channel.choices,
        default=Channel.SMS,
    )
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
            models.Index(fields=["clinic", "email", "expires_at"]),
        ]

    def __str__(self) -> str:
        target = self.phone or self.email or "?"
        return f"OTP {self.channel}:{target} ({self.session_id})"
