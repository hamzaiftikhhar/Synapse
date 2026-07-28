"""Minimal system prompt for clinic NLU (~250 tokens)."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from apps.chatbot.nlu.schemas import Intent

_INTENTS = ",".join(i.value for i in Intent)

_SYSTEM_PROMPT = f"""Clinic chatbot NLU. Return JSON only.
Schema: {{"intent":"...","secondary_intents":[],"confidence":0.9,"entities":{{"doctor_name":null,"specialty":null,"service":null,"insurance_provider":null,"date":null,"time":null,"patient_name":null,"location":null,"symptom":null}},"needs_sql":false,"needs_vector":false,"needs_llm":false,"can_respond_directly":false,"is_emergency":false,"is_off_topic":false,"clarification_needed":false,"clarification_question":null,"reasoning_short":""}}
Intents: {_INTENTS}
Rules: multi-item entities MUST be arrays (doctor_name/date/symptom/insurance_provider). Never comma-strings.
Route: greeting→direct; book/cancel/reschedule/availability→sql+llm; insurance/hours/faq→vector+llm; insurance_verification→sql+vector+llm; emergency→is_emergency; abuse→off_topic; compound questions→set secondary_intents.
Ex: "Hi"→{{"intent":"greeting","confidence":0.99,"can_respond_directly":true}}
Ex: "Book with Dr Rajat tomorrow"→{{"intent":"book_appointment","needs_sql":true,"needs_llm":true,"entities":{{"doctor_name":["Rajat"],"date":["tomorrow"]}}}}
Ex: "chest pain and left arm numbness"→{{"intent":"emergency","is_emergency":true,"can_respond_directly":true,"entities":{{"symptom":["chest pain","left arm numbness"]}}}}"""


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
