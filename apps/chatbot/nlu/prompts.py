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
Route: greeting/farewell/emergency→direct; book/cancel/reschedule/availability/doctor_search→sql+llm; insurance/hours/location/services/pricing/faq→vector+llm; insurance_verification→sql+vector+llm; abuse→off_topic.
Ex:"Hi"→{{"intent":"greeting","confidence":0.99,"can_respond_directly":true}}
Ex:"Book Dr Rajat tomorrow"→{{"intent":"book_appointment","confidence":0.9,"needs_sql":true,"needs_llm":true,"entities":{{"doctor_name":["Rajat"],"date":["tomorrow"]}}}}
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
        ctx = json.dumps(conversation_context, separators=(",", ":"))[:400]
        return f"Ctx:{ctx}\n{text}"
    return text
