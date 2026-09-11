"""Patient phone normalization — E.164, no guessing.

Mirrors apps/verification/outcomes.py::normalize_recipient's explicit
policy: strip formatting noise (spaces/dashes/parens) and validate the
E.164 shape, but never guess a missing country code. That codebase already
has one incident from a "helpful" guess going wrong elsewhere (an NLU date
parser assuming a year) — the fix here is the same one used there: push
country selection to the caller (the frontend's country-code picker), and
have this function reject anything ambiguous rather than silently
defaulting it.
"""

from __future__ import annotations

import re

_E164_RE = re.compile(r"^\+[1-9]\d{6,14}$")


class InvalidPhoneNumber(ValueError):
    """`raw` doesn't look like a valid E.164 phone number."""


def is_placeholder_phone(phone: str) -> bool:
    """True for the internal "email:<hash>" stand-in
    (patient_service.email_placeholder_phone) written to Patient.phone for
    an email-only registrant, so the field's required/unique constraint is
    satisfiable without a real number. Callers that display or return
    Patient.phone to a user must check this first — never surface the
    stand-in as if it were a real phone number."""
    return phone.startswith("email:")


def display_phone(phone: str) -> str:
    """Patient.phone, or "" if it's the internal email-only placeholder."""
    return "" if is_placeholder_phone(phone) else phone


def normalize_phone_e164(raw: str) -> str:
    """Strip formatting noise and validate E.164 shape.

    Raises InvalidPhoneNumber if `raw` has no country code (no leading
    `+`) or otherwise doesn't match E.164 — never assumes one.
    """
    cleaned = re.sub(r"[\s\-().]", "", (raw or "").strip())
    if not _E164_RE.match(cleaned):
        raise InvalidPhoneNumber(
            f"'{raw}' is not a valid E.164 phone number (expected e.g. +14155552671)."
        )
    return cleaned
