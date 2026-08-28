"""Clinic document catalog for NLU vector gating."""

from __future__ import annotations

from typing import Any

from apps.chatbot.routing.signals import catalog_overlap_score


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
    _, hits = catalog_overlap_score(message, catalog)
    return hits


def build_service_catalog(clinic: Any, *, limit: int = 40) -> list[dict[str, Any]]:
    """Active services for this clinic — used to match free-text service questions."""
    try:
        from apps.services.models import Service

        clinic_id = getattr(clinic, "id", None)
        if clinic_id is None:
            return []
        qs = (
            Service.objects.filter(clinic_id=clinic_id, is_deleted=False, is_active=True)
            .order_by("name")[:limit]
        )
        return [{"id": str(s.id), "name": s.name} for s in qs]
    except Exception:
        return []


def build_doctor_catalog(clinic: Any, *, limit: int = 40) -> list[dict[str, Any]]:
    """Active doctors for this clinic — grounds the Small NLU's doctor_name
    extraction and intent classification against who's actually on staff.

    Phase 41: without this, the NLU had no way to tell a real doctor's bare
    first name ("Priya") from a patient's name, and no way to recognize a
    two-doctor mention ("Priya and Omar") as being about doctors at all —
    reproduced live: "Tell me about Priya and Omar" extracted
    patient_name="Priya", doctor_name=null, and classified off_topic.
    """
    try:
        from apps.doctors.models import Doctor

        clinic_id = getattr(clinic, "id", None)
        if clinic_id is None:
            return []
        qs = (
            Doctor.objects.filter(
                clinic_id=clinic_id, is_deleted=False, is_active=True
            )
            .prefetch_related("specialties")
            .order_by("full_name")[:limit]
        )
        return [
            {
                "id": str(d.id),
                "full_name": d.full_name,
                "specialty": next(
                    (s.name for s in d.specialties.all()), ""
                ),
            }
            for d in qs
        ]
    except Exception:
        return []
