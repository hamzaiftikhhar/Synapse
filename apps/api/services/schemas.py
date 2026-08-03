"""Service API schemas."""

from datetime import datetime
from uuid import UUID

from ninja import Schema


class ServiceOut(Schema):
    id: UUID
    name: str
    description: str
    code: str = ""
    category: str = ""
    duration_min: int
    price_cents: int | None
    is_active: bool
    is_deleted: bool
    metadata: dict = {}
    created_at: datetime
    updated_at: datetime


class ServiceIn(Schema):
    name: str
    description: str = ""
    code: str = ""
    category: str = ""
    duration_min: int = 30
    price_cents: int | None = None
    is_active: bool = True
    metadata: dict | None = None


class ServiceUpdateIn(Schema):
    name: str | None = None
    description: str | None = None
    code: str | None = None
    category: str | None = None
    duration_min: int | None = None
    price_cents: int | None = None
    is_active: bool | None = None
    metadata: dict | None = None
