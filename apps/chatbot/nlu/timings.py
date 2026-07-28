"""NLU latency breakdown for profiling."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class NLUTimings:
    """Milliseconds per pipeline phase (api_call_ms is the Gemini/OpenAI HTTP round-trip)."""

    prompt_construction_ms: float = 0.0
    payload_serialization_ms: float = 0.0
    api_call_ms: float = 0.0
    response_read_ms: float = 0.0
    envelope_parse_ms: float = 0.0
    nlu_json_parse_ms: float = 0.0
    entity_resolution_ms: float = 0.0
    decision_engine_ms: float = 0.0
    total_ms: float = 0.0
    prompt_chars: int = 0
    system_chars: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    classifier_source: str = ""

    def to_dict(self) -> dict[str, float | int | str]:
        return {
            k: (round(v, 2) if isinstance(v, float) else v)
            for k, v in asdict(self).items()
        }

    @property
    def non_api_ms(self) -> float:
        """Local Python overhead excluding the provider HTTP call."""
        return (
            self.prompt_construction_ms
            + self.payload_serialization_ms
            + self.response_read_ms
            + self.envelope_parse_ms
            + self.nlu_json_parse_ms
            + self.entity_resolution_ms
            + self.decision_engine_ms
        )
