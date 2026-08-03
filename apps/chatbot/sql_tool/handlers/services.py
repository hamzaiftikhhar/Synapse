"""Service SQL handlers."""

from __future__ import annotations

import re

from apps.chatbot.sql_tool.base import SQLContext, SQLResult
from apps.chatbot.sql_tool.utils import entity_ids


def services_offered(ctx: SQLContext) -> SQLResult:
    from apps.services.models import Service

    qs = Service.objects.filter(clinic=ctx.clinic, is_deleted=False, is_active=True)

    if ctx.nlu.resolved_ids.service_id:
        qs = qs.filter(id=ctx.nlu.resolved_ids.service_id)
    elif ctx.nlu.entities.service:
        qs = qs.filter(name__icontains=_service_needle(ctx.nlu.entities.service))
    else:
        matched_ids = _match_services_from_message(ctx)
        if matched_ids:
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
            "price": f"${s.price_cents / 100:.2f}" if s.price_cents else "Contact for pricing",
        }
        for s in services
    ]
    if rows and len(rows) == 1:
        s = rows[0]
        dur = f", about {s['duration_min']} minutes" if s.get("duration_min") else ""
        summary = f"{s['name']} is {s['price']}{dur}."
    elif rows:
        summary = f"Services offered: {', '.join(r['name'] for r in rows[:5])}."
    else:
        summary = "No services found."
    return SQLResult(handler="services_offered", found=bool(rows), rows=rows, summary=summary)


def _service_needle(value: object) -> str:
    if isinstance(value, list):
        return str(value[0] or "")
    return str(value or "")


def _match_services_from_message(ctx: SQLContext) -> list:
    """Match this clinic's service names against the user message (tenant-dynamic)."""
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
            for t in re.findall(r"[a-z0-9]{3,}", name)
            if t not in {"and", "the", "for"}
        ]
        if len(tokens) >= 2 and all(t in message for t in tokens):
            hits.append(svc.id)
        elif len(tokens) == 1 and tokens[0] in message and len(tokens[0]) >= 5:
            hits.append(svc.id)
    return hits
