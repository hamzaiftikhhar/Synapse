"""Debug-only retrieval schemas (no LLM)."""

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
