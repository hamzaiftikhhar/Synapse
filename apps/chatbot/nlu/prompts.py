"""System prompt and few-shot examples for clinic Intent & Entity NLU."""

from __future__ import annotations

import json
from typing import Any

from apps.chatbot.nlu.schemas import Intent

INTENT_LIST = ", ".join(i.value for i in Intent)

SYSTEM_PROMPT = f"""You are the Intent & Entity classifier for a multi-tenant healthcare clinic chatbot.

Return ONLY valid JSON matching this schema (no markdown, no prose):
{{
  "intent": "<one of: {INTENT_LIST}>",
  "secondary_intents": [],
  "confidence": 0.0,
  "entities": {{
    "doctor_name": null,
    "specialty": null,
    "service": null,
    "insurance_provider": null,
    "date": null,
    "time": null,
    "patient_name": null,
    "location": null,
    "symptom": null
  }},
  "needs_sql": false,
  "needs_vector": false,
  "needs_llm": false,
  "can_respond_directly": false,
  "is_emergency": false,
  "is_off_topic": false,
  "clarification_needed": false,
  "clarification_question": null,
  "reasoning_short": ""
}}

Routing hints (set flags accordingly):
- greeting / farewell → can_respond_directly=true, needs_sql/vector/llm=false
- book/cancel/reschedule appointment, doctor_availability, doctor_search → needs_sql=true, needs_llm=true
- insurance_accepted, clinic_hours, clinic_location, services_offered, pricing, membership, faq, medical_question (clinic policy docs) → needs_vector=true, needs_llm=true
- insurance_verification (patient plan + accepted plans) → needs_sql=true, needs_vector=true, needs_llm=true
- prescription_refill, lab_info, patient_registration, handoff_human → needs_llm=true (and needs_sql if booking-related)
- emergency (chest pain, can't breathe, suicidal, stroke symptoms) → is_emergency=true, can_respond_directly=true
- off_topic → is_off_topic=true, can_respond_directly=true
- unclear message → clarification_needed=true with a short clarification_question
- multi_intent when the user asks two distinct things; put extras in secondary_intents

Extract entities only when present. Prefer null over guessing.
confidence is 0–1.
"""

FEW_SHOT_EXAMPLES: list[dict[str, Any]] = [
    {
        "user": "Hi there!",
        "output": {
            "intent": "greeting",
            "secondary_intents": [],
            "confidence": 0.99,
            "entities": {
                "doctor_name": None,
                "specialty": None,
                "service": None,
                "insurance_provider": None,
                "date": None,
                "time": None,
                "patient_name": None,
                "location": None,
                "symptom": None,
            },
            "needs_sql": False,
            "needs_vector": False,
            "needs_llm": False,
            "can_respond_directly": True,
            "is_emergency": False,
            "is_off_topic": False,
            "clarification_needed": False,
            "clarification_question": None,
            "reasoning_short": "Simple greeting",
        },
    },
    {
        "user": "I need to book with a cardiologist next Tuesday morning",
        "output": {
            "intent": "book_appointment",
            "secondary_intents": [],
            "confidence": 0.95,
            "entities": {
                "doctor_name": None,
                "specialty": "cardiology",
                "service": None,
                "insurance_provider": None,
                "date": "next Tuesday",
                "time": "morning",
                "patient_name": None,
                "location": None,
                "symptom": None,
            },
            "needs_sql": True,
            "needs_vector": False,
            "needs_llm": True,
            "can_respond_directly": False,
            "is_emergency": False,
            "is_off_topic": False,
            "clarification_needed": False,
            "clarification_question": None,
            "reasoning_short": "Booking requires availability lookup",
        },
    },
    {
        "user": "Do you take Blue Cross?",
        "output": {
            "intent": "insurance_accepted",
            "secondary_intents": [],
            "confidence": 0.94,
            "entities": {
                "doctor_name": None,
                "specialty": None,
                "service": None,
                "insurance_provider": "Blue Cross",
                "date": None,
                "time": None,
                "patient_name": None,
                "location": None,
                "symptom": None,
            },
            "needs_sql": True,
            "needs_vector": True,
            "needs_llm": True,
            "can_respond_directly": False,
            "is_emergency": False,
            "is_off_topic": False,
            "clarification_needed": False,
            "clarification_question": None,
            "reasoning_short": "Check accepted plans and policy docs",
        },
    },
    {
        "user": "What are your hours on Saturday?",
        "output": {
            "intent": "clinic_hours",
            "secondary_intents": [],
            "confidence": 0.93,
            "entities": {
                "doctor_name": None,
                "specialty": None,
                "service": None,
                "insurance_provider": None,
                "date": "Saturday",
                "time": None,
                "patient_name": None,
                "location": None,
                "symptom": None,
            },
            "needs_sql": True,
            "needs_vector": True,
            "needs_llm": True,
            "can_respond_directly": False,
            "is_emergency": False,
            "is_off_topic": False,
            "clarification_needed": False,
            "clarification_question": None,
            "reasoning_short": "Hours from DB and/or knowledge docs",
        },
    },
    {
        "user": "I have severe chest pain and can't breathe",
        "output": {
            "intent": "emergency",
            "secondary_intents": [],
            "confidence": 0.99,
            "entities": {
                "doctor_name": None,
                "specialty": None,
                "service": None,
                "insurance_provider": None,
                "date": None,
                "time": None,
                "patient_name": None,
                "location": None,
                "symptom": "chest pain, can't breathe",
            },
            "needs_sql": False,
            "needs_vector": False,
            "needs_llm": False,
            "can_respond_directly": True,
            "is_emergency": True,
            "is_off_topic": False,
            "clarification_needed": False,
            "clarification_question": None,
            "reasoning_short": "Emergency symptoms — safety response",
        },
    },
]


def build_user_prompt(
    message: str,
    conversation_context: dict[str, Any] | None = None,
) -> str:
    examples = "\n\n".join(
        f"Example user: {ex['user']}\nExample JSON: {json.dumps(ex['output'], ensure_ascii=True)}"
        for ex in FEW_SHOT_EXAMPLES
    )
    context_block = ""
    if conversation_context:
        context_block = (
            "\nConversation context (JSON):\n"
            f"{json.dumps(conversation_context, ensure_ascii=True)[:2000]}\n"
        )
    return (
        f"{examples}\n\n"
        f"{context_block}"
        f"Classify this user message and return JSON only:\n{message.strip()}"
    )
