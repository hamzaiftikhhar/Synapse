"""Factory for the configured NLU provider."""

from __future__ import annotations

from django.conf import settings

from apps.chatbot.nlu.base import NLUError, NLUProvider
from apps.chatbot.nlu.gemini_provider import GeminiNLUProvider
from apps.chatbot.nlu.openai_provider import OpenAINLUProvider

_provider: NLUProvider | None = None


def get_nlu_provider() -> NLUProvider:
    """Return a cached NLU provider from settings."""
    global _provider
    if _provider is None:
        _provider = _build_provider()
    return _provider


def reset_nlu_provider() -> None:
    """Clear cached provider — for tests only."""
    global _provider
    _provider = None


def _build_provider() -> NLUProvider:
    name = str(settings.NLU_PROVIDER).lower().strip()
    model = settings.NLU_MODEL

    if name == "gemini":
        return GeminiNLUProvider(
            model_name=model,
            api_key=settings.GOOGLE_API_KEY,
        )
    if name == "openai":
        return OpenAINLUProvider(
            model_name=model,
            api_key=settings.OPENAI_API_KEY,
        )
    raise NLUError(f"Unknown NLU_PROVIDER: {settings.NLU_PROVIDER!r}")
