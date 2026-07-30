"""Tiered chat routing — lanes, heuristics, document catalog."""

from apps.chatbot.routing.lanes import Lane, resolve_lane
from apps.chatbot.routing.heuristics import apply_routing_heuristics
from apps.chatbot.routing.doc_catalog import (
    build_document_catalog,
    catalog_for_nlu_context,
    matching_document_ids,
)

__all__ = [
    "Lane",
    "resolve_lane",
    "apply_routing_heuristics",
    "build_document_catalog",
    "catalog_for_nlu_context",
    "matching_document_ids",
]
