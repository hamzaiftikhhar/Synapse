"""Local state backing `MockOTPProvider` only.

`TwilioVerifyProvider` needs no local table — Twilio's Verify Service is the
system of record for that provider's state. This model is deliberately not a
`TenantModel`: verification (staff account phone confirmation, sensitive
actions) can happen before a clinic exists, so it isn't clinic-scoped.
"""

from __future__ import annotations

from django.db import models

from core.models import TimestampedModel, UUIDModel


class MockVerificationRecord(UUIDModel, TimestampedModel):
    to = models.CharField(max_length=255, db_index=True)
    channel = models.CharField(max_length=16)
    code_hash = models.CharField(max_length=64)
    attempts = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField()
    expires_at = models.DateTimeField()
    verified_at = models.DateTimeField(null=True, blank=True)
    last_sent_at = models.DateTimeField()

    class Meta:
        db_table = "mock_verification_records"
        indexes = [
            models.Index(fields=["to", "channel", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.to} ({self.channel})"
