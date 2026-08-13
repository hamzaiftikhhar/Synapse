"""Synonym-table fallback column mapper.

Used whenever the LLM mapper is unavailable, times out, or returns
something we can't trust (apps/importer/services/mapper.py). Deliberately
conservative: an unmatched header maps to nothing rather than a guess.
"""

import re

from apps.importer.target_schemas import target_fields_for

_SYNONYMS: dict[str, set[str]] = {
    "full_name": {
        "name", "full name", "doctor", "provider", "physician",
        "physician name", "employee", "employee name", "provider name",
        "doctor name", "staff name", "practitioner",
    },
    "title": {"title", "role", "position", "credentials", "designation"},
    "bio": {"bio", "biography", "about", "description"},
    "languages": {"languages", "language", "languages spoken"},
    "name": {
        "name", "service", "service name", "treatment", "procedure",
        "specialty", "specialty name",
    },
    "description": {"description", "details", "notes", "about"},
    "category": {"category", "dept", "department", "type", "group"},
    "duration_min": {
        "duration", "duration (min)", "duration_min", "minutes",
        "appointment length", "time", "length",
    },
    "price_cents": {
        "price", "fee", "cost", "cash price", "rate", "amount", "price ($)",
    },
    "provider_name": {
        "name", "insurance", "insurance name", "payer", "payer name", "carrier",
        "company", "insurer", "provider", "provider name",
    },
    "plan_name": {"plan", "plan name", "product", "product name"},
    "plan_type": {
        "network", "type", "plan type", "network type", "network/type",
        "network / type",
    },
}


def _normalize(header: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", header.strip().lower())).strip()


# Normalized once at import time (same _normalize as headers go through) so
# "Duration (min)" and "duration_min" both collapse to "duration min" and
# compare equal — comparing raw synonym literals against a normalized
# header silently never matches.
_NORMALIZED_SYNONYMS: dict[str, set[str]] = {
    target: {_normalize(s) for s in synonyms} for target, synonyms in _SYNONYMS.items()
}


def heuristic_map_columns(record_type: str, headers: list[str]) -> dict[str, dict]:
    """Best-effort header -> target mapping using a synonym table. Never
    maps two source headers to the same target — first match wins, later
    duplicates are left unmapped for the human to resolve."""
    allowed_targets = set(target_fields_for(record_type).keys())
    used_targets: set[str] = set()
    mapping: dict[str, dict] = {}

    for header in headers:
        normalized = _normalize(header)
        matched_target = None
        for target in allowed_targets:
            if target in used_targets:
                continue
            synonyms = _NORMALIZED_SYNONYMS.get(target, {_normalize(target)})
            if normalized in synonyms:
                matched_target = target
                break
        if matched_target:
            used_targets.add(matched_target)
            mapping[header] = {
                "target": matched_target,
                "confidence": 0.6,
                "reason": "Matched by common column-name pattern.",
            }
        else:
            mapping[header] = {
                "target": None,
                "confidence": 0.0,
                "reason": "Automatic mapping unavailable — please map manually.",
            }
    return mapping
