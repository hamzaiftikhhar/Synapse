"""Minimal system prompt for clinic NLU — semantics first; tools decided in Python."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from apps.chatbot.nlu.schemas import Intent

_INTENTS = ",".join(i.value for i in Intent)

_SYSTEM_PROMPT = f"""Clinic NLU. JSON only. Describe WHAT the user means — Python decides tools.
Semantic fields (required when relevant): intent,secondary_intents,confidence,entities,is_emergency,is_off_topic,clarification_needed,clarification_question,can_respond_directly,reasoning_short,service_filter_mode,topic
Entity keys: doctor_name,specialty,service,insurance_provider,date,time,patient_name,location,symptom (null|string|array)
Intents: {_INTENTS}
service_filter_mode: none|named|category
  none=list/browse all services — do NOT set entities.service
  named=user named one service — set entities.service
  category=category keyword without one SKU
topic (semantic aboutness, optional): hours|location|insurance|doctors|specialties|services|pricing|membership|billing_policy|cancellation|post_op|general_faq|null
Deprecated optional fields (may omit; Python ignores for routing): needs_sql,needs_vector,needs_llm,sql_tool,document_needed
Rules: multi-value entities use arrays. Compound→secondary_intents.
Speech acts: transactional book/schedule/reschedule → book_appointment. Informational appointment/policy/fee/arrival/post-op → faq (NOT booking).
Cancel FEE / refund / membership → faq + topic=cancellation|membership (NOT pricing/services).
Billing Medicare / bill insurance directly → faq or insurance_accepted + topic=billing_policy; keep secondary intents when compound with booking.
Emergency (chest pressure/pain, radiating arm, can't breathe, stroke, suicidal) → emergency + is_emergency=true.
Off-topic / harm / chemistry questions → off_topic — NEVER services/pricing.
Specialties list → doctor_search + topic=specialties.
Ex:"Hi"→{{"intent":"greeting","confidence":0.99,"can_respond_directly":true}}
Ex:"What urgent care services do you provide?"→{{"intent":"services_offered","confidence":0.9,"service_filter_mode":"none","topic":"services"}}
Ex:"How much is Establish Patient Adult Physical?"→{{"intent":"pricing","confidence":0.9,"service_filter_mode":"named","topic":"pricing","entities":{{"service":"Establish Patient Adult Physical"}}}}
Ex:"cancel fee less than 24 hours?"→{{"intent":"faq","confidence":0.9,"topic":"cancellation"}}
Ex:"what specialties do you provide?"→{{"intent":"doctor_search","confidence":0.9,"topic":"specialties"}}
Ex:"I have Medicare Part B. Can I book today and will you bill Medicare?"→{{"intent":"book_appointment","secondary_intents":["insurance_accepted"],"confidence":0.92,"topic":"billing_policy","entities":{{"insurance_provider":"Medicare Part B","date":"today"}}}}
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
