"""Widget configuration for clinic embeds."""

from core.models import TimestampedModel, UUIDModel
from django.db import models


class WidgetSettings(UUIDModel, TimestampedModel):
    clinic = models.OneToOneField(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="widget_settings",
    )
    # Single JSON: {widget, ai, booking, feature_flags}
    configuration = models.JSONField(default=dict)

    class Meta:
        db_table = "widget_settings"
        verbose_name_plural = "widget settings"

    def __str__(self) -> str:
        return f"Widget settings for {self.clinic.name}"
