"""Simple in-process circuit breaker for LLM providers.

After N consecutive failures, skip the provider for a cooldown window.
Half-open probe after cooldown; close on success.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

from django.conf import settings

logger = logging.getLogger(__name__)


@dataclass
class _BreakerState:
    failures: int = 0
    open_until: float = 0.0
    last_error: str = ""


_lock = threading.Lock()
_states: dict[str, _BreakerState] = {}


def _threshold() -> int:
    return int(getattr(settings, "LLM_CIRCUIT_FAILURE_THRESHOLD", 5))


def _cooldown() -> float:
    return float(getattr(settings, "LLM_CIRCUIT_COOLDOWN_SECONDS", 600.0))


def _state(name: str) -> _BreakerState:
    if name not in _states:
        _states[name] = _BreakerState()
    return _states[name]


def is_available(provider: str) -> bool:
    """True if calls to this provider should be attempted."""
    with _lock:
        st = _state(provider)
        now = time.monotonic()
        if st.open_until <= now:
            return True
        return False


def record_success(provider: str) -> None:
    with _lock:
        st = _state(provider)
        st.failures = 0
        st.open_until = 0.0
        st.last_error = ""


def record_failure(provider: str, error: str = "") -> None:
    with _lock:
        st = _state(provider)
        st.failures += 1
        st.last_error = (error or "")[:300]
        if st.failures >= _threshold():
            st.open_until = time.monotonic() + _cooldown()
            logger.warning(
                "circuit_open provider=%s failures=%s cooldown_s=%s last=%s",
                provider,
                st.failures,
                _cooldown(),
                st.last_error,
            )


def status(provider: str) -> dict[str, object]:
    with _lock:
        st = _state(provider)
        now = time.monotonic()
        return {
            "provider": provider,
            "failures": st.failures,
            "open": st.open_until > now,
            "open_for_s": max(0.0, round(st.open_until - now, 1)),
            "last_error": st.last_error,
        }


def reset(provider: str | None = None) -> None:
    """Test helper — clear breaker state."""
    with _lock:
        if provider is None:
            _states.clear()
        else:
            _states.pop(provider, None)
