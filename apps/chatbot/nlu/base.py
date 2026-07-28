"""NLU provider protocol and errors."""

from __future__ import annotations

from typing import Any, Protocol


class NLUError(Exception):
    """Raised when intent/entity classification fails."""


class NLUProvider(Protocol):
    """Swappable LLM backend selected via NLU_PROVIDER."""

    provider_name: str
    model_name: str

    def classify(
        self,
        *,
        message: str,
        conversation_context: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """
        Return raw structured JSON matching the NLU schema.

        Must include intent, entities, routing flags, and confidence.
        """
