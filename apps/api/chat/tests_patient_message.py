"""Patient-facing POST /chat/message — origin allowlist coverage.

The guest-chat half of the widget flow (/widget/chat/guest) is anonymous
and resolves its clinic fresh on every call via resolve_public_clinic,
which enforces Clinic.allowed_origins directly. This endpoint is
different: it's reached only after /widget/otp/verify has already issued a
patient JWT, and the clinic comes from that JWT's clinic_id claim, not a
per-request slug. A leaked or replayed patient token should still be
unusable from a website the clinic hasn't registered — see
apps.api.auth.deps.origin_allowed_for_clinic, called directly here for
defense-in-depth."""

from __future__ import annotations

from django.test import TestCase

from apps.api.auth.jwt import create_patient_access_token
from apps.clinics.models import Clinic
from apps.patients.models import Patient

MESSAGE_URL = "/api/v1/chat/message"


def _make_clinic(slug: str, allowed_origins: list[str] | None = None) -> Clinic:
    return Clinic.objects.create(
        slug=slug,
        name=f"{slug} Clinic",
        email=f"{slug}@test.com",
        phone="+12125550000",
        timezone="America/Los_Angeles",
        allowed_origins=allowed_origins or [],
    )


def _make_patient_token(clinic: Clinic) -> str:
    patient = Patient.objects.create(
        clinic=clinic, phone="+12125550100", first_name="Pat", last_name="Ient",
        is_verified=True,
    )
    return create_patient_access_token(patient_id=patient.id, clinic_id=clinic.id)


class PatientChatMessageOriginTests(TestCase):
    def test_disallowed_origin_is_rejected(self):
        clinic = _make_clinic("patient-msg-rejected", ["https://the-real-site.example.com"])
        token = _make_patient_token(clinic)

        resp = self.client.post(
            MESSAGE_URL,
            data={"message": "hello"},
            content_type="application/json",
            headers={
                "Authorization": f"Bearer {token}",
                "Origin": "https://evil.example.com",
            },
        )
        self.assertEqual(resp.status_code, 403)

    def test_registered_origin_is_allowed(self):
        clinic = _make_clinic("patient-msg-allowed", ["https://the-real-site.example.com"])
        token = _make_patient_token(clinic)

        resp = self.client.post(
            MESSAGE_URL,
            data={"message": "hello"},
            content_type="application/json",
            headers={
                "Authorization": f"Bearer {token}",
                "Origin": "https://the-real-site.example.com",
            },
        )
        self.assertEqual(resp.status_code, 200)

    def test_missing_origin_header_is_allowed(self):
        clinic = _make_clinic("patient-msg-no-origin", ["https://the-real-site.example.com"])
        token = _make_patient_token(clinic)

        resp = self.client.post(
            MESSAGE_URL,
            data={"message": "hello"},
            content_type="application/json",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(resp.status_code, 200)
