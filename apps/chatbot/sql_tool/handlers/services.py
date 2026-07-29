"""Service SQL handlers."""

from __future__ import annotations

from apps.chatbot.sql_tool.base import SQLContext, SQLResult
from apps.chatbot.sql_tool.utils import entity_ids


def services_offered(ctx: SQLContext) -> SQLResult:
    from apps.services.models import Service

    qs = Service.objects.filter(clinic=ctx.clinic, is_deleted=False, is_active=True)

    if ctx.nlu.resolved_ids.service_id:
        qs = qs.filter(id=ctx.nlu.resolved_ids.service_id)
    elif ctx.nlu.entities.service:
        qs = qs.filter(name__icontains=ctx.nlu.entities.service)

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
    summary = (
        f"Services offered: {', '.join(r['name'] for r in rows[:5])}."
        if rows
        else "No services found."
    )
    return SQLResult(handler="services_offered", found=bool(rows), rows=rows, summary=summary)
