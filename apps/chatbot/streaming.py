"""Streaming design stub for vector_rag replies (Phase 3).

Not wired to the HTTP API yet. Hard request budgets remain mandatory even
when streaming is enabled — streaming improves perceived latency, not wall-clock
guarantees.

Intended shape:
  1. ChatEngine yields tokens from OpenAI/Gemini stream APIs
  2. API endpoint uses StreamingHttpResponse / SSE
  3. Frontend appends tokens to the bot bubble

Enable later via CHAT_RESPONSE_STREAMING=true after Phase 1 budgets are proven.
"""

from __future__ import annotations

from django.conf import settings


def streaming_enabled() -> bool:
    return bool(getattr(settings, "CHAT_RESPONSE_STREAMING", False))
