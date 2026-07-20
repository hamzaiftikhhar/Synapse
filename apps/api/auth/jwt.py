"""JWT encode/decode for clinic staff API tokens."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import jwt
from django.conf import settings
from ninja.errors import HttpError


@dataclass(frozen=True)
class TokenPayload:
    user_id: int
    clinic_id: UUID
    exp: datetime

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TokenPayload:
        return cls(
            user_id=int(data["sub"]),
            clinic_id=UUID(str(data["clinic_id"])),
            exp=datetime.fromtimestamp(data["exp"], tz=UTC),
        )


def create_access_token(*, user_id: int, clinic_id: UUID) -> str:
    expire = datetime.now(UTC) + timedelta(
        minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {
        "sub": str(user_id),
        "clinic_id": str(clinic_id),
        "exp": expire,
        "iat": datetime.now(UTC),
        "type": "access",
    }
    return jwt.encode(
        payload,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def decode_access_token(token: str) -> TokenPayload:
    try:
        data = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except jwt.ExpiredSignatureError as exc:
        raise HttpError(401, "Token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise HttpError(401, "Invalid token") from exc

    if data.get("type") != "access":
        raise HttpError(401, "Invalid token type")

    return TokenPayload.from_dict(data)
