"""Conservative post-NLU entity sanitization — drop catalog-only hallucinations."""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

from apps.chatbot.nlu.schemas import ExtractedEntities

_GROUNDED_ENTITY_FIELDS = (
    "doctor_name",
    "specialty",
    "service",
    "insurance_provider",
)


def sanitize_entities(message: str, entities: ExtractedEntities) -> ExtractedEntities:
    """Keep entity values only when grounded in the user's message.

    Date/time copied from conversation Ctx (e.g. a confirmed booking's
    ISO date) must not survive a message that never mentioned a day.
    If the message *does* contain date language ("Thursday", "tomorrow"),
    keep the classifier's resolved value.
    """
    msg = (message or "").strip()
    if not msg:
        return entities

    updates: dict[str, Any] = {}
    for field in _GROUNDED_ENTITY_FIELDS:
        raw = getattr(entities, field, None)
        if raw is None:
            continue
        kept = _filter_grounded_values(raw, msg)
        if not kept:
            updates[field] = None
        elif kept != raw:
            updates[field] = kept

    doctor_raw = updates.get("doctor_name", getattr(entities, "doctor_name", None))
    if doctor_raw is not None:
        cleaned_doctor = _clean_doctor_name_values(doctor_raw)
        if cleaned_doctor != doctor_raw:
            updates["doctor_name"] = cleaned_doctor

    from apps.chatbot.nlu.entity_extract import extract_entities

    extracted = extract_entities(msg)
    if getattr(entities, "date", None) and not extracted.get("date"):
        kept_date = _filter_grounded_values(entities.date, msg)
        if not kept_date:
            updates["date"] = None
    if getattr(entities, "time", None) and not extracted.get("time"):
        kept_time = _filter_grounded_values(entities.time, msg)
        if not kept_time:
            updates["time"] = None

    if not updates:
        return entities
    return replace(entities, **updates)


def entity_grounded_in_message(value: str, message: str) -> bool:
    """True when value is plausibly mentioned in the user message."""
    val = _normalize(value)
    msg = _normalize(message)
    if not val or not msg:
        return False
    if val in msg:
        return True
    val_tokens = [t for t in re.findall(r"[a-z0-9']+", val) if len(t) >= 3]
    msg_tokens = set(re.findall(r"[a-z0-9']+", msg))
    if not val_tokens:
        return False
    significant = [t for t in val_tokens if len(t) >= 4]
    check_tokens = significant or val_tokens
    matched = sum(1 for t in check_tokens if t in msg_tokens)
    if matched >= max(1, len(check_tokens) // 2):
        return True
    for t in check_tokens:
        for m in msg_tokens:
            if len(t) >= 4 and len(m) >= 4 and (m in t or t in m):
                return True
    return False


def _filter_grounded_values(value: str | list[str], message: str) -> str | list[str] | None:
    if isinstance(value, list):
        kept = [v for v in value if entity_grounded_in_message(str(v), message)]
        if not kept:
            return None
        return kept if len(kept) > 1 else kept[0]
    if entity_grounded_in_message(str(value), message):
        return value
    return None


def _clean_doctor_name_values(value: str | list[str] | None) -> str | list[str] | None:
    from apps.chatbot.nlu.entity_extract import clean_doctor_name

    if value is None:
        return None
    if isinstance(value, list):
        kept: list[str] = []
        for item in value:
            cleaned = clean_doctor_name(str(item))
            if cleaned:
                kept.append(cleaned)
        if not kept:
            return None
        return kept if len(kept) > 1 else kept[0]
    return clean_doctor_name(str(value))


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())
