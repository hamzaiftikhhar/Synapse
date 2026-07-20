"""Shared API schemas and helpers."""

from datetime import date, datetime
from typing import Generic, TypeVar
from uuid import UUID

from ninja import Schema

T = TypeVar("T")


class MessageOut(Schema):
    detail: str


class PaginatedOut(Schema, Generic[T]):
    count: int
    results: list[T]


class TimestampedSchema(Schema):
    created_at: datetime
    updated_at: datetime


def tenant_filter(qs, clinic_id: UUID):
    """Shortcut — every tenant queryset starts here."""
    return qs.filter(clinic_id=clinic_id)
