"""Clinic tenant models."""

from django.db import models
from django.db.models import Q

from core.models import TenantModel, TimestampedModel, UUIDModel


class ClinicStatus(models.TextChoices):
    ONBOARDING = "onboarding", "Onboarding"
    ACTIVE = "active", "Active"
    SUSPENDED = "suspended", "Suspended"
    CANCELLED = "cancelled", "Cancelled"


class ClinicType(models.TextChoices):
    PRIMARY_CARE = "primary_care", "Primary Care"
    MEDICAL_SPECIALTY = "medical_specialty", "Medical Specialty"
    NEUROLOGY = "neurology", "Neurology"
    CARDIOLOGY = "cardiology", "Cardiology"
    DERMATOLOGY = "dermatology", "Dermatology"
    AESTHETICS = "aesthetics", "Aesthetics / Med Spa"
    DENTAL = "dental", "Dental"
    PHYSICAL_THERAPY = "physical_therapy", "Physical Therapy"
    BEHAVIORAL_HEALTH = "behavioral_health", "Mental / Behavioral Health"
    LABORATORY = "laboratory", "Laboratory / Diagnostics"
    URGENT_CARE = "urgent_care", "Urgent Care"
    COSMETIC_SURGERY = "cosmetic_surgery", "Cosmetic / Plastic Surgery"
    MULTI_SPECIALTY = "multi_specialty", "Multi-Specialty"
    OTHER = "other", "Other"


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
        default=ClinicStatus.ONBOARDING,
    )
    clinic_type = models.CharField(
        max_length=32, choices=ClinicType.choices, blank=True, default=""
    )
    # Resume cursor for the onboarding wizard — one of the step slugs it defines.
    # Empty + status=onboarding means onboarding hasn't been started yet.
    onboarding_step = models.CharField(max_length=32, blank=True, default="")
    onboarding_completed_at = models.DateTimeField(null=True, blank=True)

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
            models.CheckConstraint(
                check=Q(day_of_week__gte=0) & Q(day_of_week__lte=6),
                name="chk_clinic_hours_day_of_week",
            ),
        ]
        indexes = [
            models.Index(fields=["clinic"]),
            # Multiple intervals are now allowed per (clinic, day_of_week) —
            # this indexes the grouped-by-day query pattern instead of a
            # uniqueness guarantee. Overlap/duplicate/closed+open conflicts
            # are validated in apps/api/clinics/router.py, not the DB.
            models.Index(fields=["clinic", "day_of_week"], name="idx_clinic_hours_day"),
        ]

    def __str__(self) -> str:
        return f"{self.clinic} — day {self.day_of_week}"


class ClinicApplicationStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    REVIEWING = "reviewing", "Reviewing"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    CONVERTED = "converted", "Converted"


class ClinicApplication(UUIDModel, TimestampedModel):
    """A prospective clinic's self-serve "Get Started" submission — the
    pre-tenant intake record. Never the tenant itself; Super Admin review
    turns an approved application into a real Clinic + owner ClinicStaff
    + Subscription (see apps/api/platform/router.py `approve_application`).
    """

    clinic_name = models.CharField(max_length=255)
    owner_name = models.CharField(max_length=255)
    work_email = models.EmailField()
    phone = models.CharField(max_length=20, blank=True, default="")
    website = models.CharField(max_length=255, blank=True, default="")
    num_doctors = models.PositiveSmallIntegerField(null=True, blank=True)
    current_scheduling_system = models.CharField(max_length=255, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    # The Plan slug requested at submission time (apps.billing.models.Plan) —
    # stored as a slug, not a FK, so this pre-tenant model never depends on
    # the billing app; resolved to a real Plan only at approval time.
    plan_slug = models.CharField(max_length=64)

    status = models.CharField(
        max_length=16,
        choices=ClinicApplicationStatus.choices,
        default=ClinicApplicationStatus.PENDING,
    )
    reviewed_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_clinic_applications",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.CharField(max_length=500, blank=True, default="")
    converted_clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="source_application",
    )

    class Meta:
        db_table = "clinic_applications"
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["work_email"]),
        ]

    def __str__(self) -> str:
        return f"{self.clinic_name} ({self.status})"
