"""Insurance plan API schemas."""

from datetime import datetime
from uuid import UUID

from ninja import Schema


class InsurancePlanOut(Schema):
    id: UUID
    provider_name: str
    plan_name: str
    plan_type: str
    is_accepted: bool
    notes: str
    is_deleted: bool
    created_at: datetime
    updated_at: datetime


class InsurancePlanIn(Schema):
    provider_name: str
    plan_name: str = ""
    plan_type: str = ""
    is_accepted: bool = True
    notes: str = ""


class InsurancePlanUpdateIn(Schema):
    provider_name: str | None = None
    plan_name: str | None = None
    plan_type: str | None = None
    is_accepted: bool | None = None
    notes: str | None = None
