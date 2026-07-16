from django.contrib import admin

from apps.chatbot.models import ChatMessage, ChatSession, OTPVerification


class ChatMessageInline(admin.TabularInline):
    model = ChatMessage
    extra = 0
    fields = ("sequence_number", "role", "message_type", "content", "created_at")
    readonly_fields = ("created_at",)
    ordering = ("sequence_number",)


@admin.register(ChatSession)
class ChatSessionAdmin(admin.ModelAdmin):
    list_display = (
        "session_token",
        "clinic",
        "patient",
        "status",
        "is_authenticated",
        "created_at",
        "last_active_at",
    )
    list_filter = ("status", "is_authenticated", "clinic")
    search_fields = ("session_token",)
    inlines = [ChatMessageInline]


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = (
        "session",
        "sequence_number",
        "role",
        "message_type",
        "clinic",
        "created_at",
    )
    list_filter = ("role", "message_type", "clinic")
    search_fields = ("content",)


@admin.register(OTPVerification)
class OTPVerificationAdmin(admin.ModelAdmin):
    list_display = (
        "phone",
        "clinic",
        "session",
        "attempts",
        "expires_at",
        "verified_at",
    )
    list_filter = ("clinic",)
    search_fields = ("phone",)
