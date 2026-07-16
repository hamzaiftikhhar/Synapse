from django.contrib import admin

from apps.widget.models import WidgetSettings


@admin.register(WidgetSettings)
class WidgetSettingsAdmin(admin.ModelAdmin):
    list_display = ("clinic", "updated_at")
    search_fields = ("clinic__name", "clinic__slug")
