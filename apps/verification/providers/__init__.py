from apps.verification.providers.base import OTPProvider
from apps.verification.providers.mock import MockOTPProvider
from apps.verification.providers.twilio_verify import TwilioVerifyProvider

__all__ = ["OTPProvider", "MockOTPProvider", "TwilioVerifyProvider", "get_provider"]

_PROVIDERS: dict[str, type[OTPProvider]] = {
    "mock": MockOTPProvider,
    "twilio": TwilioVerifyProvider,
}


def get_provider(name: str | None = None) -> OTPProvider:
    """Resolve the active OTPProvider from `OTP_PROVIDER` (or an explicit override).

    This is the only place that knows both provider names — callers (and
    VerificationService) never branch on which one is active.
    """
    from django.conf import settings
    from django.core.exceptions import ImproperlyConfigured

    key = (name or getattr(settings, "OTP_PROVIDER", "mock") or "mock").strip().lower()
    provider_cls = _PROVIDERS.get(key)
    if provider_cls is None:
        raise ImproperlyConfigured(
            f"Unknown OTP_PROVIDER '{key}' — expected one of {sorted(_PROVIDERS)}"
        )
    return provider_cls()
