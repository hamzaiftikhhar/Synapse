"""Tiered chat routing — lanes, heuristics, confidence, document catalog."""

from apps.chatbot.routing.lanes import HYBRID_SQL_INTENTS, Lane, resolve_lane
from apps.chatbot.routing.heuristics import apply_routing_heuristics
from apps.chatbot.routing.confidence import (
    ConfidenceBand,
    apply_confidence_policy,
    confidence_meta,
)
from apps.chatbot.routing.doc_catalog import (
    build_document_catalog,
    build_service_catalog,
    catalog_for_nlu_context,
    matching_document_ids,
)
from apps.chatbot.routing.signals import (
    has_symptom_cues,
    is_service_list_query,
    is_specialty_list_query,
    is_transactional_booking,
    looks_like_knowledge_question,
    match_services_in_message,
    service_filter_mode,
)

__all__ = [
    "HYBRID_SQL_INTENTS",
    "Lane",
    "resolve_lane",
    "apply_routing_heuristics",
    "ConfidenceBand",
    "apply_confidence_policy",
    "confidence_meta",
    "build_document_catalog",
    "build_service_catalog",
    "catalog_for_nlu_context",
    "matching_document_ids",
    "is_transactional_booking",
    "looks_like_knowledge_question",
    "match_services_in_message",
    "has_symptom_cues",
    "is_service_list_query",
    "is_specialty_list_query",
    "service_filter_mode",
]
