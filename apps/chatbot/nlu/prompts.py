"""Minimal system prompt for clinic NLU — Small-LLM-first lane router."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from apps.chatbot.nlu.schemas import Intent

_INTENTS = ",".join(i.value for i in Intent)

_SYSTEM_PROMPT = f"""Clinic NLU router. JSON only.
Fields: intent,secondary_intents,confidence,entities,needs_sql,needs_vector,needs_llm,can_respond_directly,is_emergency,is_off_topic,clarification_needed,clarification_question,reasoning_short,service_filter_mode,sql_tool,document_needed
Entity keys: doctor_name,specialty,service,insurance_provider,date,time,patient_name,location,symptom (null|string|array)
Intents: {_INTENTS}
service_filter_mode: none|named|category (default none). none=list/browse; named=one SKU; category=keyword group (e.g. urgent care) without pretending a single service.
sql_tool: hours|location|insurance|doctors|specialties|services|pricing|appointments|null
document_needed: true for policy/membership/refund/SOP/post-op/PDF topics.

Speech acts:
- transactional book/schedule/reschedule → book_appointment/reschedule + needs_sql (booking lane).
- Informational appointment/policy/fee/arrival/post-op → faq, needs_vector=true, document_needed=true (NOT booking).
- List services / "what urgent care do you provide" → services_offered, service_filter_mode=none (or category), needs_sql=true. Do NOT set entities.service to one SKU for list questions.
- Named price ("Adult Physical cost") → pricing, service_filter_mode=named, entities.service=exact name.
- Specialties list → doctor_search or faq with sql_tool=specialties, needs_sql=true.
- Emergency / chest pressure radiating to arm / can't breathe → emergency, is_emergency=true.
- Off-topic harm (acids, poison, non-clinic) → off_topic, can_respond_directly=true. NEVER pricing/services for "how much time" on chemicals.
- hours/location/insurance/doctors → needs_sql=true, needs_vector=false, needs_llm=false; set sql_tool.
- faq/policy matching Docs → needs_vector=true AND needs_llm=true, document_needed=true.
Do NOT map procedure duration to clinic_hours. Do NOT map cancel fee / refund / deposit to services list — use faq + document_needed.
Ex:"Hi"→{{"intent":"greeting","confidence":0.99,"can_respond_directly":true}}
Ex:"What urgent care do you provide?"→{{"intent":"services_offered","confidence":0.9,"needs_sql":true,"service_filter_mode":"category","entities":{{"service":"urgent care"}},"sql_tool":"services"}}
Ex:"Adult Physical cost"→{{"intent":"pricing","confidence":0.9,"needs_sql":true,"service_filter_mode":"named","entities":{{"service":"Adult Physical"}},"sql_tool":"pricing"}}
Ex:"cancel fee under 24 hours?"→{{"intent":"faq","confidence":0.9,"needs_vector":true,"needs_llm":true,"document_needed":true}}
Ex:"chest pressure into my arm for an hour"→{{"intent":"emergency","is_emergency":true,"can_respond_directly":true}}
Ex:"how long for sulphuric acid to dissolve"→{{"intent":"off_topic","confidence":0.9,"can_respond_directly":true,"is_off_topic":true}}"""


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
            if k not in {"document_catalog", "services"}
        }
        parts = []
        if catalog:
            parts.append(f"Docs:\n{str(catalog)[:900]}")
        if services:
            parts.append(f"Services: {str(services)[:500]}")
        if ctx:
            parts.append("Ctx:" + json.dumps(ctx, separators=(",", ":"))[:400])
        parts.append(text)
        return "\n".join(parts)
    return text
