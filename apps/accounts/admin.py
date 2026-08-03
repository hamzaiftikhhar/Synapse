from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from apps.accounts.models import AuditLog, ClinicStaff, StaffAuthToken, User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    ordering = ("email",)
    list_display = (
        "email",
        "username",
        "role",
        "is_clinic_owner",
        "email_verified_at",
        "is_staff",
        "is_active",
    )
    list_filter = (
        "role",
        "is_clinic_owner",
        "is_staff",
        "is_active",
        "two_factor_enabled",
    )
    search_fields = ("email", "username", "first_name", "last_name", "phone_number")
    fieldsets = (
        (None, {"fields": ("email", "username", "password")}),
        ("Personal info", {"fields": ("first_name", "last_name", "phone_number")}),
        (
            "Clinic access",
            {
                "fields": (
                    "role",
                    "is_clinic_owner",
                    "email_verified_at",
                    "two_factor_enabled",
                    "last_login_ip",
                )
            },
        ),
        (
            "Permissions",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "email",
                    "username",
                    "password1",
                    "password2",
                    "role",
                    "is_clinic_owner",
                ),
            },
        ),
    )


@admin.register(ClinicStaff)
class ClinicStaffAdmin(admin.ModelAdmin):
    list_display = ("user", "clinic", "is_active", "created_at")
    list_filter = ("is_active", "clinic")
    search_fields = ("user__email", "user__username", "clinic__slug")


@admin.register(StaffAuthToken)
class StaffAuthTokenAdmin(admin.ModelAdmin):
    list_display = ("user", "purpose", "expires_at", "used_at", "created_at")
    list_filter = ("purpose",)
    search_fields = ("user__email",)


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("action", "actor", "clinic", "object_type", "created_at")
    list_filter = ("action",)
    search_fields = ("actor__email", "clinic__slug", "object_id")
    readonly_fields = (
        "actor",
        "clinic",
        "action",
        "object_type",
        "object_id",
        "metadata",
        "ip_address",
        "created_at",
    )
