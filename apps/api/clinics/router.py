"""Clinic profile, business hours, widget settings, and onboarding progress.

Onboarding has no dedicated model — it derives from `Clinic.status` /
`Clinic.onboarding_step` plus the real Doctor/Service/Specialty/InsurancePlan/
ClinicBusinessHours/DoctorSchedule rows already owned by the clinic.
"""

from __future__ import annotations

from django.utils import timezone
from ninja import Router
from ninja.errors import HttpError

from apps.api.auth.deps import clinic_from, jwt_auth
from apps.api.clinics.schemas import (
    BusinessHourIn,
    BusinessHourOut,
    ClinicProfileOut,
    ClinicProfileUpdateIn,
    OnboardingChecklistOut,
    OnboardingCountsOut,
    OnboardingStatusOut,
    WidgetSettingsOut,
    WidgetSettingsUpdateIn,
)
from apps.clinics.features import default_widget_configuration
from apps.clinics.models import Clinic, ClinicBusinessHours, ClinicStatus, ClinicType
from apps.doctors.models import Doctor, DoctorSchedule
from apps.insurance.models import InsurancePlan
from apps.services.models import Service
from apps.specialties.models import Specialty

router = Router(tags=["Clinics"])

_DAYS = range(7)  # 0=Monday .. 6=Sunday


def _serialize_clinic(clinic: Clinic) -> ClinicProfileOut:
    return ClinicProfileOut(
        id=clinic.id,
        slug=clinic.slug,
        name=clinic.name,
        clinic_type=clinic.clinic_type,
        email=clinic.email,
        phone=clinic.phone,
        address=clinic.address or {},
        timezone=clinic.timezone,
        status=clinic.status,
        onboarding_step=clinic.onboarding_step,
        onboarding_completed_at=clinic.onboarding_completed_at,
        created_at=clinic.created_at,
        updated_at=clinic.updated_at,
    )


@router.get("/me", response=ClinicProfileOut, auth=jwt_auth)
def get_clinic_profile(request):
    return _serialize_clinic(clinic_from(request))


@router.patch("/me", response=ClinicProfileOut, auth=jwt_auth)
def update_clinic_profile(request, payload: ClinicProfileUpdateIn):
    clinic = clinic_from(request)
    data = payload.dict(exclude_unset=True)
    if "clinic_type" in data and data["clinic_type"]:
        valid_types = {c.value for c in ClinicType}
        if data["clinic_type"] not in valid_types:
            raise HttpError(400, "Unknown clinic type")
    if "name" in data and not (data["name"] or "").strip():
        raise HttpError(400, "Clinic name is required")
    for field, value in data.items():
        setattr(clinic, field, value.strip() if isinstance(value, str) else value)
    clinic.save()
    return _serialize_clinic(clinic)


# ── Business hours ───────────────────────────────────────────────────────


def _serialize_hours(clinic: Clinic) -> list[BusinessHourOut]:
    existing = {
        row.day_of_week: row
        for row in ClinicBusinessHours.objects.filter(clinic=clinic)
    }
    out = []
    for day in _DAYS:
        row = existing.get(day)
        if row is None:
            out.append(BusinessHourOut(day_of_week=day, is_closed=False))
        else:
            out.append(
                BusinessHourOut(
                    day_of_week=day,
                    open_time=row.open_time,
                    close_time=row.close_time,
                    is_closed=row.is_closed,
                )
            )
    return out


@router.get("/me/business-hours", response=list[BusinessHourOut], auth=jwt_auth)
def get_business_hours(request):
    return _serialize_hours(clinic_from(request))


@router.put("/me/business-hours", response=list[BusinessHourOut], auth=jwt_auth)
def update_business_hours(request, payload: list[BusinessHourIn]):
    clinic = clinic_from(request)
    for row in payload:
        if row.day_of_week not in _DAYS:
            raise HttpError(400, "day_of_week must be between 0 (Monday) and 6 (Sunday)")
        ClinicBusinessHours.objects.update_or_create(
            clinic=clinic,
            day_of_week=row.day_of_week,
            defaults={
                "open_time": None if row.is_closed else row.open_time,
                "close_time": None if row.is_closed else row.close_time,
                "is_closed": row.is_closed,
            },
        )
    return _serialize_hours(clinic)


# ── Widget settings (booking basics + branding) ─────────────────────────


def _get_or_create_widget_settings(clinic: Clinic):
    from apps.widget.models import WidgetSettings

    settings, _ = WidgetSettings.objects.get_or_create(
        clinic=clinic, defaults={"configuration": default_widget_configuration()}
    )
    return settings


@router.get("/me/widget-settings", response=WidgetSettingsOut, auth=jwt_auth)
def get_widget_settings(request):
    settings = _get_or_create_widget_settings(clinic_from(request))
    return WidgetSettingsOut(configuration=settings.configuration or {})


@router.patch("/me/widget-settings", response=WidgetSettingsOut, auth=jwt_auth)
def update_widget_settings(request, payload: WidgetSettingsUpdateIn):
    """Shallow-merges each top-level key (widget/booking/ai/feature_flags)
    so callers can patch e.g. just `booking.lead_time_hours` without
    clobbering the rest of the configuration blob."""
    settings = _get_or_create_widget_settings(clinic_from(request))
    config = dict(settings.configuration or {})
    for key, value in (payload.configuration or {}).items():
        if isinstance(value, dict) and isinstance(config.get(key), dict):
            config[key] = {**config[key], **value}
        else:
            config[key] = value
    settings.configuration = config
    settings.save(update_fields=["configuration", "updated_at"])
    return WidgetSettingsOut(configuration=settings.configuration)


# ── Onboarding readiness ─────────────────────────────────────────────────


def _compute_onboarding_status(clinic: Clinic) -> OnboardingStatusOut:
    address = clinic.address or {}
    location_ready = bool(
        (address.get("line1") or "").strip()
        and (address.get("city") or "").strip()
        and (address.get("state") or "").strip()
        and (address.get("postal_code") or "").strip()
        and (address.get("country") or "").strip()
        and clinic.phone.strip()
    )
    clinic_ready = bool(clinic.name.strip() and clinic.clinic_type)

    providers_count = Doctor.objects.filter(
        clinic=clinic, is_deleted=False, is_active=True
    ).count()
    services_count = Service.objects.filter(
        clinic=clinic, is_deleted=False, is_active=True
    ).count()
    specialties_count = Specialty.objects.filter(clinic=clinic, is_deleted=False).count()
    insurance_count = InsurancePlan.objects.filter(clinic=clinic, is_deleted=False).count()

    hours_ready = ClinicBusinessHours.objects.filter(
        clinic=clinic, is_closed=False
    ).exists()
    availability_ready = DoctorSchedule.objects.filter(
        clinic=clinic,
        is_active=True,
        doctor__is_deleted=False,
        doctor__is_active=True,
    ).exists()

    checklist = OnboardingChecklistOut(
        clinic=clinic_ready,
        location=location_ready,
        providers=providers_count > 0,
        services=services_count > 0,
        hours=hours_ready,
        availability=availability_ready,
    )
    ready = all(
        [
            checklist.clinic,
            checklist.location,
            checklist.providers,
            checklist.services,
            checklist.hours,
            checklist.availability,
        ]
    )
    return OnboardingStatusOut(
        ready=ready,
        checklist=checklist,
        counts=OnboardingCountsOut(
            providers=providers_count,
            services=services_count,
            specialties=specialties_count,
            insurance_plans=insurance_count,
        ),
    )


@router.get("/me/onboarding-status", response=OnboardingStatusOut, auth=jwt_auth)
def get_onboarding_status(request):
    return _compute_onboarding_status(clinic_from(request))


_MISSING_MESSAGES = {
    "clinic": "Add your clinic name and type before finishing setup.",
    "location": "Add your clinic's address and phone number before finishing setup.",
    "providers": "Add at least one provider before finishing setup.",
    "services": "Add at least one service before finishing setup.",
    "hours": "Set your clinic's business hours before finishing setup.",
    "availability": "Set availability for at least one provider before finishing setup.",
}


@router.post("/me/onboarding/complete", response=ClinicProfileOut, auth=jwt_auth)
def complete_onboarding(request):
    clinic = clinic_from(request)
    status_out = _compute_onboarding_status(clinic)
    if not status_out.ready:
        checklist = status_out.checklist.dict()
        first_missing = next(key for key, ok in checklist.items() if not ok)
        raise HttpError(400, _MISSING_MESSAGES[first_missing])

    clinic.status = ClinicStatus.ACTIVE
    clinic.onboarding_completed_at = timezone.now()
    clinic.onboarding_step = "review"
    clinic.save(
        update_fields=["status", "onboarding_completed_at", "onboarding_step", "updated_at"]
    )
    return _serialize_clinic(clinic)
