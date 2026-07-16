"""Appointments."""

from django.db import models
from django.db.models import Q

from core.models import TenantModel, TimestampedModel


class AppointmentStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    CONFIRMED = "confirmed", "Confirmed"
    CANCELLED = "cancelled", "Cancelled"
    COMPLETED = "completed", "Completed"
    NO_SHOW = "no_show", "No Show"
    RESCHEDULED = "rescheduled", "Rescheduled"


class AppointmentSource(models.TextChoices):
    CHATBOT = "chatbot", "Chatbot"
    ADMIN = "admin", "Admin"
    PHONE = "phone", "Phone"
    WALK_IN = "walk_in", "Walk-in"
    IMPORT = "import", "Import"


class Appointment(TenantModel, TimestampedModel):
    doctor = models.ForeignKey(
        "doctors.Doctor",
        on_delete=models.PROTECT,
        related_name="appointments",
    )
    patient = models.ForeignKey(
        "patients.Patient",
        on_delete=models.PROTECT,
        related_name="appointments",
    )
    service = models.ForeignKey(
        "services.Service",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="appointments",
    )
    insurance_plan = models.ForeignKey(
        "insurance.InsurancePlan",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="appointments",
    )
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    status = models.CharField(
        max_length=20,
        choices=AppointmentStatus.choices,
        default=AppointmentStatus.PENDING,
    )
    confirmation_code = models.CharField(max_length=10, unique=True)
    notes = models.TextField(blank=True, default="")
    source = models.CharField(
        max_length=20,
        choices=AppointmentSource.choices,
        default=AppointmentSource.CHATBOT,
    )

    class Meta:
        db_table = "appointments"
        indexes = [
            models.Index(fields=["clinic", "doctor", "start_time"]),
            models.Index(fields=["clinic", "patient"]),
            models.Index(fields=["clinic", "status", "start_time"]),
        ]
        constraints = [
            models.CheckConstraint(
                check=Q(end_time__gt=models.F("start_time")),
                name="chk_appointment_end_after_start",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.patient} with {self.doctor} at {self.start_time}"
