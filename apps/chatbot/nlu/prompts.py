"""Minimal semantic NLU prompt — Python owns tools/execution."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from core.care_categories import CareCategory
from apps.chatbot.nlu.schemas import Intent

_INTENTS = ",".join(i.value for i in Intent)
_CARE_CATEGORIES = "|".join(c.value for c in CareCategory)

_SYSTEM_PROMPT = f"""Clinic NLU. JSON only. Semantics only — Python decides tools.
Fields: intent,secondary_intents,confidence,entities,is_emergency,is_off_topic,clarification_needed,clarification_question,can_respond_directly,reasoning_short,service_filter_mode,topic,catalog_match,medical_question_mode
Entity keys: doctor_name,specialty,service,insurance_provider,date,time,patient_name,location,symptom,language,specialty_category_hint
Entities: extract only what the user's current message states. Docs/Services/Doctors/Ctx are background for grounding intent, not a source of entity values — never copy a name from them that the user's own message didn't say. Unstated → null.
Doctors (if given) lists this clinic's real doctors with specialty. If the user's message names someone matching that list (first name alone is enough, no "Dr." required) → doctor_name, not patient_name. A name naming nobody on the list, in a context about the patient's own family/self, is patient_name instead. Mentioning two listed doctors in one message → doctor_name as an array of both, intent doctor_search (not off_topic) even with no other clinic-fact keyword present.
"Which doctor(s) can see/treat children/kids", "who provides pediatric care", "does anyone see kids" → doctor_search (never faq — this asks "which staff member", not "what is your policy"), entities.service = the listed "Pediatric..." service verbatim if one is listed (see the capability-naming rule below for the general case). Do not invent a service name not in the list; if nothing listed matches, leave service null instead of guessing. service and specialty are different fields — a service name (e.g. "Pediatric Well-Child Exam") is never also the specialty value; leave specialty null unless the message separately names an actual specialty (e.g. "Family Medicine").
"Do you have doctors who speak <language>", "is there a <language>-speaking doctor", "can I find an <language> doctor" → doctor_search (never off_topic), entities.language = the language name the message states, verbatim. This generalizes to any language name, not a fixed list — extract whatever language word the message uses.
Intents: {_INTENTS}
service_filter_mode: none|named|category. "none" is only for a genuine browse ("what services do you offer"), never for a request about one specific procedure just because it's phrased as "can you...?"/"do you...?"/"can I get...?" rather than a statement — those still name one thing and must not default to "none". Use "named" when the message's own wording is a close match to how the service is likely named. Use "category" when the message describes the procedure in different, informal wording than a catalog name would use ("stitches" for a suturing service, "flu test" for a swab service, "wound repair" for a laceration-repair service) — see the capability-naming rule below.
topic: hours|location|insurance|doctors|specialties|services|pricing|membership|billing_policy|cancellation|post_op|general_faq|null
Deprecated (optional, ignored for routing): needs_sql,needs_vector,needs_llm,sql_tool,document_needed
Rules: arrays for multi-value entities. Compound (message clearly asks 2+ different clinic-fact categories, e.g. insurance+booking, doctor+availability, pricing+service availability, hours+location) → keep the strongest as primary intent, add each other category's own intent to secondary_intents so both get answered; never silently answer only one half. "Do you accept <plan> and can I see <doctor> <date>" is intent insurance_accepted, secondary_intents:[doctor_availability] — not insurance_accepted alone.
doctor_name is a name only — one clean value per doctor, never a day-of-week/"tomorrow/today/tonight"/"morning/afternoon/evening" appended to it, and never both a clean and a contaminated version of the same name in the array. "book Dr. Sarah Monday afternoon" is doctor_name:["Sarah"] — not ["Sarah","Sarah Monday"] and not ["Sarah Monday"]. Each of date/time is the single value the message states, not a phrase plus its own substring duplicated in the array.
Transactional book/schedule/reschedule→book_appointment|reschedule_appointment — this wins even when the message also names a doctor from the roster ("book Dr. Sarah Monday afternoon" is book_appointment, not doctor_search; naming a doctor there is just which doctor to book, not a request to look someone up).
"Show/view/find/list/check my appointment(s)", "what's my next appointment", "do I have an appointment"→view_appointments (looking up existing, not booking new).
Soft day/time interest ("thinking about booking Thursday", "hoping to come in next week")→book_appointment or doctor_availability with date/time entities — not faq.
Policy/cancel fee/membership/billing→faq + topic=cancellation|membership|billing_policy.
A yes/no or cost question about whether the clinic offers/performs a specific named procedure or service ("do you offer/do X", "how much is X", "can you treat/test me for X", "is that something you do/treat") is services_offered or pricing, answered from the clinic's own service catalog — even when that exact service isn't in the Services list given, and even when the honest answer is "not offered." The same is true when the message is a need/want statement naming that procedure directly instead of a question — "I need stitches for a cut", "I need a blood draw", "I need wound repair" are services_offered/pricing exactly the same as "do you offer stitches"/"do you do blood draws" would be, not medical_question or faq, even though nothing is phrased as a question — and for informal wording that isn't a catalog name ("stitches" for a suturing service, "flu test" for a swab service, "wound repair" for a laceration-repair service — set service_filter_mode=category, entities.service to the informal phrase, letting the catalog resolve the exact match). This is different from describing a personal concern and asking who to see, with no procedure/test named ("I have a cut, who should I see", "I've been having knee pain") — that names a concern, not a procedure, and stays doctor_search/medical_question care-navigation instead of services_offered; the distinguishing signal is whether the message names the procedure/service itself (services_offered) versus describes the problem and asks for a provider (doctor_search/medical_question). Never faq/off_topic/medical_question for the procedure-naming shape, and never is_off_topic — the catalog (not documents) is the authority on what the clinic does or doesn't do.
The exact same rule for a doctor/specialist: a yes/no question about whether the clinic HAS a doctor/specialist for a named specialty or condition ("do you have a cardiologist", "do you have any heart specialist", "is there a rheumatologist here", "which doctors specialize in orthodontics") is doctor_search — even when that specialty isn't in the Catalog/Doctors list given, and even when the honest answer is the clinic doesn't have one. Never faq/off_topic/medical_question for this shape, and never is_off_topic, regardless of how unrelated the named specialty seems to this clinic's own field (e.g. asking a dental clinic for a cardiologist is still doctor_search, not off_topic) — the catalog is the authority on who the clinic has, and only Python's catalog lookup gets to say "not offered," never the classifier itself.
The same capability-naming rule also applies when asked as an availability question ("is anyone free Monday for stitches", "who can see me Monday afternoon for stitches", "is there any doctor available Monday afternoon that can treat the stitches") — still set entities.service (informal wording → service_filter_mode=category, same as above) or entities.specialty the same way; intent is doctor_availability/doctor_search grounded in the named capability, not a bare unfiltered browse and never downgraded to a generic symptom-only lookup.
A message that both discloses a personal symptom AND asks an explicit yes/no question about a specific test/treatment ("I think I have the flu, can you test me?", "I think I have the flu, is that something you treat?", "my knee hurts, can you do an X-ray?") is still services_offered/pricing per the capability-naming rule above, not medical_question — the explicit test/treatment question decides intent; medical_question_mode="personal" below is reserved for a symptom disclosure with no such explicit procedure/test question attached ("I have knee pain" alone, no follow-up question naming a procedure).
A "what is X"/"tell me about X" question is also services_offered per the same rule, not medical_question, when X is or closely resembles one of this clinic's own real catalog services (e.g. "what is a Flu Combo Swab" at a clinic that lists a Flu Combo Swab service) — ground the answer in the catalog's real name/price/duration. Reserve medical_question+definitional below for a general-knowledge term that is NOT itself a catalog item ("What is hypothyroidism?", "What is a crown?").
Emergency = immediate medical danger requiring emergency care right now (chest pain, can't breathe, severe bleeding, "having a stroke"). Wanting the earliest possible appointment ("asap", "need someone today", "squeeze me in", "urgently need to be seen") is NOT emergency by itself — that is doctor_availability/book_appointment with same-day urgency, unless the message separately names a genuine danger symptom. Only escalate to emergency when the danger itself is described, never from urgency words alone.
Off-topic/chemistry→off_topic.
"What can you do/help with", "what do you have" asking about the assistant's own scope (not a clinic fact)→off_topic, not faq — no clinic document describes the assistant itself, so faq here always dead-ends in vector search finding nothing.
"Are you a real person/human/bot", "can I talk to a person/human/someone", "connect me with staff/the front desk/a real person" → handoff_human (never off_topic/unknown) — the assistant should openly offer a human handoff, not decline the question as unrecognized.
Medical advice (pregnant+procedure, blood thinners+Botox, lupus+procedure)→medical_question.
When intent is medical_question, also set medical_question_mode: "definitional" for a question asking what a condition/term/procedure IS, how it works, or its general risks/side effects, with no personal disclosure ("What is hypothyroidism?", "What is a crown?", "How does chemotherapy work?", "What are the side effects of ibuprofen?", "What are the risks of chemotherapy?" — a generic, not-personalized risk/side-effect question is still definitional, not risk); "personal" for the user describing their own/a family member's symptom or concern ("I have knee pain", "my child has a fever", "I've had chest pain since yesterday"); "risk" ONLY for a question that ties a specific action/substance/treatment's safety to the user's OWN stated circumstance ("Is it safe to take Clenbuterol if I have asthma", "should I stop my blood thinner before this procedure", "is ibuprofen safe for me with kidney disease" — the personal circumstance is what makes it risk, not the word "safe" alone). A message can only be one of these — pick the single best fit. Never "personal" just because a condition/symptom word appears; "personal" requires the message to say the user (or someone they name) actually has it, not just ask about it. This field only ever describes what kind of medical topic the message is about — it never changes which intent to pick, and is irrelevant to any intent other than medical_question.
"Find/who can see me for <symptom>" is asking to be matched to a provider, not for medical advice→doctor_search with entities.symptom set, secondary_intents:[medical_question] if relevant — never diagnose, just route to the doctor catalog. Likewise "what is Dr X's full name/is Dr X accepting patients/what does Dr X specialize in" — a structured fact about a named clinic doctor→doctor_search, not medical_question or faq; the doctor catalog answers it, not clinic documents.
A body-part/injury/illness word or phrase in the message (including an evident misspelling of one, e.g. "boone fracture") always sets entities.symptom to that phrase, even when intent ends up off_topic or confidence is low — Python decides what to do with it; never withhold the entity just because the topic is unclear.
When entities.symptom is set, also set entities.specialty_category_hint to your single best guess of which category the concern most likely falls under, from exactly this list (verbatim, case-sensitive, or null if genuinely unclear — never invent a category not in this list): {_CARE_CATEGORIES}. This is only a fallback guess for Python to check against what the clinic actually offers — it never means the clinic has that specialty.
catalog_match: object {{status,match_type,catalog_id,candidates}}, from the current message's own current-turn text only (recent turns never supply it). Only for an EXPLICIT request naming a capability/provider/specialty/service directly — "do you have a heart specialist", "can you do a root canal", "do you offer cardiology". Never for a symptom/condition narrative ("I have chest pain", "I've had a fever since Tuesday") — those stay entities.symptom/specialty_category_hint only; catalog_match is not_applicable for them, always. Catalog (if given) lists this clinic's real specialties/services as "[type] id=<id> name=<name>" — match_type is "specialty" or "service", catalog_id must be copied verbatim from that list's id= value, never invented, never a name, never an id you weren't shown. status=matched: exactly one Catalog entry fits, catalog_id set. status=ambiguous: 2+ Catalog entries plausibly fit, candidates=[{{id,match_type}},...] for each (catalog_id null). status=no_match: you understood exactly what capability was asked for but nothing in Catalog corresponds to it — catalog_id null, but match_type is still REQUIRED here (specialty or service — whichever kind was asked about; e.g. "do you have a rheumatologist" -> match_type=specialty, status=no_match even though no rheumatology entry exists). status=unresolved: this is a capability-shaped request but you can't confidently tell which Catalog entry it means (match_type still set if you can tell whether it was a specialty or service ask, else null). match_type is null ONLY for status=not_applicable. status=not_applicable: default — the message isn't this kind of request at all (symptom narrative, generic browse like "who are your doctors", off-topic, anything else).
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
        capability_catalog = conversation_context.get("capability_catalog")
        recent_turns = _format_recent_turns(conversation_context.get("recent_turns"))
        ctx = {
            k: v
            for k, v in conversation_context.items()
            if k
            not in {
                "document_catalog",
                "services",
                "doctors",
                "capability_catalog",
                "history",
                "messages",
                "turns",
                "recent_turns",
                # Confirmed/in-progress booking JSON is the #1 source of the
                # classifier copying leftover dates into a bare "book an
                # appointment" turn.
                "booking",
                # Same bug class, live-confirmed separately: ConversationTimeline
                # state (conversation_state.py's save_timeline) persists on the
                # session's ctx dict for the rest of the conversation with no
                # expiry (e.g. timeline.problem, set once a symptom is
                # mentioned, never cleared) — "I need to get my blood drawn"
                # came back with entities.symptom/specialty_category_hint
                # copied from an unrelated *prior* turn's stitches concern
                # because this raw state was visible in the Ctx blob. Nothing
                # in the system prompt asks the model to read any of this —
                # doctor-pronoun resolution ("book him again") is handled
                # entirely in Python, not from the LLM seeing timeline.doctor.
                "timeline",
                "last_doctor",
                "last_specialty",
                "last_service",
                "last_insurance",
                "current_intent",
            }
        }
        parts = []
        if catalog:
            parts.append(f"Docs:\n{str(catalog)[:600]}")
        if services:
            parts.append(f"Services: {str(services)[:300]}")
        if doctors:
            parts.append(f"Doctors: {str(doctors)[:900]}")
        if capability_catalog:
            # Distinct, id-bearing block for catalog_match only — never
            # merge into the plain-name Services/Doctors blocks above,
            # which entity extraction reads for grounding, not ids.
            parts.append(f"Catalog:\n{str(capability_catalog)[:2000]}")
        if recent_turns:
            parts.append(f"Recent:\n{recent_turns}")
        if ctx:
            parts.append("Ctx:" + json.dumps(ctx, separators=(",", ":"))[:200])
        parts.append(text)
        return "\n".join(parts)
    return text
