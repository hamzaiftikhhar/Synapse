"""Minimal semantic NLU prompt — Python owns tools/execution."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from apps.chatbot.nlu.schemas import Intent

_INTENTS = ",".join(i.value for i in Intent)

_SYSTEM_PROMPT = f"""Clinic NLU. JSON only. Semantics only — Python decides tools.
Fields: intent,secondary_intents,confidence,entities,is_emergency,is_off_topic,clarification_needed,clarification_question,can_respond_directly,reasoning_short,service_filter_mode,topic
Entity keys: doctor_name,specialty,service,insurance_provider,date,time,patient_name,location,symptom
Entities: extract only what the user's current message states. Docs/Services/Ctx are background for grounding intent, not a source of entity values — never copy a name from them. Unstated → null.
Intents: {_INTENTS}
service_filter_mode: none|named|category
topic: hours|location|insurance|doctors|specialties|services|pricing|membership|billing_policy|cancellation|post_op|general_faq|null
Deprecated (optional, ignored for routing): needs_sql,needs_vector,needs_llm,sql_tool,document_needed
Rules: arrays for multi-value entities. Compound→secondary_intents.
Transactional book/schedule/reschedule→book_appointment|reschedule_appointment.
Policy/cancel fee/membership/billing→faq + topic=cancellation|membership|billing_policy.
Emergency→emergency+is_emergency. Off-topic/chemistry→off_topic.
Medical advice (pregnant+procedure, blood thinners+Botox, lupus+procedure)→medical_question.
Keep reasoning_short under 12 words."""


@lru_cache(maxsize=1)
def get_system_prompt() -> str:
    return _SYSTEM_PROMPT


SYSTEM_PROMPT = get_system_prompt()


def build_user_prompt(
    message: str,
    conversation_context: dict[str, Any] | None = None,
) -> str:
    text = message.strip()
    if text.lower().startswith("message:"):
        text = text[8:].strip()
    if conversation_context:
        catalog = conversation_context.get("document_catalog")
        services = conversation_context.get("services")
        ctx = {
            k: v
            for k, v in conversation_context.items()
            if k not in {"document_catalog", "services", "history", "messages", "turns"}
        }
        parts = []
        if catalog:
            parts.append(f"Docs:\n{str(catalog)[:600]}")
        if services:
            parts.append(f"Services: {str(services)[:300]}")
        if ctx:
            parts.append("Ctx:" + json.dumps(ctx, separators=(",", ":"))[:200])
        parts.append(text)
        return "\n".join(parts)
    return text
