"""Debug-only retrieval and NLU schemas."""

from typing import Any

from ninja import Schema


class DebugSearchIn(Schema):
    query: str
    top_k: int = 5


class DebugSearchHitOut(Schema):
    score: float
    document: str
    chunk_number: int
    heading: str
    text: str


class DebugSearchOut(Schema):
    query: str
    embedding_provider: str
    embedding_model: str
    embedding_dimensions: int
    top_results: list[DebugSearchHitOut]


class DebugNLUIn(Schema):
    message: str
    conversation_context: dict[str, Any] = {}


class DebugNLUOut(Schema):
    message: str
    nlu_provider: str
    nlu_model: str
    route: str
    needs_sql: bool
    needs_vector: bool
    needs_llm: bool
    safety_message: str | None = None
    nlu: dict[str, Any]
