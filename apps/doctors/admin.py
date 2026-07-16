from django.contrib import admin

from apps.doctors.models import (
    Doctor,
    DoctorInsurance,
    DoctorLeave,
    DoctorSchedule,
    DoctorService,
    DoctorSpecialty,
)


class DoctorSpecialtyInline(admin.TabularInline):
    model = DoctorSpecialty
    extra = 0


class DoctorServiceInline(admin.TabularInline):
    model = DoctorService
    extra = 0


class DoctorInsuranceInline(admin.TabularInline):
    model = DoctorInsurance
    extra = 0


class DoctorScheduleInline(admin.TabularInline):
    model = DoctorSchedule
    extra = 0


@admin.register(Doctor)
class DoctorAdmin(admin.ModelAdmin):
    list_display = (
        "full_name",
        "clinic",
        "title",
        "is_active",
        "is_accepting_patients",
        "is_deleted",
    )
    list_filter = ("is_active", "is_accepting_patients", "is_deleted", "clinic")
    search_fields = ("full_name",)
    inlines = [
        DoctorSpecialtyInline,
        DoctorServiceInline,
        DoctorInsuranceInline,
        DoctorScheduleInline,
    ]


@admin.register(DoctorSchedule)
class DoctorScheduleAdmin(admin.ModelAdmin):
    list_display = (
        "doctor",
        "clinic",
        "day_of_week",
        "start_time",
        "end_time",
        "is_active",
    )
    list_filter = ("day_of_week", "is_active", "clinic")


@admin.register(DoctorLeave)
class DoctorLeaveAdmin(admin.ModelAdmin):
    list_display = ("doctor", "clinic", "start_at", "end_at", "reason", "is_active")
    list_filter = ("is_active", "clinic")
