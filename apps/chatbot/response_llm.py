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

# Live-confirmed hallucination-adjacent gap: a fact the patient stated 2+
# exchanges ago (e.g. a child's allergy) was invisible to this prompt at
# the old cap of 1 exchange (history[-2:], "at most last 1-2 turns for
# latency") -- reproduced directly: the reply asked the patient to
# disclose an allergy they had *already* stated one exchange earlier.
# Measured, not assumed, that widening this has no meaningful latency
# cost -- 3-call samples at the old vs. this cap showed no consistent
# difference (dominated by the LLM API round trip itself, same finding as
# Phase 37's NLU latency measurement) -- and this reuses engine.py's
# already-loaded `recent_turns` (itself capped at 6 there), so it's not a
# second DB query either. Kept as an explicit constant, not `history[-2:]`
# inline, so the two call sites (here and engine.py::_generate_response)
# can't drift out of sync again.
_MAX_HISTORY_TURNS = 6

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
    return _call_response_llm(
        system=prompts["system_prompt"],
        user_block=prompts["user_prompt"],
        deadline_seconds=deadline_seconds,
    )


def _call_response_llm(
    *,
    system: str,
    user_block: str,
    deadline_seconds: float | None = None,
    max_tokens: int = 400,
    workload: str = "response",
) -> str:
    """Provider-fallback call shared by every Large-LLM prompt this module
    builds (grounded RAG reply, general medical knowledge reply, ...) --
    extracted from synthesize_clinic_reply so a new prompt never has to
    re-implement budget splitting, circuit-breaker skip, or provider
    fallback from scratch.

    `max_tokens` defaults to 400 (right-sized for this module's short,
    2-4 sentence prose replies) -- a caller with a structurally different
    output shape (e.g. capability_resolver.py's multi-candidate JSON with
    a reasoning string per candidate) must pass a larger value explicitly.
    Live-confirmed gap: the default silently truncated a 5-6 candidate
    JSON response mid-string, producing a JSON parse failure that looked
    identical to a provider outage rather than an output-budget problem.

    `workload` namespaces the circuit-breaker key (see
    providers/circuit_breaker.py) as f"{provider}:{workload}" -- e.g.
    "openai:response" vs "openai:capability". Confirmed root cause of a
    real coupling bug: this function and nlu/classifier.py's own OpenAI
    calls both used the bare provider name ("openai") as the circuit key,
    so a burst of failures from either -- including capability_resolver.py's
    heavier, slower calls, which also route through this function -- could
    open the shared circuit and silence NLU classification for the full
    cooldown window. Each caller now gets its own independent circuit;
    `is_nlu_degraded`'s failure mode is orthogonal to and layered on top of
    this, not a substitute for it."""
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

    # Split the wall-clock budget evenly across every provider we might try,
    # once, up front — so total time across all fallback attempts is bounded
    # by `budget` regardless of provider count. Previously each provider got
    # min(remaining, CHAT_RESPONSE_TIMEOUT_SECONDS) computed fresh every
    # iteration; since the outer request budget is generous, `remaining`
    # stayed above the per-provider cap even after the first provider used
    # its full slice, so two providers could each independently burn a full
    # CHAT_RESPONSE_TIMEOUT_SECONDS (8s + 8s = 16s stalls).
    per_provider_budget = budget / len(providers)

    last_error: Exception | None = None
    for provider in providers:
        circuit_key = f"{provider}:{workload}"
        remaining = budget - (time.perf_counter() - started)
        if remaining < 0.5:
            break
        if not circuit_breaker.is_available(circuit_key):
            logger.info(
                "response_llm skip provider=%s workload=%s circuit_open",
                provider,
                workload,
            )
            continue
        deadline = min(remaining, per_provider_budget)
        try:
            if provider == "openai":
                text = _openai_generate(
                    system=system,
                    user_block=user_block,
                    deadline=deadline,
                    max_tokens=max_tokens,
                )
            elif provider == "gemini":
                text = _gemini_generate(
                    system=system,
                    user_block=user_block,
                    deadline=deadline,
                    max_tokens=max_tokens,
                )
            else:
                continue
            circuit_breaker.record_success(circuit_key)
            return text
        except Exception as exc:
            last_error = exc
            circuit_breaker.record_failure(circuit_key, str(exc))
            logger.warning(
                "response_llm provider=%s workload=%s failed: %s", provider, workload, exc
            )
            continue

    raise last_error or ResponseLLMError("Response LLM failed for all providers")


def empty_rag_reply(clinic: Any) -> str:
    """User-facing copy when vector retrieval has nothing useful.

    Deliberately doesn't say "in our documents"/"our records" or otherwise
    name how the answer was looked up — a patient doesn't need or want to
    hear about internal retrieval mechanics (live-confirmed complaint: this
    read as evasive/confusing, especially when it fired for a symptom
    mention rather than a genuine missing-FAQ case). Says what's actually
    true (no clinic-specific info on that) and gives a real next step.
    """
    phone = getattr(clinic, "phone", "") or ""
    phone_bit = f" or call us at {phone}" if phone else ""
    return (
        f"I don't have clinic-specific information on that. Our care team can "
        f"help directly — please reach out through the patient portal{phone_bit}."
    )


_GENERAL_KNOWLEDGE_SYSTEM_PROMPT = """You are a clinic assistant answering a purely general, educational medical/health question -- NOT a personal symptom disclosure (those are routed elsewhere and never reach you). The planner only sends you a message here when it has already classified it as asking what a condition/term/procedure IS, how it works, or its general risks/side effects, with no personal circumstance stated.

Answer from your own general medical knowledge, in 2-4 sentences. Never diagnose the user, never recommend a specific treatment, dose, or medication for the user's own situation, never imply you know anything about the user's personal health -- you don't, and weren't told anything. Use hedging/qualification language where medically appropriate (e.g. "generally", "in most cases", "a doctor can confirm this for your specific situation") -- the same advisory tone a careful clinic receptionist would use, never a confident clinical pronouncement.

Keep it a clean, direct educational answer -- do not pad it with an appointment pitch by default. Only add a brief, optional offer to help find a doctor or book an appointment (one short sentence, at most) if the question's own phrasing suggests it might be personally motivated even though it wasn't classified as personal -- most purely definitional questions ("What is X?", "How does X work?") don't need this at all and should end cleanly with the answer.

Never mention documents, knowledge bases, retrieval, or internal tools. Never break character to explain your own routing."""


def build_general_knowledge_prompts(message: str) -> dict[str, str]:
    """System/user prompts for a purely general, non-personalized medical
    education question (planner_direct_mode == "general_medical_knowledge").

    Deliberately a separate prompt from _system_prompt/_user_block above,
    not a variant of them -- those are RAG-grounded and explicitly forbid
    answering from the model's own knowledge ("use ONLY the provided
    knowledge excerpts and SQL context -- never invent one"); weakening
    that constraint to also allow this case would risk it leaking into
    the grounded clinic-fact path. This prompt is the opposite: it MUST
    use general knowledge, precisely because there is no clinic-specific
    grounding to give it for a question like "What is hypothyroidism?"
    """
    return {
        "system_prompt": _GENERAL_KNOWLEDGE_SYSTEM_PROMPT,
        "user_prompt": (message or "").strip(),
    }


def generate_general_knowledge_reply(
    message: str, *, deadline_seconds: float | None = None
) -> str:
    """Answer a purely definitional/educational medical question using the
    model's own general knowledge -- see build_general_knowledge_prompts
    for the safety framing. Reuses the same provider-fallback/circuit-
    breaker machinery as synthesize_clinic_reply (_call_response_llm),
    just with a different, ungrounded prompt."""
    prompts = build_general_knowledge_prompts(message)
    return _call_response_llm(
        system=prompts["system_prompt"],
        user_block=prompts["user_prompt"],
        deadline_seconds=deadline_seconds,
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
        "For clinic-specific facts (doctors, hours, prices, insurance, policies, "
        "slots), use ONLY the provided knowledge excerpts and SQL context — never "
        "invent one. The Recent conversation section, when present, is a separate, "
        "legitimate source: use it to remember what the patient already told you "
        "and refer back to it naturally, the same as a human receptionist would — "
        "it is never a source of new clinic facts, only of what's already been "
        "said in this conversation. "
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
        for turn in history[-_MAX_HISTORY_TURNS:]:
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


def _gemini_generate(
    *, system: str, user_block: str, deadline: float, max_tokens: int = 400
) -> str:
    api_key = getattr(settings, "GOOGLE_API_KEY", "") or ""
    if not api_key:
        raise ResponseLLMError("GOOGLE_API_KEY is not configured")

    primary = getattr(settings, "CHAT_RESPONSE_MODEL", "gemini-3.5-flash-lite")
    # Only use Gemini model list when provider is gemini; else a flash-lite default
    if "gpt" in str(primary).lower():
        primary = "gemini-3.5-flash-lite"
    models = [primary]
    per_try = min(float(deadline), float(getattr(settings, "CHAT_RESPONSE_TIMEOUT_SECONDS", 8.0)))

    payload = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user_block}]}],
        "generationConfig": {
            "temperature": 0.35,
            "maxOutputTokens": max_tokens,
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


def _openai_generate(
    *, system: str, user_block: str, deadline: float, max_tokens: int = 400
) -> str:
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
            max_tokens=max_tokens,
        )
        text = (resp.choices[0].message.content or "").strip()
        if not text:
            raise ResponseLLMError("OpenAI returned empty content")
        return text

    try:
        return run_with_deadline(_do_request, seconds=per_try)
    except TimeoutError as exc:
        raise ResponseLLMError(f"OpenAI timed out after {per_try}s") from exc
