"""Minimal semantic NLU prompt — Python owns tools/execution."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from apps.chatbot.nlu.schemas import Intent

_INTENTS = ",".join(i.value for i in Intent)

_SYSTEM_PROMPT = f"""Clinic NLU. JSON only. Semantics only — Python decides tools.
Fields: intent,secondary_intents,confidence,entities,is_emergency,is_off_topic,clarification_needed,clarification_question,can_respond_directly,reasoning_short,service_filter_mode,topic
Entity keys: doctor_name,specialty,service,insurance_provider,date,time,patient_name,location,symptom,language
Entities: extract only what the user's current message states. Docs/Services/Doctors/Ctx are background for grounding intent, not a source of entity values — never copy a name from them that the user's own message didn't say. Unstated → null.
Doctors (if given) lists this clinic's real doctors with specialty. If the user's message names someone matching that list (first name alone is enough, no "Dr." required) → doctor_name, not patient_name. A name naming nobody on the list, in a context about the patient's own family/self, is patient_name instead. Mentioning two listed doctors in one message → doctor_name as an array of both, intent doctor_search (not off_topic) even with no other clinic-fact keyword present.
"Which doctor(s) can see/treat children/kids", "who provides pediatric care", "does anyone see kids" → doctor_search (never faq — this asks "which staff member", not "what is your policy"), entities.service = the listed "Pediatric..." service verbatim if one is listed. Generalize the same way for any other capability/age-group/condition phrase that clearly names one listed service. Do not invent a service name not in the list; if nothing listed matches, leave service null instead of guessing. service and specialty are different fields — a service name (e.g. "Pediatric Well-Child Exam") is never also the specialty value; leave specialty null unless the message separately names an actual specialty (e.g. "Family Medicine").
"Do you have doctors who speak <language>", "is there a <language>-speaking doctor", "can I find an <language> doctor" → doctor_search (never off_topic), entities.language = the language name the message states, verbatim. This generalizes to any language name, not a fixed list — extract whatever language word the message uses.
Intents: {_INTENTS}
service_filter_mode: none|named|category
topic: hours|location|insurance|doctors|specialties|services|pricing|membership|billing_policy|cancellation|post_op|general_faq|null
Deprecated (optional, ignored for routing): needs_sql,needs_vector,needs_llm,sql_tool,document_needed
Rules: arrays for multi-value entities. Compound (message clearly asks 2+ different clinic-fact categories, e.g. insurance+booking, doctor+availability, pricing+service availability, hours+location) → keep the strongest as primary intent, add each other category's own intent to secondary_intents so both get answered; never silently answer only one half. "Do you accept <plan> and can I see <doctor> <date>" is intent insurance_accepted, secondary_intents:[doctor_availability] — not insurance_accepted alone.
doctor_name is a name only — one clean value per doctor, never a day-of-week/"tomorrow/today/tonight"/"morning/afternoon/evening" appended to it, and never both a clean and a contaminated version of the same name in the array. "book Dr. Sarah Monday afternoon" is doctor_name:["Sarah"] — not ["Sarah","Sarah Monday"] and not ["Sarah Monday"]. Each of date/time is the single value the message states, not a phrase plus its own substring duplicated in the array.
Transactional book/schedule/reschedule→book_appointment|reschedule_appointment — this wins even when the message also names a doctor from the roster ("book Dr. Sarah Monday afternoon" is book_appointment, not doctor_search; naming a doctor there is just which doctor to book, not a request to look someone up).
"Show/view/find/list/check my appointment(s)", "what's my next appointment", "do I have an appointment"→view_appointments (looking up existing, not booking new).
Soft day/time interest ("thinking about booking Thursday", "hoping to come in next week")→book_appointment or doctor_availability with date/time entities — not faq.
Policy/cancel fee/membership/billing→faq + topic=cancellation|membership|billing_policy.
A yes/no or cost question about whether the clinic offers/performs a specific named procedure or service ("do you offer/do X", "how much is X") is services_offered or pricing, and answered from the clinic's own service catalog — even when that exact service isn't in the Services list given, and even when the honest answer is "not offered." Never faq/off_topic/medical_question for this shape, and never is_off_topic — the catalog (not documents) is the authority on what the clinic does or doesn't do.
Emergency = immediate medical danger requiring emergency care right now (chest pain, can't breathe, severe bleeding, "having a stroke"). Wanting the earliest possible appointment ("asap", "need someone today", "squeeze me in", "urgently need to be seen") is NOT emergency by itself — that is doctor_availability/book_appointment with same-day urgency, unless the message separately names a genuine danger symptom. Only escalate to emergency when the danger itself is described, never from urgency words alone.
Off-topic/chemistry→off_topic.
"What can you do/help with", "what do you have" asking about the assistant's own scope (not a clinic fact)→off_topic, not faq — no clinic document describes the assistant itself, so faq here always dead-ends in vector search finding nothing.
Medical advice (pregnant+procedure, blood thinners+Botox, lupus+procedure)→medical_question.
"Find/who can see me for <symptom>" is asking to be matched to a provider, not for medical advice→doctor_search with entities.symptom set, secondary_intents:[medical_question] if relevant — never diagnose, just route to the doctor catalog. Likewise "what is Dr X's full name/is Dr X accepting patients/what does Dr X specialize in" — a structured fact about a named clinic doctor→doctor_search, not medical_question or faq; the doctor catalog answers it, not clinic documents.
Recent turns (if given) are the immediately preceding conversation, oldest first. Use them only to resolve a short/bare current message ("yes","sure","earliest","that one") against the assistant's immediately preceding turn — what offer or question was it responding to. Never let recent turns override or supply an entity the current message doesn't itself state. If the current message is short and recent turns don't make its target clear, prefer low confidence/clarification_needed over guessing a topic.
Keep reasoning_short under 12 words."""


@lru_cache(maxsize=1)
def get_system_prompt() -> str:
    return _SYSTEM_PROMPT


SYSTEM_PROMPT = get_system_prompt()


_RECENT_TURN_CHARS = 90


def _format_recent_turns(turns: Any) -> str:
    """Compact, plain-text render of the last few messages — never JSON
    (cheaper in tokens, and reads as conversation rather than state the
    model might be tempted to copy fields out of). Each turn is truncated;
    this is context for resolving a short reply's target, not a transcript
    to quote from. Malformed entries are skipped rather than raising —
    this must never be the reason a chat turn fails."""
    if not isinstance(turns, list):
        return ""
    lines = []
    for turn in turns:
        if not isinstance(turn, dict):
            continue
        role = turn.get("role")
        content = str(turn.get("content") or "").strip()
        if not content:
            continue
        tag = "U" if role == "user" else "A" if role == "assistant" else None
        if tag is None:
            continue
        lines.append(f"{tag}: {content[:_RECENT_TURN_CHARS]}")
    return "\n".join(lines)


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
        doctors = conversation_context.get("doctors")
        recent_turns = _format_recent_turns(conversation_context.get("recent_turns"))
        ctx = {
            k: v
            for k, v in conversation_context.items()
            if k
            not in {
                "document_catalog",
                "services",
                "doctors",
                "history",
                "messages",
                "turns",
                "recent_turns",
                # Confirmed/in-progress booking JSON is the #1 source of the
                # classifier copying leftover dates into a bare "book an
                # appointment" turn.
                "booking",
            }
        }
        parts = []
        if catalog:
            parts.append(f"Docs:\n{str(catalog)[:600]}")
        if services:
            parts.append(f"Services: {str(services)[:300]}")
        if doctors:
            parts.append(f"Doctors: {str(doctors)[:900]}")
        if recent_turns:
            parts.append(f"Recent:\n{recent_turns}")
        if ctx:
            parts.append("Ctx:" + json.dumps(ctx, separators=(",", ":"))[:200])
        parts.append(text)
        return "\n".join(parts)
    return text
