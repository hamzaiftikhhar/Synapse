"""Thin post-NLU gate — safety/phatic/timeout recovery only (no second classifier)."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from apps.chatbot.nlu.entity_guard import sanitize_entities
from apps.chatbot.nlu.schemas import Intent, NLUResult
from apps.chatbot.routing.signals import (
    catalog_overlap_score,
    is_doctor_browse_query,
    is_phatic_farewell,
    is_phatic_greeting,
    is_price_or_duration_query,   
    is_service_list_query,
    is_specialty_list_query,
    is_transactional_booking,
    is_typo_book_request,
    is_unresolved_compound,
    looks_like_about_service,
    looks_like_knowledge_question,
    match_services_in_message,
    service_filter_mode as compute_service_filter_mode,
)


def apply_routing_heuristics(
    *,
    message: str,
    nlu: NLUResult,
    document_catalog: list[dict[str, Any]] | None = None,
    service_catalog: list[dict[str, Any]] | None = None,
) -> NLUResult:
    """
    Runtime sensors + safety/entity hints — not the lane owner.

    The ExecutionPlan planner ignores deprecated needs_*/sql_tool flags when
    choosing tasks. This pass may still correct speech-act semantics and attach
    entity/filter hints for downstream SQL handlers.

    Allowed:
      - Force phatic greeting/farewell / trust emergency
      - Entity hints + service_filter_mode
      - Speech-act semantic corrections (informational book → faq, etc.)

    Forbidden:
      - Owning final lane / execution routing (planner does that)
      - UNKNOWN + fuzzy service_hit → SERVICES_OFFERED
    """
    catalog = document_catalog or []
    services = service_catalog or []

    needs_sql = bool(nlu.needs_sql)
    needs_vector = bool(nlu.needs_vector)
    needs_llm = bool(nlu.needs_llm)
    intent = nlu.intent
    clarification_needed = bool(nlu.clarification_needed)
    can_direct = bool(nlu.can_respond_directly)
    entities = nlu.entities
    resolved_ids = nlu.resolved_ids
    is_emergency = bool(nlu.is_emergency) or intent == Intent.EMERGENCY

    doc_hit, _ = catalog_overlap_score(message, catalog)
    knowledge_q = looks_like_knowledge_question(message)
    matched_services = match_services_in_message(message, services)
    computed_mode = compute_service_filter_mode(message, matched_services)
    llm_mode = getattr(nlu, "service_filter_mode", None)
    raw_had_mode = isinstance(nlu.raw, dict) and "service_filter_mode" in nlu.raw

    # List/browse always wins. Strict catalog named match beats default "none".
    # Only trust LLM mode when explicitly present in raw payload.
    #
    # Phase 51 (live-confirmed): _SERVICE_LIST_RE also matches "what
    # specialt(y|ies)..." phrasing (by design, to catch "what specialties
    # do you offer" too) — but that made "what specialties do you have and
    # how much is a physical" treat the WHOLE message as a services browse,
    # clearing the already-resolved "physical" service entity and silently
    # dropping the pricing half of the compound question.
    # match_services_in_message() has the identical is_service_list_query
    # guard internally (so matched_services/computed_mode are tainted the
    # same way) — this exception is deliberately its own first-priority
    # branch, not just skipping the "none" branch below, so it never falls
    # through to a computed_mode that's already "none" for the same
    # underlying reason. A resolved service entity co-occurring with
    # explicit price/duration language is a strong signal this isn't
    # actually a browse request for THIS clause, even though the message
    # also contains browse-shaped language elsewhere — reuses the existing
    # is_price_or_duration_query() signal, not a new detector.
    if getattr(entities, "service", None) and is_price_or_duration_query(message) and is_service_list_query(message):
        filter_mode = "named"
    elif is_service_list_query(message):
        filter_mode = "none"
    elif computed_mode == "named" and matched_services:
        filter_mode = "named"
    elif raw_had_mode and llm_mode in {"named", "category", "none"}:
        filter_mode = llm_mode
    else:
        filter_mode = computed_mode

    if filter_mode == "named" and matched_services and not getattr(entities, "service", None):
        entities = replace(entities, service=matched_services[0].get("name"))
    if filter_mode == "none":
        entities = replace(entities, service=None)
        if resolved_ids.service_id:
            resolved_ids = replace(resolved_ids, service_id=None)

    raw = dict(nlu.raw or {})
    raw["service_filter_mode"] = filter_mode

    if is_phatic_greeting(message):
        return _result(
            nlu,
            intent=Intent.GREETING,
            confidence=max(float(nlu.confidence or 0), 0.95),
            entities=entities,
            needs_sql=False,
            needs_vector=False,
            needs_llm=False,
            can_direct=True,
            clarification_needed=False,
            is_emergency=False,
            note="phatic_greeting",
            raw=raw,
            filter_mode=filter_mode,
        )
    if is_phatic_farewell(message):
        return _result(
            nlu,
            intent=Intent.FAREWELL,
            confidence=max(float(nlu.confidence or 0), 0.95),
            entities=entities,
            needs_sql=False,
            needs_vector=False,
            needs_llm=False,
            can_direct=True,
            clarification_needed=False,
            is_emergency=False,
            note="phatic_farewell",
            raw=raw,
            filter_mode=filter_mode,
        )

    if is_emergency:
        return _result(
            nlu,
            intent=Intent.EMERGENCY,
            confidence=max(float(nlu.confidence or 0), 0.95),
            entities=entities,
            needs_sql=False,
            needs_vector=False,
            needs_llm=False,
            can_direct=True,
            clarification_needed=False,
            is_emergency=True,
            note="emergency_trust",
            raw=raw,
            filter_mode=filter_mode,
        )

    # Nano hallucinates view_appointments / unknown on 2-word typos of "book me".
    # Message shape wins: never dump an appointment list from a garbled book.
    if is_typo_book_request(message) and intent not in {
        Intent.CANCEL_APPOINTMENT,
        Intent.RESCHEDULE_APPOINTMENT,
        Intent.EMERGENCY,
    }:
        intent = Intent.BOOK_APPOINTMENT
        needs_sql = False
        needs_vector = False
        needs_llm = False
        clarification_needed = False
        can_direct = False
        raw["sql_tool"] = None

    if is_specialty_list_query(message) and intent in {
        Intent.UNKNOWN,
        Intent.SERVICES_OFFERED,
        Intent.FAQ,
        Intent.DOCTOR_SEARCH,
    }:
        intent = Intent.DOCTOR_SEARCH
        needs_sql = True
        needs_vector = False
        needs_llm = False
        clarification_needed = False
        can_direct = False
        raw["sql_tool_hint"] = "specialties"
        raw["sql_tool"] = "specialties"

    if is_service_list_query(message) and intent in {
        Intent.SERVICES_OFFERED,
        Intent.PRICING,
        Intent.UNKNOWN,
    }:
        intent = Intent.SERVICES_OFFERED
        needs_sql = True
        needs_vector = False
        needs_llm = False
        clarification_needed = False
        can_direct = False
        entities = replace(entities, service=None)
        if resolved_ids.service_id:
            resolved_ids = replace(resolved_ids, service_id=None)
        filter_mode = "none"
        raw["service_filter_mode"] = "none"

    # Policy / membership / cancel-fee frames → vector when docs exist.
    # Does NOT overwrite intent to FAQ: build_execution_plan() (planner.py)
    # independently attaches the vector task from facts.knowledge_q, and
    # _INTENT_SQL_TASKS needs the real intent (PRICING/SERVICES_OFFERED/
    # CLINIC_HOURS) to still attach the matching SQL task alongside it —
    # overwriting to FAQ here used to erase that lookup for no routing
    # benefit (needs_vector/needs_sql below are informational only; the
    # planner ignores them — see build_execution_plan's docstring).
    if (
        knowledge_q
        and catalog
        and intent
        in {
            Intent.PRICING,
            Intent.SERVICES_OFFERED,
            Intent.UNKNOWN,
            Intent.FAQ,
            Intent.CLINIC_HOURS,
        }
    ):
        needs_vector = True
        needs_llm = True
        needs_sql = False
        clarification_needed = False

    if intent == Intent.BOOK_APPOINTMENT and not is_transactional_booking(message):
        # Phase 51 (live-confirmed hallucination): "can I grab an
        # appointment with Dr. Vance" has doctor_id already resolved by
        # this point, but "grab" isn't in _TRANSACTIONAL_BOOK_RE's verb
        # list, so this block used to unconditionally fall through to FAQ
        # below — sending a message about a real, resolved doctor into the
        # vector/RAG lane, which has no doctor-roster data source and
        # free-generated "Dr. Vance is not listed among our providers,"
        # fabricating the non-existence of a real doctor. A resolved
        # doctor/service entity means a deterministic SQL lookup already
        # exists for this — strictly safer than free generation, and still
        # helpful (shows the real doctor/service, with the existing "Book
        # Appointment" chip to continue). Only falls through to FAQ when
        # genuinely no concrete entity is resolved.
        if resolved_ids.doctor_id or entities.doctor_name:
            intent = Intent.DOCTOR_SEARCH
            needs_sql = True
            needs_vector = False
            needs_llm = False
            clarification_needed = False
        elif resolved_ids.service_id or entities.service:
            intent = Intent.SERVICES_OFFERED
            needs_sql = True
            needs_vector = False
            needs_llm = False
            clarification_needed = False
        elif catalog or knowledge_q:
            # Overwrite to FAQ IS load-bearing here (unlike the blocks
            # above): leaving intent=BOOK_APPOINTMENT can make
            # compute_message_sensors' is_booking_intent check true via its
            # booking_commit/pending_uptake_booking paths and wrongly launch
            # the booking wizard for a non-transactional "do you take
            # bookings on Saturdays"-style question.
            intent = Intent.FAQ
            needs_vector = True
            needs_llm = True
            needs_sql = False
            clarification_needed = False

    # Timeout / unknown recovery (strict only — never fuzzy service_hit → SQL)
    if intent == Intent.UNKNOWN and not is_transactional_booking(message):
        if (knowledge_q and catalog) or (doc_hit and knowledge_q):
            needs_vector = True
            needs_llm = True
            needs_sql = False
            clarification_needed = False
        elif (
            filter_mode == "named"
            and matched_services
            and (is_price_or_duration_query(message) or looks_like_about_service(message))
            and not is_unresolved_compound(nlu, message)
        ):
            intent = (
                Intent.PRICING
                if is_price_or_duration_query(message)
                else Intent.SERVICES_OFFERED
            )
            needs_sql = True
            needs_vector = False
            needs_llm = False
            clarification_needed = False

    if needs_llm and not needs_vector:
        needs_llm = False

    if is_doctor_browse_query(message):
        entities = replace(entities, specialty=None, service=None)
        resolved_ids = replace(
            resolved_ids,
            specialty_id=None,
            service_id=None,
        )

    entities = sanitize_entities(message, entities)

    return _result(
        nlu,
        intent=intent,
        confidence=nlu.confidence,
        entities=entities,
        resolved_ids=resolved_ids,
        needs_sql=needs_sql,
        needs_vector=needs_vector,
        needs_llm=needs_llm,
        can_direct=can_direct,
        clarification_needed=clarification_needed,
        is_emergency=is_emergency,
        note="heuristics_thin",
        raw=raw,
        filter_mode=filter_mode,
    )


def _result(
    nlu: NLUResult,
    *,
    intent: Intent,
    confidence: float,
    entities: Any,
    needs_sql: bool,
    needs_vector: bool,
    needs_llm: bool,
    can_direct: bool,
    clarification_needed: bool,
    is_emergency: bool,
    note: str,
    raw: dict[str, Any],
    filter_mode: str = "none",
    resolved_ids: Any = None,
) -> NLUResult:
    return NLUResult(
        intent=intent,
        secondary_intents=list(nlu.secondary_intents),
        confidence=confidence,
        entities=entities,
        resolved_ids=resolved_ids if resolved_ids is not None else nlu.resolved_ids,
        needs_sql=needs_sql,
        needs_vector=needs_vector,
        needs_llm=needs_llm,
        can_respond_directly=can_direct,
        is_emergency=is_emergency,
        is_off_topic=nlu.is_off_topic,
        clarification_needed=clarification_needed,
        clarification_question=nlu.clarification_question if clarification_needed else None,
        reasoning_short=(nlu.reasoning_short or "") + f" | {note}",
        service_filter_mode=filter_mode,
        sql_tool=raw.get("sql_tool") or raw.get("sql_tool_hint") or nlu.sql_tool,
        document_needed=bool(
            nlu.document_needed or (needs_vector and intent == Intent.FAQ)
        ),
        provider=nlu.provider,
        model=nlu.model,
        timings=nlu.timings,
        raw=raw,
    )
