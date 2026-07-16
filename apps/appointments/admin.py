from django.contrib import admin

from apps.appointments.models import Appointment


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = (
        "confirmation_code",
        "patient",
        "doctor",
        "clinic",
        "start_time",
        "status",
        "source",
    )
    list_filter = ("status", "source", "clinic")
    search_fields = ("confirmation_code", "patient__first_name", "patient__last_name")
    date_hierarchy = "start_time"
