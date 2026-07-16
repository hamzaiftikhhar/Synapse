"""Doctors, schedules, leaves, and M2M junction tables."""

from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Q

from core.models import SoftDeleteModel, TenantModel, TimestampedModel


def default_languages() -> list[str]:
    return ["en"]


class Doctor(TenantModel, TimestampedModel, SoftDeleteModel):
    full_name = models.CharField(max_length=255)
    title = models.CharField(max_length=50, blank=True, default="")
    bio = models.TextField(blank=True, default="")
    photo_url = models.URLField(max_length=500, blank=True, default="")
    languages = ArrayField(
        models.CharField(max_length=10),
        default=default_languages,
    )
    is_active = models.BooleanField(default=True)
    is_accepting_patients = models.BooleanField(default=True)
    metadata = models.JSONField(default=dict, blank=True)
    specialties = models.ManyToManyField(
        "specialties.Specialty",
        through="DoctorSpecialty",
        related_name="doctors",
    )
    services = models.ManyToManyField(
        "services.Service",
        through="DoctorService",
        related_name="doctors",
    )
    insurance_plans = models.ManyToManyField(
        "insurance.InsurancePlan",
        through="DoctorInsurance",
        related_name="doctors",
    )

    class Meta:
        db_table = "doctors"
        indexes = [
            # Active doctor lists: exclude soft-deleted rows from the index
            models.Index(
                fields=["clinic", "is_active"],
                name="idx_doctors_active_live",
                condition=Q(is_deleted=False),
            ),
        ]

    def __str__(self) -> str:
        return self.full_name


class DoctorSpecialty(models.Model):
    doctor = models.ForeignKey(
        Doctor,
        on_delete=models.CASCADE,
        related_name="doctor_specialties",
    )
    specialty = models.ForeignKey(
        "specialties.Specialty",
        on_delete=models.CASCADE,
        related_name="doctor_specialties",
    )
    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="doctor_specialties",
    )

    class Meta:
        db_table = "doctor_specialties"
        constraints = [
            models.UniqueConstraint(
                fields=["doctor", "specialty"],
                name="uq_doctor_specialty",
            ),
        ]
        indexes = [
            models.Index(fields=["clinic", "specialty"]),
            models.Index(fields=["clinic", "doctor"]),
        ]


class DoctorService(models.Model):
    doctor = models.ForeignKey(
        Doctor,
        on_delete=models.CASCADE,
        related_name="doctor_services",
    )
    service = models.ForeignKey(
        "services.Service",
        on_delete=models.CASCADE,
        related_name="doctor_services",
    )
    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="doctor_services",
    )

    class Meta:
        db_table = "doctor_services"
        constraints = [
            models.UniqueConstraint(
                fields=["doctor", "service"],
                name="uq_doctor_service",
            ),
        ]
        indexes = [
            models.Index(fields=["clinic", "service"]),
            models.Index(fields=["clinic", "doctor"]),
        ]


class DoctorInsurance(models.Model):
    doctor = models.ForeignKey(
        Doctor,
        on_delete=models.CASCADE,
        related_name="doctor_insurances",
    )
    insurance_plan = models.ForeignKey(
        "insurance.InsurancePlan",
        on_delete=models.CASCADE,
        related_name="doctor_insurances",
    )
    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="doctor_insurances",
    )

    class Meta:
        db_table = "doctor_insurance"
        constraints = [
            models.UniqueConstraint(
                fields=["doctor", "insurance_plan"],
                name="uq_doctor_insurance",
            ),
        ]
        indexes = [
            models.Index(fields=["clinic", "insurance_plan"]),
            models.Index(fields=["clinic", "doctor"]),
        ]


class DoctorSchedule(TenantModel, TimestampedModel):
    doctor = models.ForeignKey(
        Doctor,
        on_delete=models.CASCADE,
        related_name="schedules",
    )
    day_of_week = models.PositiveSmallIntegerField()  # 0=Monday
    start_time = models.TimeField()
    end_time = models.TimeField()
    slot_duration_min = models.PositiveSmallIntegerField(default=30)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "doctor_schedules"
        indexes = [
            models.Index(fields=["clinic", "doctor", "day_of_week"]),
            models.Index(fields=["clinic", "doctor", "is_active"]),
        ]
        constraints = [
            models.CheckConstraint(
                check=Q(day_of_week__gte=0) & Q(day_of_week__lte=6),
                name="chk_schedule_day_of_week",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.doctor} — day {self.day_of_week}"


class DoctorLeave(TenantModel, TimestampedModel):
    doctor = models.ForeignKey(
        Doctor,
        on_delete=models.CASCADE,
        related_name="leaves",
    )
    start_at = models.DateTimeField()
    end_at = models.DateTimeField()
    reason = models.CharField(max_length=255, blank=True, default="")
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "doctor_leaves"
        indexes = [
            models.Index(fields=["clinic", "doctor", "start_at", "end_at"]),
            models.Index(fields=["clinic", "doctor", "is_active"]),
        ]
        constraints = [
            models.CheckConstraint(
                check=Q(end_at__gt=models.F("start_at")),
                name="chk_leave_end_after_start",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.doctor} leave {self.start_at:%Y-%m-%d}"
