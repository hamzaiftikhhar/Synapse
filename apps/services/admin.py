from django.contrib import admin

from apps.services.models import Service


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ("name", "clinic", "duration_min", "is_active", "is_deleted")
    list_filter = ("is_active", "is_deleted", "clinic")
    search_fields = ("name",)
