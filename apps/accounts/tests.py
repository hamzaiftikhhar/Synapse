"""Owner invite acceptance — POST /auth/accept-invite."""

from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import ClinicStaff, StaffAuthToken, StaffAuthTokenPurpose, UserRole
from apps.clinics.models import Clinic, ClinicStatus

User = get_user_model()
URL = "/api/v1/auth/accept-invite"


class AcceptInviteTests(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="invited-clinic", name="Invited Clinic", email="owner@invited.example.com",
            status=ClinicStatus.ONBOARDING,
        )
        self.owner = User.objects.create_user(
            username="invitedowner", email="owner@invited.example.com",
            role=UserRole.CLINIC_ADMIN, is_clinic_owner=True, is_active=False,
        )
        ClinicStaff.objects.create(user=self.owner, clinic=self.clinic, is_active=True)
        self.row, self.raw_token = StaffAuthToken.issue(
            user=self.owner, purpose=StaffAuthTokenPurpose.INVITE, ttl_hours=24 * 7
        )

    def test_valid_invite_activates_and_logs_in_scoped_to_clinic(self):
        resp = self.client.post(
            URL, data={"token": self.raw_token, "password": "BrandNewPass1!"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["clinic"]["slug"], self.clinic.slug)
        self.assertTrue(body["access_token"])

        self.owner.refresh_from_db()
        self.assertTrue(self.owner.is_active)
        self.assertTrue(self.owner.check_password("BrandNewPass1!"))
        self.assertIsNotNone(self.owner.email_verified_at)

        self.row.refresh_from_db()
        self.assertIsNotNone(self.row.used_at)

    def test_token_is_one_time_use(self):
        self.client.post(
            URL, data={"token": self.raw_token, "password": "BrandNewPass1!"},
            content_type="application/json",
        )
        resp = self.client.post(
            URL, data={"token": self.raw_token, "password": "AnotherPass2!"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_expired_token_rejected(self):
        self.row.expires_at = timezone.now() - timedelta(hours=1)
        self.row.save(update_fields=["expires_at"])
        resp = self.client.post(
            URL, data={"token": self.raw_token, "password": "BrandNewPass1!"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
        self.owner.refresh_from_db()
        self.assertFalse(self.owner.is_active)

    def test_wrong_purpose_token_rejected(self):
        _, raw = StaffAuthToken.issue(
            user=self.owner, purpose=StaffAuthTokenPurpose.PASSWORD_RESET, ttl_hours=2
        )
        resp = self.client.post(
            URL, data={"token": raw, "password": "BrandNewPass1!"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_garbage_token_rejected(self):
        resp = self.client.post(
            URL, data={"token": "not-a-real-token", "password": "BrandNewPass1!"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_weak_password_rejected(self):
        resp = self.client.post(
            URL, data={"token": self.raw_token, "password": "short"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
        self.owner.refresh_from_db()
        self.assertFalse(self.owner.is_active)

    def test_invited_owner_cannot_see_another_clinics_data_via_token(self):
        """The invite only ever resolves through this owner's own ClinicStaff
        row — there is no field in the request an attacker could supply to
        redirect the session to a different clinic."""
        other_clinic = Clinic.objects.create(
            slug="other-clinic", name="Other Clinic", email="x@other.example.com",
        )
        ClinicStaff.objects.create(user=self.owner, clinic=other_clinic, is_active=False)

        resp = self.client.post(
            URL, data={"token": self.raw_token, "password": "BrandNewPass1!"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        # Only the active membership (the real invited clinic) is honored.
        self.assertEqual(resp.json()["clinic"]["slug"], self.clinic.slug)
