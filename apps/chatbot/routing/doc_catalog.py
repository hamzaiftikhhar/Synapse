"""Clinic document catalog for NLU vector gating."""

from __future__ import annotations

from typing import Any


def build_document_catalog(clinic: Any, *, limit: int = 12) -> list[dict[str, Any]]:
    """Load indexed/chunked docs with routing summaries for the Small NLU."""
    from apps.knowledge.models import Document, DocumentStatus

    qs = (
        Document.objects.filter(
            clinic=clinic,
            is_deleted=False,
            status__in=[DocumentStatus.INDEXED, DocumentStatus.CHUNKED],
        )
        .order_by("-updated_at")[:limit]
    )
    catalog: list[dict[str, Any]] = []
    for doc in qs:
        meta = doc.metadata if isinstance(doc.metadata, dict) else {}
        summary = (
            getattr(doc, "routing_summary", None)
            or meta.get("routing_summary")
            or meta.get("summary")
            or ""
        )
        keywords = (
            getattr(doc, "routing_keywords", None)
            or meta.get("routing_keywords")
            or meta.get("keywords")
            or []
        )
        if not isinstance(keywords, list):
            keywords = []
        if not summary:
            # Fallback: short title-based stub so router still has a signal
            summary = f"Clinic document: {doc.title}."
        catalog.append(
            {
                "id": str(doc.id),
                "title": doc.title,
                "routing_summary": summary.strip()[:280],
                "routing_keywords": [str(k)[:40] for k in keywords[:12]],
            }
        )
    return catalog


def catalog_for_nlu_context(catalog: list[dict[str, Any]]) -> str:
    """Compact multi-line catalog for the Small NLU user prompt."""
    if not catalog:
        return ""
    lines = []
    for i, doc in enumerate(catalog, start=1):
        kws = ", ".join(doc.get("routing_keywords") or [])
        lines.append(
            f"[{i}] {doc.get('title')}: {doc.get('routing_summary')}"
            + (f" keywords: {kws}" if kws else "")
        )
    return "\n".join(lines)


def matching_document_ids(message: str, catalog: list[dict[str, Any]]) -> list[str]:
    """Return document ids whose keywords/summary overlap the message."""
    text = (message or "").lower()
    hits: list[str] = []
    for doc in catalog:
        matched = False
        for kw in doc.get("routing_keywords") or []:
            if isinstance(kw, str) and kw.lower() in text:
                matched = True
                break
        if not matched:
            summary = (doc.get("routing_summary") or "").lower()
            for token in (
                "insurance",
                "cancel",
                "cancellation",
                "policy",
                "vaccination",
                "child",
                "membership",
                "copay",
                "booking",
            ):
                if token in summary and token in text:
                    matched = True
                    break
        if matched and doc.get("id"):
            hits.append(str(doc["id"]))
    return hits
