"""Deterministic per-row extraction — turns one raw spreadsheet row plus a
confirmed column mapping into canonical_data + validation_errors.

Runs once per mapping confirmation (initial upload, or after a manual
PATCH .../mapping fix) — never per row via the LLM. The mapping's
confidence is a property of the *column*; every value from that column
inherits it verbatim.
"""

from __future__ import annotations

import re
from typing import Any

from apps.importer.models import ImportRecordStatus
from apps.importer.target_schemas import required_fields_for, target_fields_for


def apply_field_defaults(canonical: dict, record_type: str) -> dict:
    """Fill catalog defaults (e.g. blank service duration → 30) before review.

    Missing optional values stay missing unless the field declares a default.
    Applied here so the review UI shows what will actually be committed.
    """
    for field, spec in target_fields_for(record_type).items():
        if "default" not in spec:
            continue
        entry = canonical.get(field)
        if entry is not None and entry.get("value") not in (None, ""):
            continue
        canonical[field] = {
            "source": (entry or {}).get("source") or "",
            "value": spec["default"],
            "confidence": 1.0,
            "reason": f"Blank {field} defaults to {spec['default']}.",
        }
    return canonical


def _coerce(raw: str, field_type: str) -> tuple[Any, str | None]:
    raw = (raw or "").strip()
    if field_type == "string":
        return raw, None
    if field_type == "string_list":
        if not raw:
            return [], None
        return [part.strip() for part in raw.split(",") if part.strip()], None
    if field_type == "integer":
        if not raw:
            return None, None
        cleaned = re.sub(r"[^\d.\-]", "", raw)
        try:
            return int(round(float(cleaned))), None
        except ValueError:
            return None, f"Could not read '{raw}' as a number."
    if field_type == "money_cents":
        if not raw:
            return None, None
        cleaned = re.sub(r"[^\d.]", "", raw)
        try:
            return round(float(cleaned) * 100), None
        except ValueError:
            return None, f"Could not read '{raw}' as a price."
    return raw, None  # pragma: no cover — exhaustive over target_schemas types


def extract_record(
    row: dict[str, str], mapping: dict[str, dict], record_type: str
) -> tuple[dict, list[dict]]:
    target_fields = target_fields_for(record_type)
    canonical: dict[str, dict] = {}
    errors: list[dict] = []

    for header, raw_value in row.items():
        info = mapping.get(header) or {}
        target = info.get("target")
        if not target or target not in target_fields:
            continue  # unmapped/unknown column — stays visible in raw_data only
        spec = target_fields[target]
        coerced, error = _coerce(raw_value, str(spec["type"]))
        if error:
            errors.append({"field": target, "message": error})
            continue
        canonical[target] = {
            "source": header,
            "value": coerced,
            "confidence": info.get("confidence", 0.0),
            "reason": info.get("reason", ""),
        }

    apply_field_defaults(canonical, record_type)

    for field in required_fields_for(record_type):
        entry = canonical.get(field)
        if entry is None or entry["value"] in (None, "", []):
            errors.append({"field": field, "message": f"'{field}' is required but is missing."})

    return canonical, errors


def finalize_status(
    *,
    canonical_data: dict,
    validation_errors: list[dict],
    duplicate_match: dict | None,
    confidence_threshold: float,
) -> str:
    """Priority: validation errors > low confidence > duplicate > ready.
    A record below threshold or with a duplicate match keeps its data —
    it's never silently dropped, just routed for human attention."""
    if validation_errors:
        return ImportRecordStatus.NEEDS_REVIEW
    if any(entry["confidence"] < confidence_threshold for entry in canonical_data.values()):
        return ImportRecordStatus.NEEDS_REVIEW
    if duplicate_match is not None:
        return ImportRecordStatus.DUPLICATE
    return ImportRecordStatus.READY
