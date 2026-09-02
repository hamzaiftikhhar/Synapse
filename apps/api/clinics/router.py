"""Clinic profile, business hours, widget settings, and onboarding progress.

Onboarding has no dedicated model — it derives from `Clinic.status` /
`Clinic.onboarding_step` plus the real Doctor/Service/Specialty/InsurancePlan/
ClinicBusinessHours/DoctorSchedule rows already owned by the clinic.
"""

from __future__ import annotations

import re

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
# Not tied to the frontend's specific step slugs (that list can grow without
# a backend release) — just a defensive shape check so a bad/rogue value
# can't overflow the column and 500 instead of a clean 400.
_ONBOARDING_STEP_RE = re.compile(r"^[a-z_]{1,32}$")
# scheme + host[:port] only — no path/query/fragment/trailing slash. Matches
# what a browser's Origin header actually looks like, so a stored entry
# compares equal to it directly (apps.api.auth.deps.origin_allowed_for_clinic).
_ORIGIN_RE = re.compile(r"^https?://[^/\s]+$")
_MAX_ALLOWED_ORIGINS = 10


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
        allowed_origins=clinic.allowed_origins or [],
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
    if "onboarding_step" in data and data["onboarding_step"]:
        if not _ONBOARDING_STEP_RE.match(data["onboarding_step"]):
            raise HttpError(400, "Invalid onboarding step")
    if data.get("allowed_origins") is not None:
        cleaned: list[str] = []
        for raw in data["allowed_origins"]:
            origin = (raw or "").strip().rstrip("/").lower()
            if not _ORIGIN_RE.match(origin):
                raise HttpError(
                    400,
                    f"'{raw}' is not a valid origin — use e.g. https://example.com "
                    "(no path, query, or trailing slash)",
                )
            if origin not in cleaned:
                cleaned.append(origin)
        if len(cleaned) > _MAX_ALLOWED_ORIGINS:
            raise HttpError(400, f"At most {_MAX_ALLOWED_ORIGINS} allowed origins per clinic")
        data["allowed_origins"] = cleaned
    for field, value in data.items():
        setattr(clinic, field, value.strip() if isinstance(value, str) else value)
    clinic.save()
    return _serialize_clinic(clinic)


# ── Business hours ───────────────────────────────────────────────────────


def _serialize_hours(clinic: Clinic) -> list[BusinessHourOut]:
    rows = ClinicBusinessHours.objects.filter(clinic=clinic).order_by(
        "day_of_week", "open_time"
    )
    return [
        BusinessHourOut(
            id=row.id,
            day_of_week=row.day_of_week,
            open_time=row.open_time,
            close_time=row.close_time,
            is_closed=row.is_closed,
        )
        for row in rows
    ]


@router.get("/me/business-hours", response=list[BusinessHourOut], auth=jwt_auth)
def get_business_hours(request):
    return _serialize_hours(clinic_from(request))


def _validate_business_hours(payload: list[BusinessHourIn]) -> None:
    """Same validation shape as apps/api/doctors/router.py's schedule
    endpoint (end-after-start), plus the constraints unique to business
    hours now that multiple intervals per day are allowed."""
    by_day: dict[int, list[BusinessHourIn]] = {}
    for row in payload:
        if row.day_of_week not in _DAYS:
            raise HttpError(400, "day_of_week must be between 0 (Monday) and 6 (Sunday)")
        by_day.setdefault(row.day_of_week, []).append(row)

    for day, rows in by_day.items():
        closed_rows = [r for r in rows if r.is_closed]
        open_rows = [r for r in rows if not r.is_closed]
        if closed_rows and open_rows:
            raise HttpError(400, f"Day {day} cannot be both closed and open")
        if len(closed_rows) > 1:
            raise HttpError(400, f"Day {day} has more than one closed entry")
        for row in open_rows:
            if row.open_time is None or row.close_time is None:
                raise HttpError(400, f"Day {day} is missing an open or close time")
            if row.close_time <= row.open_time:
                raise HttpError(400, "End time must be after start time")
        for i, a in enumerate(open_rows):
            for b in open_rows[i + 1 :]:
                if a.open_time < b.close_time and b.open_time < a.close_time:
                    raise HttpError(400, f"Business hours overlap on day {day}")


@router.put("/me/business-hours", response=list[BusinessHourOut], auth=jwt_auth)
def update_business_hours(request, payload: list[BusinessHourIn]):
    """Bulk replace — same delete+recreate pattern as
    apps/api/doctors/router.py::update_doctor_schedule. Multiple rows per
    day are allowed (e.g. a morning shift + an afternoon shift)."""
    clinic = clinic_from(request)
    _validate_business_hours(payload)

    ClinicBusinessHours.objects.filter(clinic=clinic).delete()
    ClinicBusinessHours.objects.bulk_create(
        [
            ClinicBusinessHours(
                clinic=clinic,
                day_of_week=row.day_of_week,
                open_time=None if row.is_closed else row.open_time,
                close_time=None if row.is_closed else row.close_time,
                is_closed=row.is_closed,
            )
            for row in payload
        ]
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

    # A clinic provisioned from a paid application (apps/api/platform/router.py
    # `approve_application`) already has a Subscription row awaiting payment.
    # The operational checklist passing is not enough to go live for those —
    # activation is gated on a verified Paddle webhook instead (see
    # apps/billing/services/activation.py). Plain self-serve clinics (no
    # Subscription at all) keep the original immediate-activation behavior.
    from apps.billing.models import Subscription

    pending_subscription = Subscription.objects.filter(clinic=clinic).first()
    if pending_subscription is not None and not pending_subscription.has_access:
        clinic.onboarding_step = "billing"
        clinic.save(update_fields=["onboarding_step", "updated_at"])
        return _serialize_clinic(clinic)

    clinic.status = ClinicStatus.ACTIVE
    clinic.onboarding_completed_at = timezone.now()
    clinic.onboarding_step = "review"
    clinic.save(
        update_fields=["status", "onboarding_completed_at", "onboarding_step", "updated_at"]
    )
    return _serialize_clinic(clinic)
