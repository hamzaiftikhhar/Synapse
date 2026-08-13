"""Column-mapping — maps a spreadsheet's headers onto the canonical target
fields for a record type, via one OpenAI JSON-mode call per job (never per
row). Mirrors apps/chatbot/nlu/openai_provider.py's request pattern.

Any failure (missing key, timeout, malformed JSON, an invented field
outside the catalog) falls back to the always-available heuristic
synonym-table mapper — the import never hard-fails just because the LLM
call didn't work, and the human can still fix any column via
PATCH /import/jobs/{id}/mapping afterward.
"""

from __future__ import annotations

import json
import logging

from django.conf import settings

from apps.chatbot.nlu.deadline import run_with_deadline
from apps.chatbot.nlu.json_utils import parse_json_response
from apps.importer.services.heuristics import heuristic_map_columns
from apps.importer.target_schemas import target_fields_for

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a data-mapping assistant for a medical clinic's \
setup wizard. You will be given a target record type with its allowed \
target fields and types, plus a spreadsheet's column headers and a few \
sample rows.

Map each source column to the single best-matching target field, or null \
if none fits. Do not invent target fields outside the given list. Do not \
guess values — use the sample rows only as evidence of what the column \
represents. Never map two source headers to the same target field; if \
several plausibly fit, pick the best one and set the rest to null with a \
reason.

Respond with strict JSON only, no markdown fences, in this exact shape:
{"mapping": {"<source_header>": {"target": "<field_or_null>", \
"confidence": <0.0-1.0>, "reason": "<short reason>"}}}
Every source header from the input must appear as a key exactly once."""


def _build_user_prompt(record_type: str, headers: list[str], sample_rows: list[dict]) -> str:
    target_fields = target_fields_for(record_type)
    payload = {
        "record_type": record_type,
        "allowed_target_fields": {
            field: spec["type"] for field, spec in target_fields.items()
        },
        "source_columns": headers,
        "sample_rows": sample_rows,
    }
    return json.dumps(payload)


def _call_llm(record_type: str, headers: list[str], sample_rows: list[dict]) -> dict:
    api_key = getattr(settings, "OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")

    from openai import OpenAI

    timeout = float(getattr(settings, "IMPORTER_LLM_TIMEOUT_SECONDS", 8.0))
    client = OpenAI(api_key=api_key, timeout=timeout)
    user_prompt = _build_user_prompt(record_type, headers, sample_rows)

    def _do_request():
        return client.chat.completions.create(
            model=getattr(settings, "IMPORTER_LLM_MODEL", "gpt-4.1-mini"),
            temperature=0.0,
            max_tokens=1024,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        )

    response = run_with_deadline(_do_request, seconds=timeout)
    content = response.choices[0].message.content or ""
    data = parse_json_response(content)
    mapping = data.get("mapping")
    if not isinstance(mapping, dict):
        raise ValueError("LLM response missing a 'mapping' object")
    return mapping


def _validate_llm_mapping(mapping: dict, headers: list[str], allowed_targets: set[str]) -> dict:
    """Defends against a hallucinated field, a missing header, or a
    duplicate target — any of these triggers the heuristic fallback
    instead of trusting a malformed mapping."""
    used_targets: set[str] = set()
    cleaned: dict[str, dict] = {}
    for header in headers:
        entry = mapping.get(header)
        if not isinstance(entry, dict):
            raise ValueError(f"LLM mapping is missing header '{header}'")
        target = entry.get("target")
        if target is not None:
            if target not in allowed_targets:
                raise ValueError(f"LLM invented an out-of-catalog target '{target}'")
            if target in used_targets:
                raise ValueError(f"LLM mapped two headers to the same target '{target}'")
            used_targets.add(target)
        confidence = entry.get("confidence")
        if not isinstance(confidence, (int, float)):
            confidence = 0.0
        cleaned[header] = {
            "target": target,
            "confidence": float(confidence) if target else 0.0,
            "reason": str(entry.get("reason") or ""),
        }
    return cleaned


def map_columns(*, record_type: str, headers: list[str], sample_rows: list[dict]) -> tuple[dict, str]:
    """Returns (column_mapping, mapping_source). mapping_source is
    "llm" or "heuristic_fallback" — surfaced on the review screen so the
    owner knows how much to double-check."""
    allowed_targets = set(target_fields_for(record_type).keys())
    try:
        raw_mapping = _call_llm(record_type, headers, sample_rows)
        mapping = _validate_llm_mapping(raw_mapping, headers, allowed_targets)
        return mapping, "llm"
    except Exception:
        logger.warning("Import column-mapping LLM call failed, using heuristic fallback", exc_info=True)
        return heuristic_map_columns(record_type, headers), "heuristic_fallback"
