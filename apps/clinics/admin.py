from django.contrib import admin

from apps.clinics.models import Clinic, ClinicBusinessHours


class ClinicBusinessHoursInline(admin.TabularInline):
    model = ClinicBusinessHours
    extra = 0


@admin.register(Clinic)
class ClinicAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "email", "status", "timezone", "created_at")
    list_filter = ("status",)
    search_fields = ("name", "slug", "email")
    prepopulated_fields = {"slug": ("name",)}
    inlines = [ClinicBusinessHoursInline]


@admin.register(ClinicBusinessHours)
class ClinicBusinessHoursAdmin(admin.ModelAdmin):
    list_display = ("clinic", "day_of_week", "open_time", "close_time", "is_closed")
    list_filter = ("is_closed", "day_of_week")
