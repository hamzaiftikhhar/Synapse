"""Thin post-NLU gate — safety/phatic/timeout recovery only (no second classifier)."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from apps.chatbot.nlu.schemas import Intent, NLUResult
from apps.chatbot.routing.signals import (
    catalog_overlap_score,
    is_phatic_farewell,
    is_phatic_greeting,
    is_price_or_duration_query,
    is_service_list_query,
    is_specialty_list_query,
    is_transactional_booking,
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
    if is_service_list_query(message):
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

    # Policy / membership / cancel-fee frames → vector when docs exist
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
        intent = Intent.FAQ
        needs_vector = True
        needs_llm = True
        needs_sql = False
        clarification_needed = False

    if intent == Intent.BOOK_APPOINTMENT and not is_transactional_booking(message):
        if catalog or knowledge_q:
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
            intent = Intent.FAQ
            needs_sql = False
            clarification_needed = False
        elif filter_mode == "named" and matched_services and (
            is_price_or_duration_query(message) or looks_like_about_service(message)
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
