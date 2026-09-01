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


class ConversationSummaryOut(Schema):
    id: str
    session_token: str
    display_name: str
    email: str | None = None
    is_authenticated: bool
    status: str
    message_count: int
    last_message_preview: str | None = None
    last_active_at: str
    created_at: str


class ConversationMessageOut(Schema):
    id: str
    role: str
    message_type: str
    content: str
    metadata: dict[str, Any]
    sequence_number: int
    created_at: str


class ConversationMessagesOut(Schema):
    messages: list[ConversationMessageOut]
    has_more: bool


class StaffChatResumeOut(Schema):
    session_token: str | None
    has_history: bool
    messages: list[ConversationMessageOut]
    has_more: bool
