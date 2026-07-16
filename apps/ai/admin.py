from django.contrib import admin

from apps.ai.models import AIUsageLog


@admin.register(AIUsageLog)
class AIUsageLogAdmin(admin.ModelAdmin):
    list_display = (
        "clinic",
        "provider",
        "operation",
        "model",
        "total_tokens",
        "latency_ms",
        "cost_microcents",
        "cached_response",
        "created_at",
    )
    list_filter = ("provider", "operation", "cached_response", "clinic")
    search_fields = ("model",)
    date_hierarchy = "created_at"
