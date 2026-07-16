from django.contrib import admin

from apps.patients.models import Patient


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = (
        "first_name",
        "last_name",
        "phone",
        "email",
        "clinic",
        "is_verified",
        "preferred_language",
    )
    list_filter = ("is_verified", "preferred_language", "clinic")
    search_fields = ("first_name", "last_name", "phone", "email")
