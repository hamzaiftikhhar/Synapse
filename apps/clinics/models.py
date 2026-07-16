"""Clinic tenant models."""

from django.db import models
from django.db.models import Q

from core.models import TenantModel, TimestampedModel, UUIDModel


class ClinicStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    SUSPENDED = "suspended", "Suspended"
    ONBOARDING = "onboarding", "Onboarding"


class Clinic(UUIDModel, TimestampedModel):
    slug = models.SlugField(max_length=64, unique=True)
    name = models.CharField(max_length=255)
    email = models.EmailField()
    phone = models.CharField(max_length=20, blank=True, default="")
    address = models.JSONField(default=dict, blank=True)
    timezone = models.CharField(max_length=50, default="America/New_York")
    status = models.CharField(
        max_length=20,
        choices=ClinicStatus.choices,
        default=ClinicStatus.ACTIVE,
    )

    class Meta:
        db_table = "clinics"
        indexes = [
            models.Index(fields=["status"]),
        ]

    def __str__(self) -> str:
        return self.name


class ClinicBusinessHours(TenantModel, TimestampedModel):
    day_of_week = models.PositiveSmallIntegerField()  # 0=Monday
    open_time = models.TimeField(null=True, blank=True)
    close_time = models.TimeField(null=True, blank=True)
    is_closed = models.BooleanField(default=False)

    class Meta:
        db_table = "clinic_business_hours"
        verbose_name_plural = "clinic business hours"
        constraints = [
            models.UniqueConstraint(
                fields=["clinic", "day_of_week"],
                name="uq_clinic_business_hours_day",
            ),
            models.CheckConstraint(
                check=Q(day_of_week__gte=0) & Q(day_of_week__lte=6),
                name="chk_clinic_hours_day_of_week",
            ),
        ]
        indexes = [
            models.Index(fields=["clinic"]),
        ]

    def __str__(self) -> str:
        return f"{self.clinic} — day {self.day_of_week}"
