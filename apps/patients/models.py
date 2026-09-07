"""Patients."""

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.db.models.functions import Now, TruncDate

from apps.patients.dob import validate_date_of_birth
from core.models import TenantModel, TimestampedModel


class Patient(TenantModel, TimestampedModel):
    phone = models.CharField(max_length=20)  # required for OTP
    email = models.EmailField(blank=True, default="")
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    date_of_birth = models.DateField(null=True, blank=True)
    preferred_language = models.CharField(max_length=10, default="en")
    is_verified = models.BooleanField(default=False)
    verified_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Set when phone OTP verification succeeds.",
    )
    # Phase 42A — date-of-birth identity check, scoped to (clinic, patient)
    # rather than the OTPVerification row: OTP's own attempts counter
    # resets on every resend (a fresh OTPVerification row starts at
    # attempts=0), which would let a resend reset a DOB brute-force
    # counter too if it lived there instead. Independent of OTP lifecycle
    # by design — see apps/patients/services/patient_service.py.
    dob_check_attempts = models.PositiveSmallIntegerField(default=0)
    dob_check_locked_until = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta: #Meta is used to define the database table name and constraints and indexes
        db_table = "patients"
        constraints = [
            models.UniqueConstraint(
                fields=["clinic", "phone"],
                name="uq_patient_clinic_phone",
            ),
            models.UniqueConstraint(
                fields=["clinic", "email"],
                condition=~Q(email=""),
                name="uq_patient_clinic_email",
            ),
            models.CheckConstraint(
                condition=Q(date_of_birth__isnull=True)
                | Q(date_of_birth__lte=TruncDate(Now())),
                name="chk_patient_dob_not_future",
            ),
        ]
        indexes = [
            models.Index(fields=["clinic", "first_name"]),
            models.Index(fields=["clinic", "last_name"]),
        ]

    def clean(self) -> None:
        super().clean()
        try:
            validate_date_of_birth(self.date_of_birth)
        except ValidationError as exc:
            raise ValidationError({"date_of_birth": exc}) from exc

    def save(self, *args, **kwargs):
        # Keep API/admin/ORM writers honest even when clean() isn't called.
        update_fields = kwargs.get("update_fields")
        if update_fields is None or "date_of_birth" in update_fields:
            validate_date_of_birth(self.date_of_birth)
        super().save(*args, **kwargs)

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    def __str__(self) -> str:
        return self.full_name or self.phone
