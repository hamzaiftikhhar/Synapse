"""JWT encode/decode — staff (portal) and patient (widget) token families.

Staff tokens: type staff_access | staff_refresh
Patient tokens: type patient_access (short-lived, OTP-issued)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

import jwt
from django.conf import settings
from ninja.errors import HttpError

StaffTokenType = Literal["staff_access", "staff_refresh"]
PatientTokenType = Literal["patient_access"]


@dataclass(frozen=True)
class StaffTokenPayload:
    user_id: int
    clinic_id: UUID | None
    role: str
    token_type: StaffTokenType
    exp: datetime

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StaffTokenPayload:
        clinic_raw = data.get("clinic_id")
        return cls(
            user_id=int(data["sub"]),
            clinic_id=UUID(str(clinic_raw)) if clinic_raw else None,
            role=str(data["role"]),
            token_type=data["type"],  # type: ignore[arg-type]
            exp=datetime.fromtimestamp(data["exp"], tz=UTC),
        )


@dataclass(frozen=True)
class PatientTokenPayload:
    patient_id: UUID
    clinic_id: UUID
    session_id: UUID | None
    exp: datetime

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PatientTokenPayload:
        session_raw = data.get("session_id")
        return cls(
            patient_id=UUID(str(data["sub"])),
            clinic_id=UUID(str(data["clinic_id"])),
            session_id=UUID(str(session_raw)) if session_raw else None,
            exp=datetime.fromtimestamp(data["exp"], tz=UTC),
        )


def _encode(payload: dict[str, Any]) -> str:
    return jwt.encode(
        payload,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def _decode_raw(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except jwt.ExpiredSignatureError as exc:
        raise HttpError(401, "Token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise HttpError(401, "Invalid token") from exc


def create_staff_access_token(
    *,
    user_id: int,
    clinic_id: UUID | None,
    role: str,
) -> str:
    expire = datetime.now(UTC) + timedelta(
        minutes=settings.JWT_STAFF_ACCESS_TOKEN_EXPIRE_MINUTES
    )
    return _encode(
        {
            "sub": str(user_id),
            "clinic_id": str(clinic_id) if clinic_id else None,
            "role": role,
            "exp": expire,
            "iat": datetime.now(UTC),
            "type": "staff_access",
        }
    )


def create_staff_refresh_token(
    *,
    user_id: int,
    clinic_id: UUID | None,
    role: str,
) -> str:
    expire = datetime.now(UTC) + timedelta(
        days=settings.JWT_STAFF_REFRESH_TOKEN_EXPIRE_DAYS
    )
    return _encode(
        {
            "sub": str(user_id),
            "clinic_id": str(clinic_id) if clinic_id else None,
            "role": role,
            "exp": expire,
            "iat": datetime.now(UTC),
            "type": "staff_refresh",
        }
    )


def create_patient_access_token(
    *, #why star is used it is used to indicate that the function takes a variable number of arguments
    patient_id: UUID,
    clinic_id: UUID,
    session_id: UUID | None = None,
) -> str:
    expire = datetime.now(UTC) + timedelta(
        minutes=settings.JWT_PATIENT_ACCESS_TOKEN_EXPIRE_MINUTES
    )
    return _encode(
        {
            "sub": str(patient_id),
            "clinic_id": str(clinic_id),
            "session_id": str(session_id) if session_id else None,
            "exp": expire,
            "iat": datetime.now(UTC),
            "type": "patient_access",
        }
    )


def decode_staff_token(
    token: str,
    *,
    expected_type: StaffTokenType,
) -> StaffTokenPayload:
    data = _decode_raw(token)
    if data.get("type") != expected_type:
        raise HttpError(401, "Invalid token type")
    return StaffTokenPayload.from_dict(data)


def decode_patient_access_token(token: str) -> PatientTokenPayload:
    data = _decode_raw(token)
    if data.get("type") != "patient_access":
        raise HttpError(401, "Invalid token type")
    return PatientTokenPayload.from_dict(data)
