"""Schemas for the chat endpoint."""

from __future__ import annotations

from typing import Any

from ninja import Schema


class ChatMessageIn(Schema):
    message: str
    session_token: str | None = None


class ChatTimingsOut(Schema):
    nlu_ms: float = 0.0
    decision_ms: float = 0.0
    sql_ms: float = 0.0
    vector_ms: float = 0.0
    llm_ms: float = 0.0
    fast_path_ms: float = 0.0
    total_ms: float = 0.0


class ChatMessageOut(Schema):
    response: str
    route: str
    intent: str
    confidence: float
    needs_sql: bool = False
    needs_vector: bool = False
    needs_llm: bool = False
    safety_message: str | None = None
    timings: ChatTimingsOut
    meta: dict[str, Any] = {}
