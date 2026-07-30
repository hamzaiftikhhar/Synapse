"""
ChatEngine — the main orchestrator.

Execution modes
───────────────
  Fast Path  (~50–70% of traffic)
      route == DIRECT_RESPONSE | EMERGENCY | CLARIFY
      → look up response template, return immediately — no DB, no LLM.

  SQL Path   (booking, availability, insurance, hours…)
      → SQL Tool → format rows as context → LLM response (gpt-4.1-mini).

  Vector Path  (FAQs, policies, membership…)
      → SimilaritySearch → top-k chunks → LLM response.

  SQL + Vector Path  (insurance verification, complex questions)
      → Both tools → merged context → LLM response.

  Direct LLM  (medical advice, follow-up, medical_question…)
      → Conversation history + message → LLM response.

All paths persist the user message and assistant reply as ChatMessage rows
and update `session.last_active_at`.
"""


from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


# ── Engine result ─────────────────────────────────────────────────────────────

@dataclass
class EngineResult:
    response: str
    route: str
    intent: str
    confidence: float
    needs_sql: bool = False
    needs_vector: bool = False
    needs_llm: bool = False
    safety_message: str | None = None
    sql_results: list[dict[str, Any]] = field(default_factory=list)
    vector_results: list[dict[str, Any]] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "response": self.response,
            "route": self.route,
            "intent": self.intent,
            "confidence": self.confidence,
            "needs_sql": self.needs_sql,
            "needs_vector": self.needs_vector,
            "needs_llm": self.needs_llm,
            "safety_message": self.safety_message,
            "sql_results": self.sql_results,
            "vector_results": self.vector_results,
            "timings": self.timings,
            "meta": self.meta,
        }


# ── Main Engine ───────────────────────────────────────────────────────────────

class ChatEngine:
    """
    Process one user message end-to-end and return an EngineResult.

    Usage:
        engine = ChatEngine()
        result = engine.process(
            clinic=clinic,
            message="Do you accept Medicaid?",
            session=session,       # ChatSession — optional, for context + persistence
            patient=patient,       # Patient — optional, for auth-required queries
        )
    """

    def process(
        self,
        *,
        clinic: Any,
        message: str,
        session: Any | None = None,
        patient: Any | None = None,
        conversation_context: dict[str, Any] | None = None,
    ) -> EngineResult:
        started = time.perf_counter()
        timings: dict[str, float] = {}

        # ── 1. NLU ──────────────────────────────────────────────────────────
        t0 = time.perf_counter()
        from apps.chatbot.nlu.intent_entity import IntentEntityService
        nlu_result = IntentEntityService().analyze(
            clinic=clinic,
            message=message,
            conversation_context=conversation_context or self._build_context(session),
            session=session,
            log_usage=True,
        )
        timings["nlu_ms"] = (time.perf_counter() - t0) * 1000

        # ── 2. Decision Engine ───────────────────────────────────────────────
        t0 = time.perf_counter()
        from apps.chatbot.nlu.decision import DecisionEngine
        decision = DecisionEngine.decide(nlu_result)
        timings["decision_ms"] = (time.perf_counter() - t0) * 1000

        # ── 3. Route ─────────────────────────────────────────────────────────
        from apps.chatbot.nlu.schemas import Route
        route = decision.route

        sql_rows: list[dict[str, Any]] = []
        vector_rows: list[dict[str, Any]] = []
        response_text = ""

        if route in (Route.DIRECT_RESPONSE, Route.EMERGENCY, Route.CLARIFY):
            t0 = time.perf_counter()
            response_text = self._fast_path(decision, message, clinic)
            timings["fast_path_ms"] = (time.perf_counter() - t0) * 1000

        else:
            # SQL tool
            if decision.needs_sql:
                t0 = time.perf_counter()
                sql_rows = self._run_sql(clinic, nlu_result, patient=patient)
                timings["sql_ms"] = (time.perf_counter() - t0) * 1000

            # Vector tool
            if decision.needs_vector:
                t0 = time.perf_counter()
                vector_rows = self._run_vector(clinic, message)
                timings["vector_ms"] = (time.perf_counter() - t0) * 1000

            # SQL-only: format DB rows directly — no LLM call
            if route == Route.SQL_ONLY and sql_rows:
                from apps.chatbot.sql_tool import format_sql_results
                response_text = format_sql_results(sql_rows)
            elif decision.needs_llm or vector_rows:
                t0 = time.perf_counter()
                response_text = self._generate_response(
                    clinic=clinic,
                    message=message,
                    nlu=nlu_result,
                    sql_rows=sql_rows,
                    vector_rows=vector_rows,
                    session=session,
                )
                timings["llm_ms"] = (time.perf_counter() - t0) * 1000
            elif sql_rows:
                from apps.chatbot.sql_tool import format_sql_results
                response_text = format_sql_results(sql_rows)
            else:
                response_text = (
                    "I couldn't find clinic information for that request. "
                    "Please call the clinic directly for help."
                )

        timings["total_ms"] = (time.perf_counter() - started) * 1000

        from apps.chatbot.ui_meta import build_ui_meta
        ui_meta = build_ui_meta(
            clinic=clinic,
            intent=nlu_result.intent.value,
            route=route.value,
            sql_results=sql_rows,
            is_emergency=nlu_result.is_emergency or route == Route.EMERGENCY,
        )

        # ── 4. Persist messages ───────────────────────────────────────────────
        if session is not None:
            self._save_messages(session, message, response_text, nlu_result)

        return EngineResult(
            response=response_text,
            route=route.value,
            intent=nlu_result.intent.value,
            confidence=nlu_result.confidence,
            needs_sql=decision.needs_sql,
            needs_vector=decision.needs_vector,
            needs_llm=decision.needs_llm,
            safety_message=decision.safety_message,
            sql_results=sql_rows,
            vector_results=vector_rows,
            timings=timings,
            meta=ui_meta,
        )

    # ── Fast Path ─────────────────────────────────────────────────────────────

    def _fast_path(self, decision: Any, message: str, clinic: Any) -> str:
        from apps.chatbot.nlu.schemas import Route
        from apps.chatbot.response_templates import get_response, resolve_direct_template

        nlu = decision.nlu

        # Emergency — safety message always wins
        if decision.route == Route.EMERGENCY:
            base = decision.safety_message or get_response("EMERGENCY")
            return base

        # Clarify — prefer LLM-generated clarification question (it is contextual)
        if decision.route == Route.CLARIFY:
            if nlu.clarification_question:
                return nlu.clarification_question
            return get_response("CLARIFY_GENERIC")

        # Direct Response — pick a template
        template_id = resolve_direct_template(nlu.intent.value, message)
        clinic_phone = getattr(clinic, "phone", "") or ""
        return get_response(template_id, clinic_phone=clinic_phone)

    # ── SQL Tool ──────────────────────────────────────────────────────────────

    def _run_sql(self, clinic: Any, nlu: Any, *, patient: Any = None) -> list[dict[str, Any]]:
        from apps.chatbot.sql_tool import SQLTool

        results = SQLTool.run(clinic, nlu, patient=patient)
        return [r.to_dict() for r in results]

    # ── Vector Tool ───────────────────────────────────────────────────────────

    def _run_vector(self, clinic: Any, query: str) -> list[dict[str, Any]]:
        try:
            from apps.knowledge.services.similarity_search import SimilaritySearchService
            hits = SimilaritySearchService.search(clinic=clinic, query=query, top_k=5)
            return [
                {
                    "score": h.score,
                    "heading": h.heading,
                    "text": h.text,
                    "document": h.document_filename,
                }
                for h in hits
            ]
        except Exception:
            logger.exception("Vector search failed")
            return []

    # ── LLM Response Generator ────────────────────────────────────────────────

    def _generate_response(
        self,
        *,
        clinic: Any,
        message: str,
        nlu: Any,
        sql_rows: list[dict[str, Any]],
        vector_rows: list[dict[str, Any]],
        session: Any | None,
    ) -> str:
        try:
            from openai import OpenAI
        except ImportError:
            return "I'm sorry, I can't process that request right now. Please try again later."

        api_key = getattr(settings, "OPENAI_API_KEY", "")
        if not api_key:
            return "I'm unable to generate a response at this time. Please contact the clinic directly."

        model = getattr(settings, "CHAT_RESPONSE_MODEL", "gpt-4.1-mini")
        timeout = float(getattr(settings, "CHAT_RESPONSE_TIMEOUT_SECONDS", 15.0))

        # Build context blocks
        context_parts: list[str] = []

        if sql_rows:
            context_parts.append("### Clinic Data\n" + json.dumps(sql_rows, indent=2, default=str)[:3000])

        if vector_rows:
            chunks = "\n\n".join(
                f"[{h['heading'] or 'Info'}] {h['text'][:500]}"
                for h in vector_rows
                if h.get("score", 0) >= 0.40
            )
            if chunks:
                context_parts.append("### Knowledge Base\n" + chunks[:2500])

        context_block = "\n\n".join(context_parts)

        # Recent conversation history (last 6 turns)
        history = self._load_history(session, limit=6)

        system_prompt = (
            f"You are a friendly, concise clinic assistant for {clinic.name}. "
            "Answer the patient's question using ONLY the provided clinic data and knowledge base. "
            "Do not invent appointments, doctors, or policies. "
            "If you cannot answer from the data, say so politely and suggest calling the clinic. "
            "Keep responses brief (2–4 sentences) and clinic-focused. "
            "Never diagnose or give medical advice."
        )

        messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]

        if context_block:
            messages.append({
                "role": "system",
                "content": f"Current clinic context:\n{context_block}",
            })

        messages.extend(history)
        messages.append({"role": "user", "content": message})

        try:
            client = OpenAI(api_key=api_key, timeout=timeout)
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.3,
                max_tokens=300,
            )
            return resp.choices[0].message.content or "I wasn't able to generate a response. Please call the clinic."
        except Exception as exc:
            logger.exception("LLM response generation failed: %s", exc)
            return "I'm having trouble responding right now. Please try again or call the clinic directly."

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _build_context(self, session: Any | None) -> dict[str, Any] | None:
        if session is None:
            return None
        ctx = getattr(session, "conversation_context", None)
        return ctx if isinstance(ctx, dict) else None

    def _load_history(self, session: Any | None, *, limit: int = 6) -> list[dict[str, str]]:
        if session is None:
            return []
        try:
            from apps.chatbot.models import ChatMessage, MessageRole, MessageType
            msgs = (
                ChatMessage.objects
                .filter(
                    session=session,
                    role__in=[MessageRole.USER, MessageRole.ASSISTANT],
                    message_type=MessageType.TEXT,
                )
                .order_by("-sequence_number")[:limit]
            )
            history = [{"role": m.role, "content": m.content} for m in reversed(msgs)]
            return history
        except Exception:
            logger.exception("Failed to load conversation history")
            return []

    def _save_messages(
        self,
        session: Any,
        user_message: str,
        assistant_response: str,
        nlu: Any,
    ) -> None:
        try:
            from apps.chatbot.models import ChatMessage, MessageRole, MessageType

            # Get next sequence number
            last = (
                ChatMessage.objects
                .filter(session=session)
                .order_by("-sequence_number")
                .values_list("sequence_number", flat=True)
                .first()
            )
            seq = (last or 0) + 1

            ChatMessage.objects.create(
                clinic=session.clinic,
                session=session,
                role=MessageRole.USER,
                message_type=MessageType.TEXT,
                content=user_message,
                sequence_number=seq,
                metadata={
                    "intent": nlu.intent.value,
                    "confidence": nlu.confidence,
                },
            )
            ChatMessage.objects.create(
                clinic=session.clinic,
                session=session,
                role=MessageRole.ASSISTANT,
                message_type=MessageType.TEXT,
                content=assistant_response,
                sequence_number=seq + 1,
                metadata={},
            )

            # Update session activity
            session.last_active_at = timezone.now()
            session.save(update_fields=["last_active_at"])

        except Exception:
            logger.exception("Failed to save chat messages")
