from django.contrib import admin

from apps.insurance.models import InsurancePlan


@admin.register(InsurancePlan)
class InsurancePlanAdmin(admin.ModelAdmin):
    list_display = (
        "provider_name",
        "plan_name",
        "clinic",
        "plan_type",
        "is_accepted",
        "is_deleted",
    )
    list_filter = ("is_accepted", "is_deleted", "plan_type", "clinic")
    search_fields = ("provider_name", "plan_name")
