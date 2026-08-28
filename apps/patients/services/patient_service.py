"""Patient profile operations — source of truth for widget identity."""

from __future__ import annotations

import hashlib
from datetime import date, timedelta
from uuid import UUID

from django.utils import timezone

from apps.clinics.models import Clinic
from apps.patients.models import Patient

_DOB_MAX_ATTEMPTS = 5
_DOB_LOCKOUT_MINUTES = 30
_DOB_GENERIC_MESSAGE = "We couldn't verify your identity. Please contact the clinic directly."


class IdentityVerificationError(Exception):
    """Raised by verify_date_of_birth. Message is deliberately identical
    for a mismatch and a lockout — never confirm to the caller which one
    it was, or whether a record even exists for the phone/email given."""

    def __init__(self, message: str = _DOB_GENERIC_MESSAGE, *, status_code: int = 401) -> None:
        super().__init__(message)
        self.status_code = status_code


def email_placeholder_phone(email: str) -> str:
    """
    Deterministic stand-in for Patient.phone (max_length=20, unique per
    clinic) when a patient registers with email only.

    Must fit 20 chars, so raw truncation of the email is not safe — two
    different addresses sharing their first ~14 characters would truncate
    to the same string and silently collide into one Patient record. Hash
    the full address instead so collisions require a genuine hash clash,
    not just a shared prefix.
    """
    digest = hashlib.sha1(email.strip().lower().encode()).hexdigest()[:14]
    return f"email:{digest}"


def get_by_phone(*, clinic: Clinic, phone: str) -> Patient | None:
    return Patient.objects.filter(clinic=clinic, phone=phone).first()


def get_or_create_by_phone(
    *,
    clinic: Clinic,
    phone: str,
    first_name: str = "",
    last_name: str = "",
) -> tuple[Patient, bool]:
    """
    Ensure a Patient row exists for this clinic + phone.

    OTP verifies the phone on this record; it does not replace Patient identity.
    """
    patient = get_by_phone(clinic=clinic, phone=phone)
    if patient is not None:
        return patient, False

    patient = Patient.objects.create(
        clinic=clinic,
        phone=phone,
        first_name=first_name.strip() or "New",
        last_name=last_name.strip() or "Patient",
        is_verified=False,
    )
    return patient, True


def get_or_create_by_email(
    *,
    clinic: Clinic,
    email: str,
    first_name: str = "",
    last_name: str = "",
) -> tuple[Patient, bool]:
    """Mirrors get_or_create_by_phone for an email-first registrant — a
    deterministic placeholder phone (email_placeholder_phone) satisfies
    Patient.phone's unique constraint without ever surfacing that internal
    stand-in as a real phone number. Same "OTP/contact capture verifies
    the record, it does not replace Patient identity" invariant.
    """
    email = email.strip().lower()
    patient = Patient.objects.filter(clinic=clinic, email=email).first()
    if patient is not None:
        return patient, False

    placeholder = email_placeholder_phone(email)
    patient, created = get_or_create_by_phone(
        clinic=clinic, phone=placeholder, first_name=first_name, last_name=last_name,
    )
    if not patient.email:
        patient.email = email
        patient.save(update_fields=["email", "updated_at"])
    return patient, created


def mark_phone_verified(patient: Patient) -> Patient:
    patient.is_verified = True
    patient.verified_at = timezone.now()
    patient.save(update_fields=["is_verified", "verified_at", "updated_at"])
    return patient


def update_profile(
    patient: Patient,
    *,
    first_name: str | None = None,
    last_name: str | None = None,
    email: str | None = None,
) -> Patient:
    fields: list[str] = []
    if first_name is not None and first_name.strip():
        patient.first_name = first_name.strip()
        fields.append("first_name")
    if last_name is not None and last_name.strip():
        patient.last_name = last_name.strip()
        fields.append("last_name")
    if email is not None:
        patient.email = email.strip()
        fields.append("email")
    if fields:
        fields.append("updated_at")
        patient.save(update_fields=fields)
    return patient


def get_for_clinic(*, clinic_id: UUID, patient_id: UUID) -> Patient | None:
    return Patient.objects.filter(clinic_id=clinic_id, pk=patient_id).first()


def verify_date_of_birth(patient: Patient, dob: date) -> bool:
    """Compare `dob` against `patient.date_of_birth` — the identity check
    that runs after OTP proves contact ownership (never before: gating on
    DOB pre-OTP would make it a brute-forceable oracle with no rate limit
    tied to a proven channel).

    A patient with no stored DOB (a brand-new record — send_otp always
    get-or-creates one before the code goes out — or a legacy record that
    predates this check) has nothing to compare against: captured and
    treated as verified, never a lockout/mismatch case, so a real patient
    is never permanently blocked by missing historical data.

    Lockout is scoped to (clinic, patient) via fields on Patient itself,
    deliberately not the OTPVerification row — that row's own `attempts`
    resets to 0 on every resend (send_otp always creates a fresh row), so
    inheriting that pattern here would let a resend reset a DOB
    brute-force counter too.
    """
    now = timezone.now()
    if patient.dob_check_locked_until and patient.dob_check_locked_until > now:
        raise IdentityVerificationError(status_code=429)

    if patient.date_of_birth is None:
        patient.date_of_birth = dob
        patient.save(update_fields=["date_of_birth", "updated_at"])
        return True

    if patient.date_of_birth == dob:
        if patient.dob_check_attempts:
            patient.dob_check_attempts = 0
            patient.save(update_fields=["dob_check_attempts", "updated_at"])
        return True

    patient.dob_check_attempts += 1
    update_fields = ["dob_check_attempts", "updated_at"]
    if patient.dob_check_attempts >= _DOB_MAX_ATTEMPTS:
        patient.dob_check_locked_until = now + timedelta(minutes=_DOB_LOCKOUT_MINUTES)
        update_fields.append("dob_check_locked_until")
    patient.save(update_fields=update_fields)
    raise IdentityVerificationError()
