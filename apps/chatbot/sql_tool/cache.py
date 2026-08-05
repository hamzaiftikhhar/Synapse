"""Short-TTL cache for stable clinic SQL facts (hours, doctors, insurance, services)."""

from __future__ import annotations

import logging
from typing import Any

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

_CACHEABLE = frozenset(
    {"hours", "location", "insurance", "doctors", "specialties", "services", "pricing"}
)


def cache_key(clinic_id: Any, task: str) -> str:
    return f"clinic_fact:{clinic_id}:{task}"


def get_cached_result(clinic_id: Any, task: str) -> list[dict[str, Any]] | None:
    if task not in _CACHEABLE:
        return None
    try:
        hit = cache.get(cache_key(clinic_id, task))
        if isinstance(hit, list):
            return hit
    except Exception:
        logger.debug("clinic fact cache get failed", exc_info=True)
    return None


def set_cached_result(clinic_id: Any, task: str, rows: list[dict[str, Any]]) -> None:
    if task not in _CACHEABLE:
        return
    ttl = int(getattr(settings, "CLINIC_FACT_CACHE_TTL_SECONDS", 600))
    try:
        cache.set(cache_key(clinic_id, task), rows, timeout=ttl)
    except Exception:
        logger.debug("clinic fact cache set failed", exc_info=True)
