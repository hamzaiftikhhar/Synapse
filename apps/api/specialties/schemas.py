"""Specialty API schemas."""

from datetime import datetime
from uuid import UUID

from ninja import Schema


class SpecialtyOut(Schema):
    id: UUID
    name: str
    slug: str
    description: str
    is_active: bool
    is_deleted: bool
    created_at: datetime
    updated_at: datetime


class SpecialtyIn(Schema):
    name: str
    slug: str = ""
    description: str = ""
    is_active: bool = True


class SpecialtyUpdateIn(Schema):
    name: str | None = None
    slug: str | None = None
    description: str | None = None
    is_active: bool | None = None
