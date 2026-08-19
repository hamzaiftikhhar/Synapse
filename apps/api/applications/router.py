"""Public clinic application intake ("Get Started") — no auth.

This is the pre-tenant entry point of the acquisition flow: Pricing →
Get Started → application → Super Admin review (apps/api/platform/router.py)
→ provisioned Clinic. Submitting an application never creates a Clinic.
"""

from __future__ import annotations

import logging

from ninja import Router
from ninja.errors import HttpError

from apps.api.applications.schemas import ClinicApplicationIn, ClinicApplicationOut
from apps.billing.models import Plan
from apps.clinics.models import (
    ClinicApplication,
    ClinicApplicationSource,
    ClinicApplicationStatus,
)
from apps.notifications.service import NotificationService

logger = logging.getLogger(__name__)
router = Router(tags=["Applications"])

_VALID_SOURCES = {c.value for c in ClinicApplicationSource}


@router.post("", response=ClinicApplicationOut, auth=None)
def submit_application(request, payload: ClinicApplicationIn):
    clinic_name = (payload.clinic_name or "").strip()
    owner_name = (payload.owner_name or "").strip()
    work_email = (payload.work_email or "").strip().lower()
    plan_slug = (payload.plan_slug or "").strip()
    source = (payload.source or "").strip().lower()
    if source not in _VALID_SOURCES:
        source = ClinicApplicationSource.GET_STARTED

    if not clinic_name:
        raise HttpError(400, "Clinic name is required")
    if not owner_name:
        raise HttpError(400, "Owner name is required")
    if not work_email or "@" not in work_email:
        raise HttpError(400, "A valid work email is required")
    # A demo request doesn't ask the visitor to commit to a plan — Super
    # Admin picks one at approval time (see approve_application). Every
    # other source still requires a real, currently-sellable plan.
    if source != ClinicApplicationSource.DEMO_REQUEST:
        if not Plan.objects.filter(slug=plan_slug, is_active=True).exists():
            raise HttpError(400, "Selected plan is not available")
    else:
        plan_slug = ""

    # Resubmission from the same email while still pending updates the
    # existing application rather than piling up duplicates.
    application = ClinicApplication.objects.filter(
        work_email=work_email, status=ClinicApplicationStatus.PENDING
    ).first()

    fields = dict(
        clinic_name=clinic_name,
        owner_name=owner_name,
        phone=(payload.phone or "").strip(),
        website=(payload.website or "").strip(),
        num_doctors=payload.num_doctors,
        current_scheduling_system=(payload.current_scheduling_system or "").strip(),
        plan_slug=plan_slug,
        notes=(payload.notes or "").strip(),
        source=source,
    )

    if application is not None:
        for key, value in fields.items():
            setattr(application, key, value)
        application.save(update_fields=[*fields.keys(), "updated_at"])
    else:
        application = ClinicApplication.objects.create(work_email=work_email, **fields)
        logger.info(
            "demo_request_created application=%s source=%s", application.id, source
        )
        if source == ClinicApplicationSource.DEMO_REQUEST:
            NotificationService.send_demo_request_received_email(
                to=work_email, clinic_name=clinic_name
            )
        else:
            NotificationService.send_application_received_email(
                to=work_email, clinic_name=clinic_name
            )
        NotificationService.send_demo_request_notification_email(
            application_id=str(application.id),
            clinic_name=clinic_name,
            requester_name=owner_name,
            work_email=work_email,
            phone=fields["phone"],
            source=source,
        )

    return ClinicApplicationOut(
        id=application.id, status=application.status, created_at=application.created_at
    )
