"""Clinic-scoped analytics — AI usage plus operational overview/insights."""

from __future__ import annotations

from ninja import Query, Router, Schema

from apps.accounts.models import UserRole
from apps.api.analytics.ranges import parse_range
from apps.api.analytics import service as insights
from apps.api.auth.deps import clinic_from, jwt_auth
from apps.ai.services.analytics import clinic_extras, summarize_usage

router = Router(tags=["Analytics"])


class ModelUsageOut(Schema):
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    calls: int
    estimated_usd: float | None = None


class OperationUsageOut(Schema):
    operation: str
    total_tokens: int
    calls: int


class DailyUsageOut(Schema):
    date: str
    total_tokens: int
    calls: int


class RateCardOut(Schema):
    model: str
    input_usd_per_1m: float
    output_usd_per_1m: float


class ClinicAnalyticsOut(Schema):
    days: int
    show_cost: bool
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    calls: int
    cached_calls: int
    avg_latency_ms: int
    conversations: int
    chatbot_bookings: int
    estimated_usd: float | None = None
    models: list[ModelUsageOut]
    operations: list[OperationUsageOut]
    daily: list[DailyUsageOut]
    rates: list[RateCardOut] = []


def _strip_cost(summary: dict) -> dict:
    summary["estimated_usd"] = None
    summary["rates"] = []
    for row in summary["models"]:
        row["estimated_usd"] = None
    return summary


@router.get("/overview", auth=jwt_auth)
def clinic_overview(request, range: str = Query("30d")):
    clinic = clinic_from(request)
    _key, days = parse_range(range)
    return insights.overview(clinic, days=days)


@router.get("/insights", auth=jwt_auth)
def clinic_insights(request, range: str = Query("30d")):
    clinic = clinic_from(request)
    _key, days = parse_range(range)
    payload = insights.insights(clinic, days=days)
    show_cost = request.auth.role == UserRole.SUPER_ADMIN  # type: ignore[attr-defined]
    if not show_cost:
        payload["ai"] = _strip_cost(payload["ai"])
    payload["show_cost"] = show_cost
    return payload


@router.get("/breakdown", auth=jwt_auth)
def clinic_breakdown(
    request,
    dimension: str = Query(...),
    range: str = Query("30d"),
):
    clinic = clinic_from(request)
    _key, days = parse_range(range)
    return insights.breakdown(clinic, days=days, dimension=dimension)


@router.get("", response=ClinicAnalyticsOut, auth=jwt_auth)
def clinic_analytics(request, days: int = Query(30, ge=1, le=90)):
    clinic = clinic_from(request)
    show_cost = request.auth.role == UserRole.SUPER_ADMIN  # type: ignore[attr-defined]
    summary = summarize_usage(clinic_id=clinic.id, days=days)
    extras = clinic_extras(clinic_id=clinic.id, days=days)
    if not show_cost:
        summary = _strip_cost(summary)
    return ClinicAnalyticsOut(
        days=summary["days"],
        show_cost=show_cost,
        prompt_tokens=summary["prompt_tokens"],
        completion_tokens=summary["completion_tokens"],
        total_tokens=summary["total_tokens"],
        calls=summary["calls"],
        cached_calls=summary["cached_calls"],
        avg_latency_ms=summary["avg_latency_ms"],
        conversations=extras["conversations"],
        chatbot_bookings=extras["chatbot_bookings"],
        estimated_usd=summary["estimated_usd"],
        models=summary["models"],
        operations=summary["operations"],
        daily=summary["daily"],
        rates=summary["rates"],
    )
