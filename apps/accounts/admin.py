from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from apps.accounts.models import ClinicStaff, User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    ordering = ("email",)
    list_display = (
        "email",
        "username",
        "role",
        "is_clinic_owner",
        "is_staff",
        "is_active",
    )
    list_filter = ("role", "is_clinic_owner", "is_staff", "is_active", "two_factor_enabled")
    search_fields = ("email", "username", "first_name", "last_name", "phone_number")
    fieldsets = (
        (None, {"fields": ("email", "username", "password")}),
        ("Personal info", {"fields": ("first_name", "last_name", "phone_number")}),
        (
            "Clinic access",
            {"fields": ("role", "is_clinic_owner", "two_factor_enabled", "last_login_ip")},
        ),
        (
            "Permissions",
            {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")},
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
