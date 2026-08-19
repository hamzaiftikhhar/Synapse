from __future__ import annotations

from ninja import Schema


class VerificationSendIn(Schema):
    to: str
    channel: str = "sms"


class VerificationCheckIn(Schema):
    to: str
    code: str


class VerificationOutcomeOut(Schema):
    status: str
    valid: bool = False
    message: str = ""
    # Populated only when settings.DEBUG is True and the mock provider is
    # active — enforced in apps.verification, not here.
    dev_code: str | None = None
