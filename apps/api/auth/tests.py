"""Self-serve clinic creation — POST /api/v1/auth/clinics."""

from __future__ import annotations

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.models import ClinicStaff
from apps.api.test_helpers import make_verified_owner
from apps.clinics.models import Clinic, ClinicStatus

User = get_user_model()


class CreateClinicAtomicityTests(TestCase):
    """Regression for the production "Umbrella Health" / "Umbrell Health"
    duplicate-clinic incident: create_clinic used to call write_audit()
    *after* its `with transaction.atomic():` block had already closed, so a
    failure there raised once the clinic/staff/widget rows were already
    committed. The client saw a failed request and retried with a tweaked
    slug, and the first clinic was never rolled back — leaving two
    independent clinics owned by the same account. The fix moves write_audit
    inside the same transaction; verify a failure there now leaves nothing
    behind at all, so a retry is actually safe.
    """

    def setUp(self):
        self.user, self.headers = make_verified_owner(email="owner@duprisk.example.com")

    def test_failure_after_clinic_row_rolls_back_everything(self):
        with patch("apps.api.auth.router.write_audit", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self.client.post(
                    "/api/v1/auth/clinics",
                    data={"name": "Duplicate Risk Clinic", "slug": "duplicate-risk-clinic"},
                    content_type="application/json",
                    headers=self.headers,
                )

        self.assertFalse(Clinic.objects.filter(slug="duplicate-risk-clinic").exists())
        self.assertFalse(ClinicStaff.objects.filter(user=self.user).exists())

    def test_success_still_creates_clinic_and_audit_row(self):
        resp = self.client.post(
            "/api/v1/auth/clinics",
            data={"name": "Real Clinic", "slug": "real-clinic"},
            content_type="application/json",
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(Clinic.objects.filter(slug="real-clinic").exists())

        from apps.accounts.models import AuditAction, AuditLog

        clinic = Clinic.objects.get(slug="real-clinic")
        self.assertTrue(
            AuditLog.objects.filter(
                action=AuditAction.CLINIC_CREATE, clinic=clinic
            ).exists()
        )


class CreateClinicOnePerAccountTests(TestCase):
    """A user who already belongs to a clinic can't spin up another one
    through the self-serve endpoint — this is the policy half of the
    duplicate-clinic fix: even without a post-commit failure to trigger a
    confused retry, nothing previously stopped one account from creating
    unlimited independent clinics.

    Uses make_verified_owner (a tenant-less token, like a user mid-signup
    would actually have) plus a manually attached ClinicStaff row, rather
    than make_clinic_admin — that helper bakes the clinic into the token
    itself, and StaffJWTAuth 401s a tenant-scoped token whose membership
    row is no longer active, which would test the auth layer instead of
    the guard this is actually about.
    """

    def test_existing_member_is_rejected(self):
        user, headers = make_verified_owner(email="already-owns-one@example.com")
        existing_clinic = Clinic.objects.create(
            slug="already-owns-one", name="Already Owns One", email=user.email,
            status=ClinicStatus.ONBOARDING,
        )
        ClinicStaff.objects.create(user=user, clinic=existing_clinic, is_active=True)

        resp = self.client.post(
            "/api/v1/auth/clinics",
            data={"name": "Second Clinic Attempt", "slug": "second-clinic-attempt"},
            content_type="application/json",
            headers=headers,
        )
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(Clinic.objects.filter(slug="second-clinic-attempt").exists())

    def test_inactive_membership_does_not_block(self):
        user, headers = make_verified_owner(email="left-a-clinic@example.com")
        former_clinic = Clinic.objects.create(
            slug="left-a-clinic", name="Left A Clinic", email=user.email,
            status=ClinicStatus.SUSPENDED,
        )
        ClinicStaff.objects.create(user=user, clinic=former_clinic, is_active=False)

        resp = self.client.post(
            "/api/v1/auth/clinics",
            data={"name": "Fresh Start Clinic", "slug": "fresh-start-clinic"},
            content_type="application/json",
            headers=headers,
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertTrue(Clinic.objects.filter(slug="fresh-start-clinic").exists())
