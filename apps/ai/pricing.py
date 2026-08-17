"""Official OpenAI API list prices for models Synapse actually calls.

Rates are USD per 1M tokens (standard, non-batch, non-cached), matching
openai.com/api/pricing for the GPT-4.1 family and embeddings. Used only
to *estimate* spend for Super Admin — clinic owners never see these figures.
"""

from __future__ import annotations

# (input_usd_per_1m, output_usd_per_1m)
OPENAI_USD_PER_1M: dict[str, tuple[float, float]] = {
    "gpt-4.1-nano": (0.10, 0.40),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "text-embedding-3-small": (0.02, 0.0),
    "text-embedding-3-large": (0.13, 0.0),
}

# Gemini is a secondary fallback in this codebase; include the flash family
# we actually configure so Super Admin estimates aren't silently $0.
GEMINI_USD_PER_1M: dict[str, tuple[float, float]] = {
    "gemini-2.0-flash": (0.10, 0.40),
    "gemini-2.5-flash": (0.15, 0.60),
    "gemini-1.5-flash": (0.075, 0.30),
}


def _normalize(model: str) -> str:
    return (model or "").strip().lower()


def rates_for(model: str) -> tuple[float, float] | None:
    key = _normalize(model)
    if key in OPENAI_USD_PER_1M:
        return OPENAI_USD_PER_1M[key]
    if key in GEMINI_USD_PER_1M:
        return GEMINI_USD_PER_1M[key]
    for prefix, pair in OPENAI_USD_PER_1M.items():
        if key.startswith(prefix):
            return pair
    for prefix, pair in GEMINI_USD_PER_1M.items():
        if key.startswith(prefix):
            return pair
    return None


def estimate_usd(*, model: str, prompt_tokens: int, completion_tokens: int) -> float:
    pair = rates_for(model)
    if pair is None:
        return 0.0
    inp, out = pair
    return (max(prompt_tokens, 0) / 1_000_000) * inp + (
        max(completion_tokens, 0) / 1_000_000
    ) * out


def usd_to_microcents(usd: float) -> int:
    """Store dollars as millionths of a USD in AIUsageLog.cost_microcents."""
    return int(round(usd * 1_000_000))


def known_rate_cards() -> list[dict]:
    cards = []
    for name, (inp, out) in {**OPENAI_USD_PER_1M, **GEMINI_USD_PER_1M}.items():
        cards.append(
            {
                "model": name,
                "input_usd_per_1m": inp,
                "output_usd_per_1m": out,
            }
        )
    return cards
