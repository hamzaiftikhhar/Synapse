from django.contrib import admin

from apps.specialties.models import Specialty


@admin.register(Specialty)
class SpecialtyAdmin(admin.ModelAdmin):
    list_display = ("name", "clinic", "slug", "is_active", "is_deleted")
    list_filter = ("is_active", "is_deleted", "clinic")
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}
