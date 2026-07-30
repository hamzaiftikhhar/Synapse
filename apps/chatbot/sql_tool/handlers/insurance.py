"""Insurance SQL handlers."""

from __future__ import annotations

from django.db.models import Q

from apps.chatbot.sql_tool.base import SQLContext, SQLResult
from apps.chatbot.sql_tool.utils import entity_ids, entity_list


def insurance_accepted(ctx: SQLContext) -> SQLResult:
    from apps.insurance.models import InsurancePlan

    clinic = ctx.clinic
    nlu = ctx.nlu
    qs = InsurancePlan.objects.filter(clinic=clinic, is_deleted=False, is_accepted=True)

    plan_ids = entity_ids(nlu.resolved_ids.insurance_plan_id)
    if plan_ids:
        qs = qs.filter(id__in=plan_ids)
    else:
        providers = entity_list(nlu.entities.insurance_provider)
        if providers:
            q = Q()
            for provider in providers:
                q |= Q(provider_name__icontains=provider) | Q(plan_name__icontains=provider)
            qs = qs.filter(q)

    doctor_ids = entity_ids(nlu.resolved_ids.doctor_id)
    if doctor_ids:
        qs = qs.filter(doctor_insurances__doctor_id__in=doctor_ids).distinct()

    plans = list(qs[:3])
    rows = [
        {
            "id": str(p.id),
            "provider_name": p.provider_name,
            "plan_name": p.plan_name,
            "plan_type": p.plan_type,
            "is_accepted": p.is_accepted,
            "notes": (p.notes or "")[:200],
        }
        for p in plans
    ]

    if rows:
        names = ", ".join(
            r["provider_name"] + (f" ({r['plan_name']})" if r.get("plan_name") else "")
            for r in rows
        )
        providers = entity_list(nlu.entities.insurance_provider)
        if providers:
            summary = f"Yes — we accept {names}."
        else:
            summary = f"We accept plans including: {names}."
    else:
        provider_hint = ""
        providers = entity_list(nlu.entities.insurance_provider)
        if providers:
            provider_hint = f" for {providers[0]}"
        summary = (
            f"I don't see a matching accepted plan{provider_hint} in our records. "
            "Please call the clinic to verify coverage."
        )

    return SQLResult(handler="insurance_accepted", found=bool(rows), rows=rows, summary=summary)
