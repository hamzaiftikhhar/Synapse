"""Staff identity — custom User + clinic membership.

Patients never use this model. Widget/patient auth is phone OTP + Patient JWT
(see apps.api.auth.patient).
"""

from django.contrib.auth.models import AbstractUser
from django.db import models


class UserRole(models.TextChoices):
    SUPER_ADMIN = "SUPER_ADMIN", "Super Admin"
    CLINIC_ADMIN = "CLINIC_ADMIN", "Clinic Admin"
    STAFF = "STAFF", "Staff"


class User(AbstractUser):
    """
    Portal staff identity (email + password).

    Tenant binding lives on ClinicStaff, not here — SUPER_ADMIN has no clinic.
    Patients are apps.patients.Patient and never get a row in this table.
    """

    email = models.EmailField(unique=True)
    role = models.CharField(
        max_length=20,
        choices=UserRole.choices,
        default=UserRole.STAFF,
    )
    phone_number = models.CharField(max_length=20, blank=True, default="")
    is_clinic_owner = models.BooleanField(default=False)
    two_factor_enabled = models.BooleanField(default=False)
    last_login_ip = models.GenericIPAddressField(null=True, blank=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]

    class Meta:
        db_table = "users"

    def __str__(self) -> str:
        return f"{self.email} ({self.role})"


class ClinicStaff(models.Model):
    """
    Links a staff User to exactly one clinic.

    Used by staff login — JWT embeds clinic_id + role for tenant isolation.
    """

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="clinic_staff",
    )
    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="staff",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "clinic_staff"
        verbose_name_plural = "clinic staff"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "clinic"],
                name="uq_clinic_staff_user_clinic",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user.email} @ {self.clinic.slug}"
