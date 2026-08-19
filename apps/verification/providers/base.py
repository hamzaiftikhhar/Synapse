"""The abstraction every provider implements — send / check / resend only.

Nothing outside a provider's own module may import Twilio, or reach into
provider-specific state. `VerificationService` (apps/verification/service.py)
depends only on this interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from apps.verification.outcomes import VerificationOutcome


class OTPProvider(ABC):
    name: str

    @abstractmethod
    def send_verification(self, *, to: str, channel: str = "sms") -> VerificationOutcome:
        """Start a new verification, or continue an existing pending one."""

    @abstractmethod
    def check_verification(self, *, to: str, code: str) -> VerificationOutcome:
        """Check a code the user submitted."""

    @abstractmethod
    def resend_verification(self, *, to: str, channel: str = "sms") -> VerificationOutcome:
        """Ask for another code for an already-started verification."""
