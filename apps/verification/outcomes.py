"""Provider-independent result vocabulary for verification attempts.

Both providers translate whatever their backend actually says into this one
set of statuses, so callers of `VerificationService` never branch on which
provider is active.

The vocabulary mirrors Twilio Verify's own status values (pending, approved,
canceled, max_attempts_reached, expired, failed) plus two outcomes Twilio
itself can't distinguish once a verification SID is deleted (on approval,
expiry, or max attempts alike — Twilio's docs are explicit about this):
`ALREADY_VERIFIED` and `NOT_FOUND`. `MockOTPProvider` can report these
precisely because it keeps its own state; `TwilioVerifyProvider` reports
`NOT_FOUND` for all three post-deletion cases rather than guessing which one
actually happened — that's an honest reflection of what Twilio's API can
promise, not a gap in this abstraction.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

# ITU-T E.164: a leading '+', 1-15 digits total, no leading zero after '+'.
_E164_RE = re.compile(r"^\+[1-9]\d{6,14}$")

_PHONE_CHANNELS = {"sms", "call", "whatsapp"}


class VerificationStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    CANCELED = "canceled"
    MAX_ATTEMPTS_REACHED = "max_attempts_reached"
    EXPIRED = "expired"
    FAILED = "failed"
    ALREADY_VERIFIED = "already_verified"
    NOT_FOUND = "not_found"
    INVALID_RECIPIENT = "invalid_recipient"


@dataclass(frozen=True)
class VerificationOutcome:
    """What a send/check/resend call produced. Never carries the real code."""

    status: VerificationStatus
    to: str
    channel: str
    provider: str
    provider_ref: str = ""
    valid: bool = False
    message: str = ""
    # Populated only by MockOTPProvider, and only when settings.DEBUG is True.
    # Twilio never populates this — there is no "development code" concept
    # for a real Verify Service.
    dev_code: str | None = None


class RecipientNormalizationError(ValueError):
    """`to` doesn't look like a valid recipient for the given channel."""


def normalize_recipient(to: str, channel: str) -> str:
    """E.164 for phone-like channels, lowercase+stripped for email.

    Deliberately does not guess a country code for numbers missing a `+` —
    silently assuming one has produced real bugs elsewhere in this codebase
    (an NLU date parser guessing the wrong year). Upstream (an international
    phone input component) is expected to produce E.164; this only validates
    the shape and normalizes formatting noise (spaces/dashes/parens).
    """
    raw = (to or "").strip()
    if not raw:
        raise RecipientNormalizationError("A recipient is required.")

    if channel in _PHONE_CHANNELS:
        cleaned = re.sub(r"[\s\-().]", "", raw)
        if not _E164_RE.match(cleaned):
            raise RecipientNormalizationError(
                f"'{to}' is not a valid E.164 phone number (expected e.g. +14155552671)."
            )
        return cleaned

    if channel == "email":
        cleaned = raw.lower()
        if "@" not in cleaned or cleaned.startswith("@") or cleaned.endswith("@"):
            raise RecipientNormalizationError(f"'{to}' is not a valid email address.")
        return cleaned

    raise RecipientNormalizationError(f"Unsupported channel '{channel}'.")
