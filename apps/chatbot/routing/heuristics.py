"""Hybrid keyword heuristics applied after rules/NLU — clinic-agnostic."""

from __future__ import annotations

import re
from typing import Any

from apps.chatbot.nlu.schemas import Intent, NLUResult
from apps.chatbot.routing.signals import (
    catalog_overlap_score,
    is_business_hours_query,
    is_informational,
    is_price_or_duration_query,
    is_procedure_duration_query,
    is_transactional_booking,
    looks_like_about_service,
    looks_like_knowledge_question,
    match_services_in_message,
)


_LOCATION_RE = re.compile(
    r"\b(where|address|location|directions|map|parking)\b", re.I
)
_DOCTOR_RE = re.compile(
    r"\b(find (?:me )?(?:a |the )?(?:doctor|dentist|physician)|"
    r"help me find (?:a )?(?:doctor|dentist)|list (?:of )?(?:doctors|dentists)|"
    r"who (are|is) (your|the) (?:doctor|dentist)|show (me )?(doctors|dentists|physicians)|"
    r"cardiologist|dermatologist|neurologist|primary care)\b",
    re.I,
)
_INSURANCE_RE = re.compile(
    r"\b(insurance|aetna|cigna|medicare|medicaid|blue\s*cross|humana|"
    r"accept(ed|s)?|coverage|copay|medi[- ]?cal|denti[- ]?cal)\b",
    re.I,
)
_AVAIL_RE = re.compile(
    r"\b(available|availability|earliest|tomorrow|today|slot|slots)\b", re.I
)
_BOOK_RE = re.compile(r"\b(book|schedule)\b", re.I)
_SERVICES_LIST_RE = re.compile(
    r"\b(what services|which services|services do you|list (?:of )?services|"
    r"services (?:do you )?(?:offer|provide|have))\b",
    re.I,
)


def apply_routing_heuristics(
    *,
    message: str,
    nlu: NLUResult,
    document_catalog: list[dict[str, Any]] | None = None,
    service_catalog: list[dict[str, Any]] | None = None,
) -> NLUResult:
    """
    Mutate routing flags by returning an updated NLUResult.

    - Force SQL for known clinic ops (hours, doctors, insurance, location, pricing).
    - Force vector when message overlaps this clinic's document catalog.
    - Match this clinic's service names dynamically for price/duration/about queries.
    - Prefer knowledge/RAG for informational policy questions over booking/hours collisions.
    - Never leave needs_llm=True without needs_vector.
    """
    text = (message or "").lower()
    catalog = document_catalog or []
    services = service_catalog or []

    needs_sql = bool(nlu.needs_sql)
    needs_vector = bool(nlu.needs_vector)
    needs_llm = bool(nlu.needs_llm)
    intent = nlu.intent
    clarification_needed = bool(nlu.clarification_needed)
    can_direct = bool(nlu.can_respond_directly)
    entities = nlu.entities

    doc_hit, _ = catalog_overlap_score(message, catalog)
    knowledge_q = looks_like_knowledge_question(message)
    matched_services = match_services_in_message(message, services)
    service_hit = bool(matched_services)

    # Attach matched service name onto entities when missing (helps SQL filter)
    if matched_services and not getattr(entities, "service", None):
        try:
            from dataclasses import replace

            entities = replace(entities, service=matched_services[0].get("name"))
        except Exception:
            pass

    # Informational policy / post-op / arrival — prefer vector when docs exist.
    # Must beat duration/pricing so "how many hours without straws" ≠ service list.
    priced_named_service = bool(
        service_hit
        and re.search(r"\b(cost|price|pricing|how much does|how much is|how much for)\b", text)
    )
    if knowledge_q and catalog and not priced_named_service:
        needs_vector = True
        needs_llm = True
        intent = Intent.FAQ
        needs_sql = False
        clarification_needed = False

    # Price / duration / named service — BEFORE business hours (critical)
    elif (
        is_price_or_duration_query(message)
        or is_procedure_duration_query(message)
        or (service_hit and (looks_like_about_service(message) or is_informational(message)))
        or _SERVICES_LIST_RE.search(text)
    ) and not _INSURANCE_RE.search(text):
        if _SERVICES_LIST_RE.search(text) and not (
            is_price_or_duration_query(message) or is_procedure_duration_query(message)
        ):
            intent = Intent.SERVICES_OFFERED
        elif re.search(r"\b(cost|price|pricing|how much|fee)\b", text) or is_procedure_duration_query(message):
            intent = Intent.PRICING
        elif service_hit:
            intent = Intent.SERVICES_OFFERED
        else:
            intent = Intent.SERVICES_OFFERED
        needs_sql = True
        if doc_hit and knowledge_q and not service_hit:
            needs_vector = True
            needs_llm = True
        else:
            needs_vector = False
            needs_llm = False
        can_direct = False
        clarification_needed = False

    # Business hours only when speech-act is open/close
    elif is_business_hours_query(message) and not knowledge_q and not service_hit:
        intent = Intent.CLINIC_HOURS
        needs_sql = True
        needs_vector = False
        needs_llm = False
        can_direct = False
        clarification_needed = False
    elif _LOCATION_RE.search(text) and not _DOCTOR_RE.search(text) and not knowledge_q:
        intent = Intent.CLINIC_LOCATION
        needs_sql = True
        needs_vector = False
        needs_llm = False
        can_direct = False
    elif _DOCTOR_RE.search(text) and not _BOOK_RE.search(text) and not knowledge_q:
        intent = Intent.DOCTOR_SEARCH
        needs_sql = True
        needs_vector = False
        needs_llm = False
        can_direct = False
        clarification_needed = False
    elif _AVAIL_RE.search(text) and (
        _DOCTOR_RE.search(text) or "primary" in text or "general practice" in text
    ):
        intent = Intent.DOCTOR_AVAILABILITY
        needs_sql = True
        needs_vector = False
        needs_llm = False
        can_direct = False
    elif _INSURANCE_RE.search(text) and (
        "accept" in text or "cover" in text or "insurance" in text or "check my" in text
    ):
        if intent not in {Intent.FAQ, Intent.INSURANCE_VERIFICATION}:
            intent = Intent.INSURANCE_ACCEPTED
        needs_sql = True
        if doc_hit and knowledge_q:
            needs_vector = True
            needs_llm = True
        else:
            needs_vector = False
            needs_llm = False
        can_direct = False
        clarification_needed = False

    # Catalog overlap → vector for FAQ / explain / policy frames
    if doc_hit and intent not in {
        Intent.PRICING,
        Intent.SERVICES_OFFERED,
        Intent.CLINIC_HOURS,
        Intent.DOCTOR_SEARCH,
        Intent.DOCTOR_AVAILABILITY,
        Intent.CLINIC_LOCATION,
    }:
        if knowledge_q or intent == Intent.FAQ or "what does" in text or "explain" in text:
            needs_vector = True
            needs_llm = True
            if intent not in {
                Intent.INSURANCE_ACCEPTED,
                Intent.INSURANCE_VERIFICATION,
            }:
                intent = Intent.FAQ
                needs_sql = False

    # Booking intent only when transactional — informational "appointment" stays FAQ
    if intent == Intent.BOOK_APPOINTMENT and is_informational(message) and not is_transactional_booking(message):
        if catalog or knowledge_q:
            intent = Intent.FAQ
            needs_vector = True
            needs_llm = True
            needs_sql = False
            clarification_needed = False

    # Unknown / timed-out NLU: prefer SQL if a clinic service was named; else vector if docs
    if (
        (intent == Intent.UNKNOWN or clarification_needed)
        and not is_transactional_booking(message)
    ):
        if service_hit:
            intent = Intent.SERVICES_OFFERED
            needs_sql = True
            needs_vector = False
            needs_llm = False
            clarification_needed = False
        elif catalog:
            needs_vector = True
            needs_llm = True
            if intent == Intent.UNKNOWN:
                intent = Intent.FAQ
            clarification_needed = False

    # Contract: Large LLM only with vector
    if needs_llm and not needs_vector:
        needs_llm = False

    # Pure SQL clinic facts never need vector unless hybrid/FAQ above set it
    if intent in {
        Intent.CLINIC_HOURS,
        Intent.CLINIC_LOCATION,
        Intent.DOCTOR_SEARCH,
        Intent.DOCTOR_AVAILABILITY,
        Intent.PRICING,
        Intent.SERVICES_OFFERED,
    } and not needs_vector:
        needs_llm = False

    return NLUResult(
        intent=intent,
        secondary_intents=list(nlu.secondary_intents),
        confidence=nlu.confidence,
        entities=entities,
        resolved_ids=nlu.resolved_ids,
        needs_sql=needs_sql,
        needs_vector=needs_vector,
        needs_llm=needs_llm,
        can_respond_directly=can_direct,
        is_emergency=nlu.is_emergency,
        is_off_topic=nlu.is_off_topic,
        clarification_needed=clarification_needed,
        clarification_question=nlu.clarification_question,
        reasoning_short=(nlu.reasoning_short or "") + " | heuristics",
        provider=nlu.provider,
        model=nlu.model,
        timings=nlu.timings,
    )
