from django.contrib import admin

from apps.accounts.models import ClinicStaff


@admin.register(ClinicStaff)
class ClinicStaffAdmin(admin.ModelAdmin):
    list_display = ("user", "clinic", "is_active", "created_at")
    list_filter = ("is_active", "clinic")
    search_fields = ("user__username", "user__email", "clinic__slug")
