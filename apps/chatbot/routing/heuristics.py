"""Hybrid keyword heuristics applied after rules/NLU."""

from __future__ import annotations

import re
from typing import Any

from apps.chatbot.nlu.schemas import Intent, NLUResult


_HOURS_RE = re.compile(
    r"\b(hours?|open|close|closing|when are you open)\b", re.I
)
_LOCATION_RE = re.compile(
    r"\b(where|address|location|directions|map|parking)\b", re.I
)
_DOCTOR_RE = re.compile(
    r"\b(find (a |the )?doctor|help me find a doctor|list (of )?doctors|"
    r"who (are|is) (your|the) doctor|show (me )?(doctors|physicians)|"
    r"cardiologist|dermatologist|neurologist|primary care)\b",
    re.I,
)
_INSURANCE_RE = re.compile(
    r"\b(insurance|aetna|cigna|medicare|medicaid|blue\s*cross|humana|"
    r"accept(ed|s)?|coverage|copay)\b",
    re.I,
)
_AVAIL_RE = re.compile(
    r"\b(available|availability|earliest|tomorrow|today|slot|slots)\b", re.I
)
_BOOK_RE = re.compile(r"\b(book|schedule|appointment)\b", re.I)


def apply_routing_heuristics(
    *,
    message: str,
    nlu: NLUResult,
    document_catalog: list[dict[str, Any]] | None = None,
) -> NLUResult:
    """
    Mutate routing flags on a copy-like basis by returning an updated NLUResult.

    - Force SQL for known clinic ops (hours, doctors, insurance, location).
    - Force vector only when message overlaps document catalog keywords/summary.
    - Never leave needs_llm=True without needs_vector.
    """
    text = (message or "").lower()
    catalog = document_catalog or []

    needs_sql = bool(nlu.needs_sql)
    needs_vector = bool(nlu.needs_vector)
    needs_llm = bool(nlu.needs_llm)
    intent = nlu.intent
    clarification_needed = bool(nlu.clarification_needed)
    can_direct = bool(nlu.can_respond_directly)

    # SQL-known intents
    if _HOURS_RE.search(text):
        intent = Intent.CLINIC_HOURS
        needs_sql = True
        needs_vector = False
        needs_llm = False
        can_direct = False
        clarification_needed = False
    elif _LOCATION_RE.search(text) and not _DOCTOR_RE.search(text):
        intent = Intent.CLINIC_LOCATION
        needs_sql = True
        needs_vector = False
        needs_llm = False
        can_direct = False
    elif _DOCTOR_RE.search(text) and not _BOOK_RE.search(text):
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
        "accept" in text or "cover" in text or "insurance" in text
    ):
        # Prefer SQL for accept/coverage; document policies still can match below
        if intent not in {Intent.FAQ, Intent.INSURANCE_VERIFICATION}:
            intent = Intent.INSURANCE_ACCEPTED
        needs_sql = True
        # Only vector if catalog says policy PDF
        needs_vector = False
        needs_llm = False
        can_direct = False

    # Document catalog overlap → vector
    doc_hit = _catalog_overlap(text, catalog)
    if doc_hit:
        # Policy/FAQ docs beat SQL-only for cancellation/policy questions
        if any(
            k in text
            for k in (
                "policy",
                "cancel",
                "cancellation",
                "refund",
                "package",
                "include",
                "membership",
                "contract",
            )
        ):
            needs_vector = True
            needs_llm = True
            if intent not in {Intent.INSURANCE_ACCEPTED, Intent.INSURANCE_VERIFICATION}:
                intent = Intent.FAQ
        elif intent == Intent.FAQ or "what does" in text or "explain" in text:
            needs_vector = True
            needs_llm = True

    # Contract: Large LLM only with vector
    if needs_llm and not needs_vector:
        needs_llm = False

    # SQL clinic facts never need vector unless FAQ/policy above set it
    if intent in {
        Intent.CLINIC_HOURS,
        Intent.CLINIC_LOCATION,
        Intent.DOCTOR_SEARCH,
        Intent.DOCTOR_AVAILABILITY,
        Intent.SERVICES_OFFERED,
    } and intent != Intent.FAQ:
        if not doc_hit or intent in {
            Intent.CLINIC_HOURS,
            Intent.CLINIC_LOCATION,
            Intent.DOCTOR_SEARCH,
            Intent.DOCTOR_AVAILABILITY,
        }:
            needs_vector = False
            needs_llm = False

    return NLUResult(
        intent=intent,
        secondary_intents=list(nlu.secondary_intents),
        confidence=nlu.confidence,
        entities=nlu.entities,
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


def _catalog_overlap(text: str, catalog: list[dict[str, Any]]) -> bool:
    for doc in catalog:
        summary = (doc.get("routing_summary") or doc.get("summary") or "").lower()
        keywords = doc.get("routing_keywords") or doc.get("keywords") or []
        title = (doc.get("title") or "").lower()
        for kw in keywords:
            if isinstance(kw, str) and kw.lower() in text:
                return True
        # Loose summary token overlap (significant words)
        for token in re.findall(r"[a-z]{4,}", summary + " " + title):
            if token in {
                "insurance",
                "coverage",
                "copay",
                "cancel",
                "cancellation",
                "booking",
                "policy",
                "vaccination",
                "pediatric",
                "child",
                "membership",
                "pricing",
                "refund",
            } and token in text:
                return True
    return False
