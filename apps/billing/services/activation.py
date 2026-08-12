"""The one deliberate boundary where billing state is allowed to touch
clinic lifecycle state — kept as a single, explicit rule rather than
scattering `Clinic.status` writes through billing code (see apps/api/
clinics/router.py `complete_onboarding` for the other half of this
handshake: it defers activation to here whenever a clinic has a pending
Subscription instead of activating immediately)."""

from __future__ import annotations

from django.utils import timezone

from apps.billing.models import Subscription


def maybe_activate_clinic(subscription: Subscription) -> None:
    from apps.clinics.models import ClinicStatus

    clinic = subscription.clinic
    if clinic.status != ClinicStatus.ONBOARDING or not subscription.has_access:
        return

    # Defensive re-check of the same operational checklist complete_onboarding()
    # already validated when it set onboarding_step="billing" — payment can be
    # confirmed much later, so re-verify nothing regressed (a doctor deleted,
    # hours cleared) in the meantime. Deliberately re-implemented here rather
    # than imported from apps.api.clinics.router — a services module should
    # not depend on an API router module.
    from apps.clinics.models import ClinicBusinessHours
    from apps.doctors.models import Doctor, DoctorSchedule
    from apps.services.models import Service

    address = clinic.address or {}
    location_ready = bool(
        (address.get("line1") or "").strip()
        and (address.get("city") or "").strip()
        and (address.get("state") or "").strip()
        and (address.get("postal_code") or "").strip()
        and (address.get("country") or "").strip()
        and clinic.phone.strip()
    )
    ready = (
        bool(clinic.name.strip() and clinic.clinic_type)
        and location_ready
        and Doctor.objects.filter(clinic=clinic, is_deleted=False, is_active=True).exists()
        and Service.objects.filter(clinic=clinic, is_deleted=False, is_active=True).exists()
        and ClinicBusinessHours.objects.filter(clinic=clinic, is_closed=False).exists()
        and DoctorSchedule.objects.filter(
            clinic=clinic, is_active=True, doctor__is_deleted=False, doctor__is_active=True
        ).exists()
    )
    if not ready:
        return

    clinic.status = ClinicStatus.ACTIVE
    clinic.onboarding_completed_at = timezone.now()
    clinic.onboarding_step = "review"
    clinic.save(
        update_fields=["status", "onboarding_completed_at", "onboarding_step", "updated_at"]
    )
