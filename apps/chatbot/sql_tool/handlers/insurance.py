"""Insurance SQL handlers."""

from __future__ import annotations

import re

from django.db.models import Q

from apps.chatbot.sql_tool.base import SQLContext, SQLResult
from apps.chatbot.sql_tool.utils import entity_ids, entity_list


def insurance_accepted(ctx: SQLContext) -> SQLResult:
    from apps.insurance.models import InsurancePlan

    clinic = ctx.clinic
    nlu = ctx.nlu
    providers = entity_list(nlu.entities.insurance_provider)
    plan_ids = entity_ids(nlu.resolved_ids.insurance_plan_id)
    doctor_ids = entity_ids(nlu.resolved_ids.doctor_id)

    # Dynamic: match provider names from this clinic's catalog against the message
    if not providers and not plan_ids and ctx.message:
        providers = _match_providers_from_message(clinic, ctx.message)

    base = InsurancePlan.objects.filter(clinic=clinic, is_deleted=False)
    if doctor_ids:
        base = base.filter(doctor_insurances__doctor_id__in=doctor_ids).distinct()

    # Phase 41 — "Aetna HMO" and "Aetna PPO" used to return the identical
    # row (reproduced live: both questions returned "Yes — we accept Aetna
    # (HMO Plus)."). Two stacked causes, both needing a fix here: (1)
    # provider-name matching alone ignores plan_type entirely, so any
    # accepted plan for the provider "answers" a question about a
    # different type; (2) resolve_entities's own plan_id resolution
    # (_match_insurance) isn't plan-type aware either — with two same-
    # provider plans it can silently resolve to the wrong one via tie-
    # breaking, and that resolved plan_ids then bypassed type-checking
    # entirely in an earlier version of this fix. So: whenever the message
    # names a specific type, match by provider text (not the possibly-
    # wrong resolved plan_ids) and let the type filter pick the right row.
    requested_plan_type = _requested_plan_type(ctx.message)
    plan_type_mismatch = False
    if requested_plan_type and providers:
        provider_q = Q()
        for provider in providers:
            provider_q |= Q(provider_name__icontains=provider) | Q(plan_name__icontains=provider)
        candidates = list(base.filter(provider_q).order_by("-is_accepted", "provider_name")[:20])
        exact = [
            p for p in candidates if (p.plan_type or "").strip().upper() == requested_plan_type
        ]
        if exact:
            plans = exact
        elif candidates:
            plans = candidates
            plan_type_mismatch = True
        else:
            plans = []
    # Named provider/plan → include rejected rows so we can say "we do not accept X"
    elif plan_ids or providers:
        qs = base
        if plan_ids:
            qs = qs.filter(id__in=plan_ids)
        else:
            q = Q()
            for provider in providers:
                q |= Q(provider_name__icontains=provider) | Q(plan_name__icontains=provider)
            qs = qs.filter(q)
        plans = list(qs.order_by("-is_accepted", "provider_name")[:12])
    else:
        # Browse mode: accepted plans only
        plans = list(
            base.filter(is_accepted=True).order_by("provider_name")[:12]
        )

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

    accepted = [r for r in rows if r.get("is_accepted")]
    rejected = [r for r in rows if not r.get("is_accepted")]

    def _label(r: dict) -> str:
        return r["provider_name"] + (
            f" ({r['plan_name']})" if r.get("plan_name") else ""
        )

    if plan_type_mismatch:
        # rows[0]["provider_name"] is the real DB value, never the raw NLU
        # entity text — which can itself be "Aetna PPO" (the whole phrase),
        # producing an awkward "Aetna PPO PPO plan" if used directly here.
        provider_label = rows[0]["provider_name"] if rows else "that provider"
        if accepted:
            names = ", ".join(_label(r) for r in accepted[:3])
            summary = (
                f"We don't see a {provider_label} {requested_plan_type} plan on file, "
                f"but we do accept {names}."
            )
        else:
            summary = (
                f"We don't see a {provider_label} {requested_plan_type} plan on file. "
                "Please call the clinic to verify coverage."
            )
    elif providers and rejected and not accepted:
        names = ", ".join(_label(r) for r in rejected[:5])
        notes = next((r["notes"] for r in rejected if r.get("notes")), "")
        summary = f"No — we currently don't accept {names}."
        if notes:
            summary += f" {notes}"
        else:
            summary += " Please ask about fee-for-service options or call the clinic."
    elif providers and accepted:
        names = ", ".join(_label(r) for r in accepted[:5])
        summary = f"Yes — we accept {names}."
        if rejected:
            summary += (
                " We currently don't accept "
                + ", ".join(_label(r) for r in rejected[:3])
                + "."
            )
    elif accepted:
        names = ", ".join(_label(r) for r in accepted[:8])
        summary = f"We accept plans including: {names}."
    else:
        provider_hint = f" for {providers[0]}" if providers else ""
        summary = (
            f"I don't see a matching accepted plan{provider_hint} in our records. "
            "Please call the clinic to verify coverage."
        )

    return SQLResult(
        handler="insurance_accepted",
        found=bool(accepted) or bool(rejected and providers),
        rows=rows,
        summary=summary,
    )


_PLAN_TYPE_RE = re.compile(r"\b(HMO|PPO|EPO|POS|HDHP)\b", re.I)


def _requested_plan_type(message: str | None) -> str | None:
    """A closed, enumerable set of US plan-type abbreviations — deterministic
    Python extraction, not an NLU entity, since there's nothing semantic to
    interpret here."""
    match = _PLAN_TYPE_RE.search(message or "")
    return match.group(1).upper() if match else None


def _match_providers_from_message(clinic, message: str) -> list[str]:
    """Match insurance provider strings from this clinic's plans (tenant-dynamic)."""
    from apps.insurance.models import InsurancePlan

    text = (message or "").lower()
    if not text:
        return []
    text_compact = re.sub(r"[^a-z0-9]", "", text)
    names = (
        InsurancePlan.objects.filter(clinic=clinic, is_deleted=False)
        .values_list("provider_name", flat=True)
        .distinct()
    )
    hits: list[str] = []
    for name in names:
        n = (name or "").strip()
        if len(n) < 3:
            continue
        lower = n.lower()
        if lower in text:
            hits.append(n)
            continue
        # Hyphen/slash segments: "Medi-Cal / Denti-Cal" → match "medi-cal"
        for part in re.split(r"[/|,]", lower):
            part = part.strip()
            if len(part) >= 4 and part in text:
                hits.append(n)
                break
        else:
            compact = re.sub(r"[^a-z0-9]", "", lower)
            if len(compact) >= 5 and compact in text_compact:
                hits.append(n)
                continue
            tokens = [t for t in re.findall(r"[a-z0-9]{4,}", lower)]
            if len(tokens) >= 2 and all(t in text for t in tokens[:2]):
                hits.append(n)
    return hits
