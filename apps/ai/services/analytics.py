"""AIUsageLog aggregations for clinic + platform analytics."""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from django.db.models import Avg, Count, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from apps.ai.models import AIUsageLog
from apps.ai.pricing import estimate_usd, known_rate_cards


def _since(days: int):
    return timezone.now() - timedelta(days=max(1, min(days, 90)))


def _base_qs(*, clinic_id: UUID | None, days: int):
    qs = AIUsageLog.objects.filter(created_at__gte=_since(days))
    if clinic_id is not None:
        qs = qs.filter(clinic_id=clinic_id)
    return qs


def _cost(model: str, prompt: int, completion: int) -> float:
    return estimate_usd(model=model, prompt_tokens=prompt, completion_tokens=completion)


def summarize_usage(*, clinic_id: UUID | None = None, days: int = 30) -> dict:
    qs = _base_qs(clinic_id=clinic_id, days=days)
    totals = qs.aggregate(
        prompt=Sum("prompt_tokens"),
        completion=Sum("completion_tokens"),
        tokens=Sum("total_tokens"),
        calls=Count("id"),
        avg_latency=Avg("latency_ms"),
        cached=Count("id", filter=Q(cached_response=True)),
    )

    prompt = int(totals["prompt"] or 0)
    completion = int(totals["completion"] or 0)
    tokens = int(totals["tokens"] or 0) or (prompt + completion)
    calls = int(totals["calls"] or 0)

    models = []
    estimated_usd = 0.0
    for row in qs.values("model").annotate(
        prompt=Sum("prompt_tokens"),
        completion=Sum("completion_tokens"),
        tokens=Sum("total_tokens"),
        calls=Count("id"),
    ):
        p = int(row["prompt"] or 0)
        c = int(row["completion"] or 0)
        t = int(row["tokens"] or 0) or (p + c)
        cost = _cost(row["model"], p, c)
        estimated_usd += cost
        models.append(
            {
                "model": row["model"],
                "prompt_tokens": p,
                "completion_tokens": c,
                "total_tokens": t,
                "calls": int(row["calls"] or 0),
                "estimated_usd": round(cost, 6),
            }
        )
    models.sort(key=lambda m: m["total_tokens"], reverse=True)

    operations = [
        {
            "operation": row["operation"],
            "total_tokens": int(row["tokens"] or 0),
            "calls": int(row["calls"] or 0),
        }
        for row in qs.values("operation").annotate(
            tokens=Sum("total_tokens"), calls=Count("id")
        )
    ]
    operations.sort(key=lambda o: o["total_tokens"], reverse=True)

    daily = [
        {
            "date": row["day"].isoformat() if row["day"] else "",
            "total_tokens": int(row["tokens"] or 0),
            "calls": int(row["calls"] or 0),
        }
        for row in qs.annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(tokens=Sum("total_tokens"), calls=Count("id"))
        .order_by("day")
    ]

    return {
        "days": days,
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": tokens,
        "calls": calls,
        "cached_calls": int(totals["cached"] or 0),
        "avg_latency_ms": int(round(totals["avg_latency"] or 0)),
        "estimated_usd": round(estimated_usd, 6),
        "models": models,
        "operations": operations,
        "daily": daily,
        "rates": known_rate_cards(),
    }


def clinic_extras(*, clinic_id: UUID, days: int) -> dict:
    from apps.appointments.models import Appointment, AppointmentSource
    from apps.chatbot.models import ChatSession

    since = _since(days)
    return {
        "conversations": ChatSession.objects.filter(
            clinic_id=clinic_id, created_at__gte=since
        ).count(),
        "chatbot_bookings": Appointment.objects.filter(
            clinic_id=clinic_id,
            created_at__gte=since,
            source=AppointmentSource.CHATBOT,
        ).count(),
    }


def platform_by_clinic(*, days: int = 30) -> list[dict]:
    qs = _base_qs(clinic_id=None, days=days)
    grouped = qs.values("clinic_id", "clinic__name", "clinic__slug", "model").annotate(
        prompt=Sum("prompt_tokens"),
        completion=Sum("completion_tokens"),
        tokens=Sum("total_tokens"),
        calls=Count("id"),
    )
    buckets: dict[str, dict] = {}
    for row in grouped:
        cid = str(row["clinic_id"])
        bucket = buckets.get(cid)
        if bucket is None:
            bucket = {
                "clinic_id": cid,
                "name": row["clinic__name"],
                "slug": row["clinic__slug"],
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "calls": 0,
                "estimated_usd": 0.0,
            }
            buckets[cid] = bucket
        p = int(row["prompt"] or 0)
        c = int(row["completion"] or 0)
        t = int(row["tokens"] or 0) or (p + c)
        bucket["prompt_tokens"] += p
        bucket["completion_tokens"] += c
        bucket["total_tokens"] += t
        bucket["calls"] += int(row["calls"] or 0)
        bucket["estimated_usd"] += _cost(row["model"], p, c)

    out = list(buckets.values())
    for row in out:
        row["estimated_usd"] = round(row["estimated_usd"], 6)
    out.sort(key=lambda r: r["total_tokens"], reverse=True)
    return out
