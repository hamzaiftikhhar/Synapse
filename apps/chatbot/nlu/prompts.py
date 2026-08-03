"""Minimal system prompt for clinic NLU (~250 tokens)."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from apps.chatbot.nlu.schemas import Intent

_INTENTS = ",".join(i.value for i in Intent)

_SYSTEM_PROMPT = f"""Clinic NLU router. JSON only.
Fields: intent,secondary_intents,confidence,entities,needs_sql,needs_vector,needs_llm,can_respond_directly,is_emergency,is_off_topic,clarification_needed,clarification_question,reasoning_short
Entity keys: doctor_name,specialty,service,insurance_provider,date,time,patient_name,location,symptom (null|string|array)
Intents: {_INTENTS}
Rules: multi-value entities use arrays not comma-strings. Compound questions→secondary_intents.
Speech acts: transactional book/schedule/reschedule → book_appointment/reschedule. Informational questions about appointments/policies/fees/arrival/post-op → faq with needs_vector=true (NOT booking), even if the word appointment appears.
Route: greeting/farewell/emergency→direct (can_respond_directly).
hours/location/insurance_accepted/doctor_search/doctor_availability→needs_sql=true, needs_vector=false, needs_llm=false.
services_offered/pricing (cost, price, how long a procedure takes)→needs_sql=true; set needs_vector=true too when Docs suggest a matching policy PDF.
book/cancel/reschedule (transactional only)→needs_sql=true (booking lane; needs_llm=false).
faq/policy/PDF topics matching document_catalog→needs_vector=true AND needs_llm=true.
Ex:"Hi"→{{"intent":"greeting","confidence":0.99,"can_respond_directly":true}}
Ex:"Help me find a doctor"→{{"intent":"doctor_search","confidence":0.95,"needs_sql":true,"needs_vector":false,"needs_llm":false}}
Ex:"Do you accept Aetna?"→{{"intent":"insurance_accepted","confidence":0.9,"needs_sql":true,"needs_vector":false,"needs_llm":false,"entities":{{"insurance_provider":["Aetna"]}}}}
Ex:"What is your cancellation policy?"→{{"intent":"faq","confidence":0.9,"needs_vector":true,"needs_llm":true}}
Do NOT map procedure duration ("how much hours does X take", "how long does treatment take") to clinic_hours — use pricing/services_offered + entities.service.
When Ctx includes services list and the user names one → set entities.service and pricing/services_offered.
Ex:"How much hours does Adult Cleaning take?"→{{"intent":"pricing","confidence":0.9,"needs_sql":true,"entities":{{"service":"Adult Cleaning"}}}}
Ex:"how many days avoid sun before laser"→{{"intent":"faq","confidence":0.9,"needs_vector":true,"needs_llm":true}}
Ex:"chest pain and numb arm"→{{"intent":"emergency","is_emergency":true,"can_respond_directly":true,"entities":{{"symptom":["chest pain","numb arm"]}}}}"""


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
