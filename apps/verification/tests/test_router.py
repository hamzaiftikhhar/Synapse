"""POST /api/v1/verification/{send,resend,check} — staff-authenticated.

Exercises the real HTTP surface, not the service directly: auth gating,
rate limiting, audit logging, and the phone_verified_at side effect on a
genuine APPROVED outcome.
"""

from __future__ import annotations

from django.core.cache import cache
from django.test import TestCase, override_settings

from apps.accounts.models import AuditAction, AuditLog
from apps.api.test_helpers import make_clinic_admin

SEND_URL = "/api/v1/verification/send"
RESEND_URL = "/api/v1/verification/resend"
CHECK_URL = "/api/v1/verification/check"


@override_settings(DEBUG=True, OTP_PROVIDER="mock")
class VerificationRouterTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.user, self.clinic, self.headers = make_clinic_admin(
            email="owner@verify-router.example.com", clinic_slug="verify-router-clinic"
        )

    def test_send_requires_authentication(self):
        resp = self.client.post(
            SEND_URL, data={"to": "+14155552671", "channel": "sms"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 401)

    def test_send_returns_pending_and_dev_code(self):
        resp = self.client.post(
            SEND_URL, data={"to": "+14155552671", "channel": "sms"},
            content_type="application/json", headers=self.headers,
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["status"], "pending")
        self.assertIsNotNone(body["dev_code"])

    def test_send_writes_audit_log(self):
        self.client.post(
            SEND_URL, data={"to": "+14155552671", "channel": "sms"},
            content_type="application/json", headers=self.headers,
        )
        log = AuditLog.objects.filter(
            actor=self.user, action=AuditAction.PHONE_VERIFY_REQUESTED
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.clinic_id, self.clinic.id)

    def test_full_send_then_check_approves_and_sets_phone_verified_at(self):
        self.user.phone_number = "+14155552671"
        self.user.save(update_fields=["phone_number"])

        sent = self.client.post(
            SEND_URL, data={"to": "+14155552671", "channel": "sms"},
            content_type="application/json", headers=self.headers,
        ).json()

        checked = self.client.post(
            CHECK_URL, data={"to": "+14155552671", "code": sent["dev_code"]},
            content_type="application/json", headers=self.headers,
        )
        self.assertEqual(checked.status_code, 200)
        body = checked.json()
        self.assertEqual(body["status"], "approved")
        self.assertTrue(body["valid"])

        self.user.refresh_from_db()
        self.assertIsNotNone(self.user.phone_verified_at)

        log = AuditLog.objects.filter(
            actor=self.user, action=AuditAction.PHONE_VERIFY_APPROVED
        ).first()
        self.assertIsNotNone(log)
        self.assertTrue(log.metadata.get("self_phone"))

    def test_check_does_not_set_phone_verified_at_for_a_different_number(self):
        """Verifying some other phone number (e.g. a number being newly
        added) must not silently mark the user's *existing* phone as
        verified — only an exact match does."""
        self.user.phone_number = "+14155550000"
        self.user.save(update_fields=["phone_number"])

        sent = self.client.post(
            SEND_URL, data={"to": "+14155552671", "channel": "sms"},
            content_type="application/json", headers=self.headers,
        ).json()
        self.client.post(
            CHECK_URL, data={"to": "+14155552671", "code": sent["dev_code"]},
            content_type="application/json", headers=self.headers,
        )
        self.user.refresh_from_db()
        self.assertIsNone(self.user.phone_verified_at)

    def test_wrong_code_does_not_approve_or_write_failure_audit(self):
        """A wrong code with attempts remaining is routine (PENDING) — not
        worth an audit record on every keystroke."""
        self.client.post(
            SEND_URL, data={"to": "+14155552671", "channel": "sms"},
            content_type="application/json", headers=self.headers,
        )
        resp = self.client.post(
            CHECK_URL, data={"to": "+14155552671", "code": "000000"},
            content_type="application/json", headers=self.headers,
        )
        self.assertEqual(resp.json()["status"], "pending")
        self.assertFalse(
            AuditLog.objects.filter(action=AuditAction.PHONE_VERIFY_FAILED).exists()
        )

    def test_max_attempts_reached_writes_failure_audit(self):
        self.client.post(
            SEND_URL, data={"to": "+14155552671", "channel": "sms"},
            content_type="application/json", headers=self.headers,
        )
        for _ in range(6):
            self.client.post(
                CHECK_URL, data={"to": "+14155552671", "code": "000000"},
                content_type="application/json", headers=self.headers,
            )
        self.assertTrue(
            AuditLog.objects.filter(
                actor=self.user, action=AuditAction.PHONE_VERIFY_FAILED
            ).exists()
        )

    def test_send_is_rate_limited_per_recipient(self):
        for _ in range(5):
            resp = self.client.post(
                SEND_URL, data={"to": "+14155559999", "channel": "sms"},
                content_type="application/json", headers=self.headers,
            )
            self.assertEqual(resp.status_code, 200)
        resp = self.client.post(
            SEND_URL, data={"to": "+14155559999", "channel": "sms"},
            content_type="application/json", headers=self.headers,
        )
        self.assertEqual(resp.status_code, 429)

    def test_invalid_recipient_returns_200_with_invalid_status_not_a_500(self):
        resp = self.client.post(
            SEND_URL, data={"to": "garbage", "channel": "sms"},
            content_type="application/json", headers=self.headers,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "invalid_recipient")

    def test_cross_tenant_actor_scoping_on_audit_log(self):
        """The audit row's clinic must be the caller's own tenant, never
        something the request body could influence — `to` is a phone number,
        not a clinic identifier."""
        other_user, other_clinic, other_headers = make_clinic_admin(
            email="owner2@verify-router.example.com", clinic_slug="verify-router-clinic-2"
        )
        self.client.post(
            SEND_URL, data={"to": "+14155551234", "channel": "sms"},
            content_type="application/json", headers=other_headers,
        )
        log = AuditLog.objects.filter(actor=other_user).first()
        self.assertEqual(log.clinic_id, other_clinic.id)
        self.assertNotEqual(log.clinic_id, self.clinic.id)
