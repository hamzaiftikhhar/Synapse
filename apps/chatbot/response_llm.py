"""
Final answer synthesis LLM — provider-agnostic.

Uses SQL rows + vector knowledge + chat history to produce a concise
clinic reply. Swap CHAT_RESPONSE_PROVIDER between gemini (dev) and openai (prod).
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

from django.conf import settings

logger = logging.getLogger(__name__)

_GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "{model}:generateContent?key={api_key}"
)


class ResponseLLMError(Exception):
    pass


def synthesize_clinic_reply(
    *,
    clinic: Any,
    message: str,
    nlu: Any | None = None,
    sql_rows: list[dict[str, Any]] | None = None,
    vector_rows: list[dict[str, Any]] | None = None,
    history: list[dict[str, str]] | None = None,
    extra_context: str = "",
) -> str:
    """Generate a concise patient-facing answer from grounded clinic context."""
    provider = (getattr(settings, "CHAT_RESPONSE_PROVIDER", "gemini") or "gemini").lower()
    system = _system_prompt(clinic)
    user_block = _user_block(
        message=message,
        nlu=nlu,
        sql_rows=sql_rows or [],
        vector_rows=vector_rows or [],
        history=history or [],
        extra_context=extra_context,
    )

    if provider == "openai":
        return _openai_generate(system=system, user_block=user_block)
    return _gemini_generate(system=system, user_block=user_block)


def _system_prompt(clinic: Any) -> str:
    phone = getattr(clinic, "phone", "") or ""
    return (
        f"You are the clinic assistant for {clinic.name}. "
        "Write a concise, warm reply for the patient (2–4 sentences unless listing is needed). "
        "Use ONLY the provided clinic data, knowledge excerpts, and conversation history. "
        "Do not invent doctors, hours, insurance plans, prices, or policies. "
        "Never diagnose or prescribe. Soft specialty suggestions are OK if provided in context. "
        "If data is missing, say so briefly and suggest calling the clinic"
        + (f" at {phone}" if phone else "")
        + ". "
        "Do not mention SQL, vectors, embeddings, or internal tools."
    )


def _user_block(
    *,
    message: str,
    nlu: Any | None,
    sql_rows: list[dict[str, Any]],
    vector_rows: list[dict[str, Any]],
    history: list[dict[str, str]],
    extra_context: str,
) -> str:
    parts: list[str] = []

    if nlu is not None:
        intent = getattr(getattr(nlu, "intent", None), "value", None) or getattr(
            nlu, "intent", ""
        )
        parts.append(f"### Intent\n{intent}")

    if history:
        lines = []
        for turn in history[-8:]:
            role = turn.get("role", "user")
            content = (turn.get("content") or "").strip()
            if content:
                lines.append(f"{role}: {content}")
        if lines:
            parts.append("### Recent conversation\n" + "\n".join(lines))

    if sql_rows:
        parts.append(
            "### Clinic database results\n"
            + json.dumps(sql_rows, indent=2, default=str)[:3500]
        )

    if vector_rows:
        chunks = []
        for h in vector_rows:
            score = float(h.get("score") or 0)
            if score < 0.25:
                continue
            heading = h.get("heading") or "Info"
            text = (h.get("text") or "")[:600]
            chunks.append(f"[{heading} | score={score:.2f}]\n{text}")
        if chunks:
            parts.append("### Knowledge base excerpts\n" + "\n\n".join(chunks[:5])[:3000])

    if extra_context.strip():
        parts.append("### Additional context\n" + extra_context.strip()[:1500])

    parts.append(f"### Patient message\n{message.strip()}")
    parts.append("### Task\nWrite the assistant reply only — no JSON, no preamble.")
    return "\n\n".join(parts)


def _gemini_generate(*, system: str, user_block: str) -> str:
    api_key = getattr(settings, "GOOGLE_API_KEY", "") or ""
    if not api_key:
        raise ResponseLLMError("GOOGLE_API_KEY is not configured")

    primary = getattr(settings, "CHAT_RESPONSE_MODEL", "gemini-3.1-flash-lite")
    fallbacks = getattr(
        settings,
        "CHAT_RESPONSE_FALLBACK_MODELS",
        "gemini-flash-lite-latest,gemini-2.0-flash-lite,gemini-3.1-flash-lite",
    )
    models = [primary] + [
        m.strip()
        for m in str(fallbacks).split(",")
        if m.strip() and m.strip() != primary
    ]
    timeout = float(getattr(settings, "CHAT_RESPONSE_TIMEOUT_SECONDS", 20.0))

    payload = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user_block}]}],
        "generationConfig": {
            "temperature": 0.35,
            "maxOutputTokens": 400,
        },
    }
    body = json.dumps(payload).encode("utf-8")
    last_error: Exception | None = None

    for model in models:
        url = _GEMINI_URL.format(model=model, api_key=api_key)
        request = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                envelope = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            logger.warning(
                "Gemini response LLM model=%s HTTP %s: %s",
                model,
                exc.code,
                detail[:300],
            )
            last_error = ResponseLLMError(f"Gemini HTTP {exc.code}: {detail[:300]}")
            # Try next model on not-found / overload
            if exc.code in {404, 429, 503}:
                continue
            raise last_error from exc
        except Exception as exc:
            last_error = ResponseLLMError(f"Gemini request failed: {exc}")
            logger.warning("Gemini response LLM model=%s error: %s", model, exc)
            continue

        candidates = envelope.get("candidates") or []
        if not candidates:
            last_error = ResponseLLMError(f"Gemini model {model} returned no candidates")
            continue
        parts = (((candidates[0] or {}).get("content") or {}).get("parts")) or []
        text = "".join(p.get("text", "") for p in parts if isinstance(p, dict)).strip()
        if not text:
            last_error = ResponseLLMError(f"Gemini model {model} returned empty content")
            continue
        logger.info("Gemini response LLM ok model=%s chars=%s", model, len(text))
        return text

    raise last_error or ResponseLLMError("Gemini response LLM failed for all models")


def _openai_generate(*, system: str, user_block: str) -> str:
    api_key = getattr(settings, "OPENAI_API_KEY", "") or ""
    if not api_key:
        raise ResponseLLMError("OPENAI_API_KEY is not configured")

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise ResponseLLMError("openai package is not installed") from exc

    model = getattr(settings, "CHAT_RESPONSE_MODEL", "gpt-4.1-mini")
    timeout = float(getattr(settings, "CHAT_RESPONSE_TIMEOUT_SECONDS", 20.0))
    client = OpenAI(api_key=api_key, timeout=timeout)
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_block},
        ],
        temperature=0.35,
        max_tokens=400,
    )
    text = (resp.choices[0].message.content or "").strip()
    if not text:
        raise ResponseLLMError("OpenAI returned empty content")
    return text
