"""
Final answer synthesis LLM — provider-agnostic with hard wall-clock deadlines.

Never lets an LLM decide how long the API call lasts.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any

from django.conf import settings

from apps.chatbot.nlu.deadline import run_with_deadline
from apps.chatbot.providers import circuit_breaker

logger = logging.getLogger(__name__)

_GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "{model}:generateContent?key={api_key}"
)


class ResponseLLMError(Exception):
    pass


def build_response_prompts(
    *,
    clinic: Any,
    message: str,
    nlu: Any | None = None,
    sql_rows: list[dict[str, Any]] | None = None,
    vector_rows: list[dict[str, Any]] | None = None,
    history: list[dict[str, str]] | None = None,
    extra_context: str = "",
) -> dict[str, str]:
    """Return the exact system/user prompts sent to the Large LLM (for pipeline debug)."""
    return {
        "system_prompt": _system_prompt(clinic),
        "user_prompt": _user_block(
            message=message,
            nlu=nlu,
            sql_rows=sql_rows or [],
            vector_rows=vector_rows or [],
            history=history or [],
            extra_context=extra_context,
        ),
    }


def synthesize_clinic_reply(
    *,
    clinic: Any,
    message: str,
    nlu: Any | None = None,
    sql_rows: list[dict[str, Any]] | None = None,
    vector_rows: list[dict[str, Any]] | None = None,
    history: list[dict[str, str]] | None = None,
    extra_context: str = "",
    deadline_seconds: float | None = None,
) -> str:
    """Generate a concise patient-facing answer from grounded clinic context."""
    prompts = build_response_prompts(
        clinic=clinic,
        message=message,
        nlu=nlu,
        sql_rows=sql_rows,
        vector_rows=vector_rows,
        history=history,
        extra_context=extra_context,
    )
    system = prompts["system_prompt"]
    user_block = prompts["user_prompt"]

    budget = float(
        deadline_seconds
        if deadline_seconds is not None
        else getattr(settings, "CHAT_RESPONSE_TIMEOUT_SECONDS", 8.0)
    )
    budget = max(0.5, budget)
    started = time.perf_counter()

    primary = (getattr(settings, "CHAT_RESPONSE_PROVIDER", "openai") or "openai").lower()
    secondary = (
        getattr(settings, "CHAT_RESPONSE_SECONDARY_PROVIDER", "") or ""
    ).lower().strip()

    providers = [primary]
    if secondary and secondary != primary:
        providers.append(secondary)

    last_error: Exception | None = None
    for provider in providers:
        remaining = budget - (time.perf_counter() - started)
        if remaining < 0.5:
            break
        if not circuit_breaker.is_available(provider):
            logger.info("response_llm skip provider=%s circuit_open", provider)
            continue
        try:
            if provider == "openai":
                text = _openai_generate(
                    system=system, user_block=user_block, deadline=remaining
                )
            elif provider == "gemini":
                text = _gemini_generate(
                    system=system, user_block=user_block, deadline=remaining
                )
            else:
                continue
            circuit_breaker.record_success(provider)
            return text
        except Exception as exc:
            last_error = exc
            circuit_breaker.record_failure(provider, str(exc))
            logger.warning("response_llm provider=%s failed: %s", provider, exc)
            continue

    raise last_error or ResponseLLMError("Response LLM failed for all providers")


def empty_rag_reply(clinic: Any) -> str:
    """User-facing copy when vector retrieval has nothing useful."""
    phone = getattr(clinic, "phone", "") or ""
    phone_bit = f" or call us at {phone}" if phone else ""
    return (
        f"I couldn't find clinic-specific information on that in our documents. "
        f"Please check with our care team through the patient portal{phone_bit}."
    )


def _load_constitution() -> str:
    from pathlib import Path

    path = Path(__file__).resolve().parent / "prompts" / "receptionist_constitution.md"
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return (
            "You are a premium clinic concierge. Be concise, warm, and patient-facing. "
            "Never invent clinical facts or mention internal tools."
        )


def _clinic_prompt_overlay(clinic: Any) -> str:
    try:
        from apps.widget.models import WidgetSettings

        settings = WidgetSettings.objects.filter(clinic=clinic).first()
        if settings and isinstance(settings.configuration, dict):
            ai = settings.configuration.get("ai") or {}
            overlay = ai.get("clinic_prompt") or ai.get("system_prompt") or ""
            if isinstance(overlay, str) and overlay.strip():
                return overlay.strip()
    except Exception:
        pass
    return ""


def _system_prompt(clinic: Any) -> str:
    phone = getattr(clinic, "phone", "") or ""
    constitution = _load_constitution()
    overlay = _clinic_prompt_overlay(clinic)
    base = (
        f"You are the clinic assistant for {clinic.name}. "
        f"{constitution} "
        "You are answering from retrieved knowledge-base excerpts (RAG lane only). "
        "Use ONLY the provided knowledge excerpts and optional SQL context. "
        + (f"Clinic phone (only if needed): {phone}. " if phone else "")
    )
    if overlay:
        base += f"\n\n### Clinic-specific guidance\n{overlay[:2000]}"
    return base


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
        for turn in history[-2:]:  # at most last 1–2 turns for latency
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


def _gemini_generate(*, system: str, user_block: str, deadline: float) -> str:
    api_key = getattr(settings, "GOOGLE_API_KEY", "") or ""
    if not api_key:
        raise ResponseLLMError("GOOGLE_API_KEY is not configured")

    primary = getattr(settings, "CHAT_RESPONSE_MODEL", "gemini-2.0-flash-lite")
    # Only use Gemini model list when provider is gemini; else a flash-lite default
    if "gpt" in str(primary).lower():
        primary = "gemini-2.0-flash-lite"
    models = [primary]
    per_try = min(float(deadline), float(getattr(settings, "CHAT_RESPONSE_TIMEOUT_SECONDS", 8.0)))

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

        def _do_request() -> dict[str, Any]:
            with urllib.request.urlopen(request, timeout=per_try) as response:
                return json.loads(response.read().decode("utf-8"))

        try:
            envelope = run_with_deadline(_do_request, seconds=per_try)
        except TimeoutError as exc:
            last_error = ResponseLLMError(f"Gemini timed out after {per_try}s")
            logger.warning("Gemini response LLM model=%s timeout", model)
            continue
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            last_error = ResponseLLMError(f"Gemini HTTP {exc.code}: {detail[:300]}")
            if exc.code in {404, 429, 503}:
                continue
            raise last_error from exc
        except Exception as exc:
            last_error = ResponseLLMError(f"Gemini request failed: {exc}")
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


def _openai_generate(*, system: str, user_block: str, deadline: float) -> str:
    api_key = getattr(settings, "OPENAI_API_KEY", "") or ""
    if not api_key:
        raise ResponseLLMError("OPENAI_API_KEY is not configured")

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise ResponseLLMError("openai package is not installed") from exc

    model = getattr(settings, "CHAT_RESPONSE_MODEL", "gpt-4.1-mini")
    if str(model).startswith("gemini"):
        model = "gpt-4.1-mini"
    per_try = min(float(deadline), float(getattr(settings, "CHAT_RESPONSE_TIMEOUT_SECONDS", 8.0)))
    client = OpenAI(api_key=api_key, timeout=per_try)

    def _do_request() -> str:
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

    try:
        return run_with_deadline(_do_request, seconds=per_try)
    except TimeoutError as exc:
        raise ResponseLLMError(f"OpenAI timed out after {per_try}s") from exc
