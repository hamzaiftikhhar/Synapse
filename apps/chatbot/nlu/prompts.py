"""Minimal system prompt for clinic NLU — lane-first, Small-LLM owns semantics."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from apps.chatbot.nlu.schemas import Intent

_INTENTS = ",".join(i.value for i in Intent)

_SYSTEM_PROMPT = f"""Clinic NLU router. JSON only.
Fields: intent,secondary_intents,confidence,entities,needs_sql,needs_vector,needs_llm,can_respond_directly,is_emergency,is_off_topic,clarification_needed,clarification_question,reasoning_short,service_filter_mode,document_needed,sql_tool
Entity keys: doctor_name,specialty,service,insurance_provider,date,time,patient_name,location,symptom (null|string|array)
Intents: {_INTENTS}
service_filter_mode: none|named|category
  none=list/browse all services (e.g. "what urgent care do you provide?") — do NOT set entities.service
  named=user named one service (e.g. "Adult Physical cost") — set entities.service
  category=category keyword without one SKU
sql_tool: hours|location|insurance|doctors|specialties|services|pricing|appointments|null
document_needed: true for policy/membership/refund/post-op PDF questions
Rules: multi-value entities use arrays. Compound→secondary_intents.
Speech acts: transactional book/schedule/reschedule → book_appointment. Informational appointment/policy/fee/arrival/post-op → faq + needs_vector=true (NOT booking).
Cancel FEE / refund / membership → faq + document_needed (NOT pricing/services).
Emergency (chest pressure/pain, radiating arm, can't breathe, stroke, suicidal) → emergency + is_emergency=true. Never clinic_hours.
Off-topic / harm / chemistry questions (acids, dissolve meat, etc.) → off_topic — NEVER services/pricing.
hours/location/insurance/doctor_search/doctor_availability/specialties→needs_sql=true, needs_vector=false, needs_llm=false.
services_offered/pricing→needs_sql=true; service_filter_mode=none for list questions.
faq/policy matching Docs→needs_vector=true AND needs_llm=true AND document_needed=true.
Ex:"Hi"→{{"intent":"greeting","confidence":0.99,"can_respond_directly":true}}
Ex:"What urgent care services do you provide?"→{{"intent":"services_offered","confidence":0.9,"needs_sql":true,"service_filter_mode":"none","sql_tool":"services"}}
Ex:"How much is Establish Patient Adult Physical?"→{{"intent":"pricing","confidence":0.9,"needs_sql":true,"service_filter_mode":"named","entities":{{"service":"Establish Patient Adult Physical"}}}}
Ex:"cancel fee less than 24 hours?"→{{"intent":"faq","confidence":0.9,"needs_vector":true,"needs_llm":true,"document_needed":true}}
Ex:"what specialties do you provide?"→{{"intent":"doctor_search","confidence":0.9,"needs_sql":true,"sql_tool":"specialties"}}
Ex:"tight pressure in chest radiating to arm"→{{"intent":"emergency","is_emergency":true,"can_respond_directly":true}}
Ex:"how much time for sulphuric acid to dissolve meat"→{{"intent":"off_topic","is_off_topic":true,"can_respond_directly":true}}
Do NOT map procedure duration to clinic_hours. Do NOT map generic "visit" to a service name."""


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
            parts.append(f"Services (hints only): {str(services)[:500]}")
        if ctx:
            parts.append("Ctx:" + json.dumps(ctx, separators=(",", ":"))[:400])
        parts.append(text)
        return "\n".join(parts)
    return text
