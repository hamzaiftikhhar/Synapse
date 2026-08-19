"""Staff identity — custom User + clinic membership.

Patients never use this model. Widget/patient auth is phone/email OTP + Patient JWT.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


class UserRole(models.TextChoices):
    SUPER_ADMIN = "SUPER_ADMIN", "Super Admin"
    CLINIC_ADMIN = "CLINIC_ADMIN", "Clinic Admin"
    STAFF = "STAFF", "Staff"


class User(AbstractUser):
    """
    Portal staff identity (email + password).

    Tenant binding lives on ClinicStaff (many clinics per user).
    SUPER_ADMIN has no required clinic membership.
    """

    email = models.EmailField(unique=True)
    role = models.CharField(
        max_length=20,
        choices=UserRole.choices,
        default=UserRole.STAFF,
    )
    phone_number = models.CharField(max_length=20, blank=True, default="")
    is_clinic_owner = models.BooleanField(default=False)
    email_verified_at = models.DateTimeField(null=True, blank=True)
    phone_verified_at = models.DateTimeField(null=True, blank=True)
    two_factor_enabled = models.BooleanField(default=False)
    last_login_ip = models.GenericIPAddressField(null=True, blank=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]

    class Meta:
        db_table = "users"

    @property
    def email_verified(self) -> bool:
        return self.email_verified_at is not None

    @property
    def phone_verified(self) -> bool:
        return self.phone_verified_at is not None

    def __str__(self) -> str:
        return f"{self.email} ({self.role})"


class ClinicStaff(models.Model):
    """Links a staff User to one or more clinics (multi-tenant membership)."""

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="clinic_memberships",
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


class StaffAuthTokenPurpose(models.TextChoices):
    EMAIL_VERIFY = "email_verify", "Email verification"
    PASSWORD_RESET = "password_reset", "Password reset"
    INVITE = "invite", "Clinic owner invitation"


class StaffAuthToken(models.Model):
    """One-time hashed tokens for email verify / password reset."""

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="auth_tokens",
    )
    purpose = models.CharField(max_length=32, choices=StaffAuthTokenPurpose.choices)
    token_hash = models.CharField(max_length=64, db_index=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "staff_auth_tokens"
        indexes = [
            models.Index(fields=["user", "purpose", "created_at"]),
        ]

    @staticmethod
    def hash_token(raw: str) -> str:
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @classmethod
    def issue(
        cls,
        *,
        user: User,
        purpose: str,
        ttl_hours: int = 24,
    ) -> tuple["StaffAuthToken", str]:
        raw = secrets.token_urlsafe(32)
        row = cls.objects.create(
            user=user,
            purpose=purpose,
            token_hash=cls.hash_token(raw),
            expires_at=timezone.now() + timedelta(hours=ttl_hours),
        )
        return row, raw

    def mark_used(self) -> None:
        self.used_at = timezone.now()
        self.save(update_fields=["used_at"])

    @property
    def is_valid(self) -> bool:
        if self.used_at is not None:
            return False
        return timezone.now() < self.expires_at


class AuditAction(models.TextChoices):
    LOGIN = "login", "Login"
    REGISTER = "register", "Register"
    EMAIL_VERIFY = "email_verify", "Email verify"
    PASSWORD_RESET = "password_reset", "Password reset"
    PASSWORD_CHANGE = "password_change", "Password change"
    PHONE_VERIFY_REQUESTED = "phone_verify_requested", "Phone verification requested"
    PHONE_VERIFY_APPROVED = "phone_verify_approved", "Phone verification approved"
    PHONE_VERIFY_FAILED = "phone_verify_failed", "Phone verification failed"
    ENTER_CLINIC = "enter_clinic", "Enter clinic"
    EXIT_CLINIC = "exit_clinic", "Exit clinic"
    CLINIC_CREATE = "clinic_create", "Clinic create"
    CLINIC_STATUS = "clinic_status", "Clinic status change"
    DOCUMENT_UPLOAD = "document_upload", "Document upload"
    DOCUMENT_DELETE = "document_delete", "Document delete"
    DOCTOR_DELETE = "doctor_delete", "Doctor delete"
    APPOINTMENT_CANCEL = "appointment_cancel", "Appointment cancel"
    INSURANCE_UPDATE = "insurance_update", "Insurance update"
    TENANT_SELECT = "tenant_select", "Tenant select"
    SUBSCRIPTION_CHECKOUT_STARTED = "subscription_checkout_started", "Subscription checkout started"
    SUBSCRIPTION_CANCEL_REQUESTED = "subscription_cancel_requested", "Subscription cancel requested"
    SUBSCRIPTION_CHANGE_REQUESTED = "subscription_change_requested", "Subscription change requested"
    APPLICATION_APPROVED = "application_approved", "Clinic application approved"
    APPLICATION_REJECTED = "application_rejected", "Clinic application rejected"
    INVITE_ACCEPTED = "invite_accepted", "Invitation accepted"
    USER_INVITE = "user_invite", "User invited"
    USER_UPDATE = "user_update", "User updated"
    PLAN_UPDATE = "plan_update", "Billing plan updated"


class AuditLog(models.Model):
    """Immutable audit trail for sensitive platform / clinic actions."""

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
    )
    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
    )
    action = models.CharField(max_length=64, choices=AuditAction.choices)
    object_type = models.CharField(max_length=64, blank=True, default="")
    object_id = models.CharField(max_length=64, blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "audit_logs"
        indexes = [
            models.Index(fields=["clinic", "created_at"]),
            models.Index(fields=["actor", "created_at"]),
            models.Index(fields=["action", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.action} @ {self.created_at:%Y-%m-%d %H:%M}"
