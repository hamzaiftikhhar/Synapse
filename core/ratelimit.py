"""A small, dependency-free rate limiter for sensitive unauthenticated
endpoints (login, register, forgot-password, OTP send/check).

Backed by Django's default cache (`django.core.cache.cache`) — no Redis/
Celery is configured in this project, and none is introduced here. With the
LocMemCache that's active by default today this correctly protects a single
process; running multiple worker processes/machines in production needs a
shared cache backend (e.g. Redis or memcached) for the counts to be accurate
across workers. That's a deployment configuration change, not a code change
— this module doesn't care which cache backend is behind `cache`.
"""

from __future__ import annotations

from django.core.cache import cache
from ninja.errors import HttpError

_PREFIX = "ratelimit"


def check_rate_limit(scope: str, identifier: str, *, limit: int, window_seconds: int) -> None:
    """Raise HttpError(429) once `identifier` has been seen more than `limit`
    times within `window_seconds` under `scope`. Call once per attempt,
    before doing the sensitive work.

    `identifier` is never included in the raised error message — a 429 body
    must not confirm or deny which value (an email, a phone number) is being
    throttled.
    """
    if not identifier:
        return
    key = f"{_PREFIX}:{scope}:{identifier}"
    try:
        count = cache.incr(key)
    except ValueError:
        # Key doesn't exist yet (first hit in this window, or the backend
        # doesn't support incr on a missing key) — start a fresh window.
        cache.set(key, 1, timeout=window_seconds)
        count = 1
    if count > limit:
        raise HttpError(429, "Too many attempts. Please try again later.")
