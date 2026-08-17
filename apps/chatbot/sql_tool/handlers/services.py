"""Service SQL handlers — honor service_filter_mode (none|named|category)."""

from __future__ import annotations

import re

from apps.chatbot.sql_tool.base import SQLContext, SQLResult
from apps.chatbot.sql_tool.utils import entity_ids

_GENERIC_SERVICE_TOKENS = frozenset(
    {
        "visit", "visits", "care", "basic", "level", "routine", "simple",
        "urgent", "patient", "adult", "exam", "and", "the", "for", "with",
        "a", "an", "of", "or", "service", "services", "treatment",
    }
)


def services_offered(ctx: SQLContext) -> SQLResult:
    from apps.services.models import Service

    qs = Service.objects.filter(clinic=ctx.clinic, is_deleted=False, is_active=True)
    mode = _filter_mode(ctx)

    if mode == "none":
        # Browse / list — never collapse to one fuzzy SKU
        pass
    elif mode == "named" and ctx.nlu.resolved_ids.service_id:
        qs = qs.filter(id=ctx.nlu.resolved_ids.service_id)
    elif mode == "named" and ctx.nlu.entities.service:
        qs = qs.filter(name__icontains=_service_needle(ctx.nlu.entities.service))
    elif mode == "category" and ctx.nlu.resolved_ids.service_id:
        # Same authority the mode == "named" branch above already gives
        # this signal — a confidently DB-resolved service must never be
        # silently dropped just because the raw message also read as a
        # multi-service category question (e.g. "laser treatment" can
        # both fuzzy-resolve to one service via NLU entity resolution AND
        # surface >1 raw-text hits from the message resolver).
        qs = qs.filter(id=ctx.nlu.resolved_ids.service_id)
    elif mode == "category":
        needle = _category_needle(ctx.message)
        if needle:
            qs = qs.filter(name__icontains=needle)
        else:
            # No hardcoded category phrase matched either — fall back to
            # the planner-authorized match (ExecutionPlan.resolved_service_ids,
            # computed once by the shared message resolver) instead of the
            # handler re-guessing from scratch. _match_services_strict is a
            # legacy local fallback, kept only for the case resolved_service_ids
            # is empty (e.g. call sites that bypass the planner, such as
            # SQLTool.run) so behavior never regresses to "no filter" here
            # — not something this handler should still be doing on the
            # planner-driven path (e.g. "what laser services do you have"
            # was previously surfacing every active service, Botox/filler/
            # acne included, before either fallback existed).
            #
            # Deliberately does NOT fall back to a raw entities.service
            # icontains here (unlike mode == "named" — see above): that
            # string is whatever the NLU extracted verbatim, often a
            # paraphrase (e.g. "laser treatment") rather than a literal
            # substring of any real service name, so name__icontains=
            # against it can silently match zero rows even when the
            # resolvers above/below independently found a real answer for
            # the same message.
            matched_ids = ctx.resolved_service_ids or _match_services_strict(ctx)
            if matched_ids:
                qs = qs.filter(id__in=matched_ids)
    elif ctx.nlu.resolved_ids.service_id:
        qs = qs.filter(id=ctx.nlu.resolved_ids.service_id)
    elif ctx.nlu.entities.service and mode != "none":
        qs = qs.filter(name__icontains=_service_needle(ctx.nlu.entities.service))
    else:
        # Only strict full-name matches from message — never loose token hits
        matched_ids = ctx.resolved_service_ids or _match_services_strict(ctx)
        if matched_ids and mode == "named":
            qs = qs.filter(id__in=matched_ids)

    doctor_ids = entity_ids(ctx.nlu.resolved_ids.doctor_id)
    if doctor_ids:
        qs = qs.filter(doctors__id__in=doctor_ids).distinct()

    services = list(qs.order_by("name")[:20])
    rows = [
        {
            "id": str(s.id),
            "name": s.name,
            "description": (s.description or "")[:300],
            "duration_min": s.duration_min,
            "price_cents": s.price_cents,
            "category": s.category or "",
            "price": f"${s.price_cents / 100:.2f}" if s.price_cents else "Contact for pricing",
        }
        for s in services
    ]
    if rows and len(rows) == 1 and mode == "named":
        s = rows[0]
        dur = f", about {s['duration_min']} minutes" if s.get("duration_min") else ""
        summary = f"{s['name']} is {s['price']}{dur}."
    elif rows:
        summary = f"Services offered: {', '.join(r['name'] for r in rows[:5])}."
    else:
        summary = "No services found."
    return SQLResult(
        handler="services_offered",
        found=bool(rows),
        rows=rows,
        summary=summary,
        meta={"service_filter_mode": mode},
    )


def _filter_mode(ctx: SQLContext) -> str:
    mode = getattr(ctx.nlu, "service_filter_mode", None) or "none"
    mode = str(mode).strip().lower()
    if mode not in {"none", "named", "category"}:
        # Fallback: raw payload from heuristics
        raw = getattr(ctx.nlu, "raw", None) or {}
        mode = str(raw.get("service_filter_mode") or "none").lower()
    if mode not in {"none", "named", "category"}:
        mode = "none"
    return mode


def _service_needle(value: object) -> str:
    if isinstance(value, list):
        return str(value[0] or "")
    return str(value or "")


def _category_needle(message: str) -> str:
    text = (message or "").lower()
    for phrase in (
        "urgent care",
        "primary care",
        "well child",
        "well-child",
        "cancer screening",
        "physical",
    ):
        if phrase in text:
            return phrase
    return ""


def _match_services_strict(ctx: SQLContext) -> list:
    """Full-name or ≥2 distinctive tokens only — no single generic token."""
    from apps.services.models import Service

    message = (ctx.message or "").lower()
    if not message:
        return []

    services = list(
        Service.objects.filter(
            clinic=ctx.clinic, is_deleted=False, is_active=True
        ).only("id", "name")
    )
    hits = []
    for svc in services:
        name = (svc.name or "").strip().lower()
        if len(name) < 4:
            continue
        if name in message:
            hits.append(svc.id)
            continue
        tokens = [
            t
            for t in re.findall(r"[a-z0-9]{5,}", name)
            if t not in _GENERIC_SERVICE_TOKENS
        ]
        if len(tokens) >= 2 and all(t in message for t in tokens[:2]):
            hits.append(svc.id)
        elif len(tokens) == 1 and len(tokens[0]) >= 8 and tokens[0] in message:
            hits.append(svc.id)
    return hits
