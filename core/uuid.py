"""
UUID helpers for Synapse.

PostgreSQL 18 provides uuidv7(). Python 3.13 does not yet include uuid.uuid7,
so we generate RFC 9562 UUIDv7 in Python for Django ORM inserts, and also set
the database default to uuidv7() for raw SQL / bulk paths.
"""

from __future__ import annotations

import os
import time
import uuid

from django.db import models
from django.db.models import Func


def uuid7() -> uuid.UUID:
    """
    Generate a time-ordered UUIDv7 (RFC 9562).

    Prefer this over uuid4 for primary keys: better B-tree locality and
    roughly chronological ordering under load.
    """
    if hasattr(uuid, "uuid7"):
        return uuid.uuid7()

    # 48-bit Unix timestamp in milliseconds
    timestamp_ms = int(time.time() * 1000) & ((1 << 48) - 1)
    rand_bytes = os.urandom(10)

    # Layout: timestamp (48) | ver (4) | rand_a (12) | var (2) | rand_b (62)
    uuid_int = timestamp_ms << 80
    uuid_int |= 0x7 << 76  # version 7
    rand_a = int.from_bytes(rand_bytes[:2], "big") & 0x0FFF
    uuid_int |= rand_a << 64
    rand_b = int.from_bytes(rand_bytes[2:], "big") & ((1 << 62) - 1)
    uuid_int |= (0b10 << 62) | rand_b  # RFC variant 10
    return uuid.UUID(int=uuid_int)

 # sample output:
 # 123e4567-e89b-12d3-a456-426614174000
class UuidV7(Func):
    """PostgreSQL 18+ uuidv7() database function."""

    function = "uuidv7"
    template = "%(function)s()"
    arity = 0
    output_field = models.UUIDField()
