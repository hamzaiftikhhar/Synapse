from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from apps.accounts.models import ClinicStaff, User
#why we have admin.py file? because we want to register the models with the admin site. what is the admin site? the admin site is a web interface for the admin to manage the models. 

@admin.register(User) #what is the @admin.register(User)? it is a decorator that registers the User model with the admin site.
class UserAdmin(DjangoUserAdmin): #what is the UserAdmin? it is a class that inherits from DjangoUserAdmin.
    ordering = ("email",) #what is the ordering? it is a list of fields to order the results by.
    list_display = ( #what is the list_display? it is a list of fields to display in the admin site.
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
    add_fieldsets = ( #what is the add_fieldsets? it is a list of fields to display in the add user page. This controls the form when creating a new user.
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
