"""Audit log helpers."""

from __future__ import annotations

from typing import Any

from apps.accounts.models import AuditLog


def write_audit(
    *,
    action: str,
    actor=None,
    clinic=None,
    object_type: str = "",
    object_id: str = "",
    metadata: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> AuditLog:
    return AuditLog.objects.create(
        actor=actor,
        clinic=clinic,
        action=action,
        object_type=object_type,
        object_id=str(object_id) if object_id else "",
        metadata=metadata or {},
        ip_address=ip_address,
    )
