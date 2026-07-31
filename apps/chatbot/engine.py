"""
ChatEngine — tiered orchestrator.

Lanes
─────
  direct      greeting / farewell / off_topic / emergency → templates
  sql_fast    hours / insurance / doctors / location → SQL + formatter (no Large LLM)
  booking     book explore/commit → discovery + Start Booking
  vector_rag  FAQ / policy / PDF-matched → vector + Large LLM only here
  clarify     unknown / low confidence → polite clarify

Hard rule: synthesize_clinic_reply runs iff lane == vector_rag.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


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
    lane: str = ""

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
            "lane": self.lane,
        }


class ChatEngine:
    """Process one user message end-to-end and return an EngineResult."""

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

        from apps.chatbot.routing import (
            Lane,
            apply_routing_heuristics,
            build_document_catalog,
            catalog_for_nlu_context,
            matching_document_ids,
            resolve_lane,
        )

        # Document catalog for Small NLU + heuristics
        t0 = time.perf_counter()
        doc_catalog = build_document_catalog(clinic)
        timings["doc_catalog_ms"] = (time.perf_counter() - t0) * 1000

        ctx = conversation_context or self._build_context(session) or {}
        nlu_ctx = dict(ctx) if isinstance(ctx, dict) else {}
        catalog_text = catalog_for_nlu_context(doc_catalog)
        if catalog_text:
            nlu_ctx["document_catalog"] = catalog_text[:1200]

        # ── 1. NLU ──────────────────────────────────────────────────────────
        t0 = time.perf_counter()
        from apps.chatbot.nlu.intent_entity import IntentEntityService

        nlu_result = IntentEntityService().analyze(
            clinic=clinic,
            message=message,
            conversation_context=nlu_ctx,
            session=session,
            log_usage=True,
        )
        timings["nlu_ms"] = (time.perf_counter() - t0) * 1000

        # Heuristic post-pass (SQL vs vector gating)
        nlu_result = apply_routing_heuristics(
            message=message,
            nlu=nlu_result,
            document_catalog=doc_catalog,
        )

        # ── 2. Decision Engine ───────────────────────────────────────────────
        t0 = time.perf_counter()
        from apps.chatbot.nlu.decision import DecisionEngine

        decision = DecisionEngine.decide(nlu_result)
        timings["decision_ms"] = (time.perf_counter() - t0) * 1000

        from apps.chatbot.nlu.schemas import Intent, Route

        route = decision.route
        sql_rows: list[dict[str, Any]] = []
        vector_rows: list[dict[str, Any]] = []
        response_text = ""

        last_doctor = ctx.get("last_doctor") if isinstance(ctx.get("last_doctor"), dict) else None
        last_specialty = (
            ctx.get("last_specialty") if isinstance(ctx.get("last_specialty"), dict) else None
        )

        booking_commit = self._is_booking_commit(message, nlu_result)
        is_booking_intent = nlu_result.intent in {
            Intent.BOOK_APPOINTMENT,
            Intent.RESCHEDULE_APPOINTMENT,
        }

        soft_medical = (
            (
                nlu_result.intent == Intent.MEDICAL_QUESTION
                or bool(getattr(nlu_result.entities, "symptom", None))
                or self._looks_like_symptom(message)
            )
            and not is_booking_intent
        )

        doctor_followup = self._is_doctor_quality_followup(message) and last_doctor
        matched_docs = matching_document_ids(message, doc_catalog)
        policy_like = any(
            k in (message or "").lower()
            for k in (
                "policy",
                "cancel",
                "cancellation",
                "what does",
                "include",
                "membership",
            )
        )
        needs_vector = bool(nlu_result.needs_vector) or (
            soft_medical and bool(matched_docs)
        )
        doc_match = bool(matched_docs) and (
            needs_vector
            or nlu_result.intent in {Intent.FAQ, Intent.MEDICAL_QUESTION}
            or policy_like
        )

        lane = resolve_lane(
            nlu=nlu_result,
            route=route,
            is_booking_intent=is_booking_intent,
            soft_medical=soft_medical,
            needs_vector=needs_vector,
            doc_match=doc_match,
        )

        # Doctor quality follow-up: template, no RAG
        if doctor_followup and lane != Lane.BOOKING:
            lane = Lane.DIRECT

        suggested: list[dict[str, Any]] = []
        guidance = ""
        timings["lane"] = lane.value

        # ── 3. Execute lane ──────────────────────────────────────────────────
        if lane == Lane.DIRECT:
            t0 = time.perf_counter()
            if doctor_followup and last_doctor:
                response_text = self._doctor_followup_reply(last_doctor)
            elif soft_medical:
                response_text = self._soft_medical_reply(clinic, message)
            else:
                response_text = self._fast_path(decision, message, clinic)
            timings["fast_path_ms"] = (time.perf_counter() - t0) * 1000

        elif lane == Lane.CLARIFY:
            t0 = time.perf_counter()
            response_text = self._fast_path(decision, message, clinic)
            timings["fast_path_ms"] = (time.perf_counter() - t0) * 1000

        elif lane == Lane.SQL_FAST:
            t0 = time.perf_counter()
            sql_rows = self._run_sql(clinic, nlu_result, patient=patient)
            timings["sql_ms"] = (time.perf_counter() - t0) * 1000
            from apps.chatbot.sql_tool import format_sql_results

            response_text = format_sql_results(sql_rows)
            if soft_medical and not sql_rows:
                response_text = self._soft_medical_reply(clinic, message)

        elif lane == Lane.BOOKING:
            from apps.chatbot.booking.config import get_booking_config
            from apps.chatbot.booking.discovery import suggest_specialties

            cfg = get_booking_config(clinic)
            if cfg.get("ai_discovery"):
                t0 = time.perf_counter()
                suggested, guidance = suggest_specialties(clinic, message=message)
                timings["discovery_ms"] = (time.perf_counter() - t0) * 1000

            if booking_commit:
                resolved = self._resolve_doctor_from_message(clinic, message)
                if resolved:
                    last_doctor = resolved
                response_text = (
                    "Great — tap Start Booking below and I'll walk you through "
                    "picking a time. I won't list every open slot here."
                )
            else:
                bits = []
                if guidance:
                    bits.append(guidance)
                if suggested:
                    names = ", ".join(
                        (s.get("plain_label") or s.get("name") or "")
                        for s in suggested[:3]
                    )
                    bits.append(
                        f"Based on what you shared, these areas may help: {names}."
                    )
                bits.append(
                    "When you're ready, tap Start Booking or ask me to find a doctor."
                )
                response_text = " ".join(bits)

        elif lane == Lane.VECTOR_RAG:
            # Optional SQL if also needed
            if nlu_result.needs_sql:
                t0 = time.perf_counter()
                sql_rows = self._run_sql(clinic, nlu_result, patient=patient)
                timings["sql_ms"] = (time.perf_counter() - t0) * 1000

            t0 = time.perf_counter()
            vector_rows = self._run_vector(
                clinic, message, document_ids=matched_docs or None
            )
            timings["vector_ms"] = (time.perf_counter() - t0) * 1000

            t0 = time.perf_counter()
            response_text = self._generate_response(
                clinic=clinic,
                message=message,
                nlu=nlu_result,
                sql_rows=sql_rows,
                vector_rows=vector_rows,
                session=session,
                extra_context="",
            )
            timings["llm_ms"] = (time.perf_counter() - t0) * 1000

        else:
            response_text = self._fast_path(decision, message, clinic)

        timings["total_ms"] = (time.perf_counter() - started) * 1000

        shown_doctors = []
        for block in sql_rows:
            if block.get("handler") == "search_doctors":
                for r in (block.get("rows") or [])[:3]:
                    shown_doctors.append(
                        {
                            "id": str(r.get("id") or ""),
                            "name": r.get("full_name") or r.get("name") or "",
                            "title": r.get("title") or "",
                            "bio": (r.get("bio") or "")[:240],
                        }
                    )
        if shown_doctors and not last_doctor:
            last_doctor = shown_doctors[0]
        if suggested and not last_specialty:
            last_specialty = {
                "id": suggested[0].get("id"),
                "name": suggested[0].get("name"),
            }

        from apps.chatbot.ui_meta import build_ui_meta

        ui_meta = build_ui_meta(
            clinic=clinic,
            intent=nlu_result.intent.value,
            route=route.value,
            sql_results=sql_rows,
            is_emergency=nlu_result.is_emergency or route == Route.EMERGENCY,
            message=message,
            nlu=nlu_result,
            booking_commit=booking_commit and is_booking_intent,
            last_doctor=last_doctor,
            last_specialty=last_specialty,
        )
        ui_meta["lane"] = lane.value

        if (soft_medical or (is_booking_intent and not booking_commit)) and suggested:
            ui_meta.setdefault("specialties", [])
            if not ui_meta["specialties"]:
                ui_meta["specialties"] = [
                    {
                        "id": s.get("id"),
                        "name": s.get("name"),
                        "description": s.get("plain_label") or s.get("description") or "",
                        "recommended": True,
                        "select_message": f"I need a {s.get('name')} doctor",
                    }
                    for s in suggested[:4]
                ]

        if session is not None:
            self._save_messages(session, message, response_text, nlu_result)
            self._update_memory(
                session,
                last_doctor=last_doctor,
                last_specialty=last_specialty,
                intent=nlu_result.intent.value,
            )

        return EngineResult(
            response=response_text,
            route=route.value,
            intent=nlu_result.intent.value,
            confidence=nlu_result.confidence,
            needs_sql=bool(nlu_result.needs_sql),
            needs_vector=lane == Lane.VECTOR_RAG,
            needs_llm=lane == Lane.VECTOR_RAG,
            safety_message=decision.safety_message,
            sql_results=sql_rows,
            vector_results=vector_rows,
            timings=timings,
            meta=ui_meta,
            lane=lane.value,
        )

    def _soft_medical_reply(self, clinic: Any, message: str) -> str:
        from apps.chatbot.booking.config import get_booking_config
        from apps.chatbot.booking.discovery import suggest_specialties

        cfg = get_booking_config(clinic)
        if cfg.get("ai_discovery"):
            suggested, guidance = suggest_specialties(clinic, message=message)
            if suggested:
                names = ", ".join(
                    (s.get("plain_label") or s.get("name") or "") for s in suggested[:3]
                )
                return (
                    (guidance + " " if guidance else "")
                    + f"I'm not able to diagnose, but these areas may help: {names}. "
                    "Would you like me to find a doctor or start booking?"
                )
        return (
            "I'm sorry you're dealing with that. I can't diagnose symptoms, "
            "but I can help you find a doctor or start booking an appointment."
        )

    def _fast_path(self, decision: Any, message: str, clinic: Any) -> str:
        from apps.chatbot.nlu.schemas import Route
        from apps.chatbot.response_templates import get_response, resolve_direct_template

        nlu = decision.nlu

        if decision.route == Route.EMERGENCY:
            return decision.safety_message or get_response("EMERGENCY")

        if decision.route == Route.CLARIFY or getattr(nlu, "clarification_needed", False):
            if nlu.clarification_question:
                return nlu.clarification_question
            return get_response("CLARIFY_GENERIC")

        template_id = resolve_direct_template(nlu.intent.value, message)
        clinic_phone = getattr(clinic, "phone", "") or ""
        return get_response(template_id, clinic_phone=clinic_phone)

    def _run_sql(self, clinic: Any, nlu: Any, *, patient: Any = None) -> list[dict[str, Any]]:
        from apps.chatbot.sql_tool import SQLTool

        results = SQLTool.run(clinic, nlu, patient=patient)
        return [r.to_dict() for r in results]

    def _run_vector(
        self,
        clinic: Any,
        query: str,
        *,
        document_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        try:
            from apps.knowledge.services.similarity_search import SimilaritySearchService

            kwargs: dict[str, Any] = {
                "clinic": clinic,
                "query": query,
                "top_k": 5,
            }
            # Scope when search API supports document filter
            search = getattr(SimilaritySearchService, "search")
            try:
                hits = search(**kwargs, document_ids=document_ids)  # type: ignore[call-arg]
            except TypeError:
                hits = search(**kwargs)

            min_score = float(getattr(settings, "CHAT_VECTOR_MIN_SCORE", 0.25))
            return [
                {
                    "score": h.score,
                    "heading": h.chunk.heading or "",
                    "text": h.chunk.content,
                    "document": h.document.file_name,
                    "document_id": str(getattr(h.document, "id", "")),
                }
                for h in hits
                if (h.score or 0) >= min_score
            ]
        except Exception:
            logger.exception("Vector search failed")
            return []

    def _generate_response(
        self,
        *,
        clinic: Any,
        message: str,
        nlu: Any,
        sql_rows: list[dict[str, Any]],
        vector_rows: list[dict[str, Any]],
        session: Any | None,
        extra_context: str = "",
    ) -> str:
        """Large LLM — vector_rag lane only."""
        from apps.chatbot.response_llm import ResponseLLMError, synthesize_clinic_reply
        from apps.chatbot.sql_tool import format_sql_results

        history = self._load_history(session, limit=8)
        try:
            return synthesize_clinic_reply(
                clinic=clinic,
                message=message,
                nlu=nlu,
                sql_rows=sql_rows,
                vector_rows=vector_rows,
                history=history,
                extra_context=extra_context,
            )
        except ResponseLLMError as exc:
            logger.warning("Response LLM failed: %s", exc)
        except Exception:
            logger.exception("Response LLM unexpected failure")

        if vector_rows:
            top = vector_rows[0]
            snippet = (top.get("text") or "").strip()
            if snippet:
                return snippet[:500]
        if sql_rows:
            return format_sql_results(sql_rows)
        return (
            "I couldn't find that in our clinic documents. "
            "Please try rephrasing, or ask about hours, insurance, or booking."
        )

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
                ChatMessage.objects.filter(
                    session=session,
                    role__in=[MessageRole.USER, MessageRole.ASSISTANT],
                    message_type=MessageType.TEXT,
                )
                .order_by("-sequence_number")[:limit]
            )
            return [{"role": m.role, "content": m.content} for m in reversed(msgs)]
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

            last = (
                ChatMessage.objects.filter(session=session)
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
            session.last_active_at = timezone.now()
            session.save(update_fields=["last_active_at"])
        except Exception:
            logger.exception("Failed to save chat messages")

    def _looks_like_symptom(self, message: str) -> bool:
        text = (message or "").lower()
        cues = (
            "pain", "ache", "itch", "fever", "cough", "dizzy", "nausea",
            "headache", "rash", "swelling", "feeling", "hurt", "sore",
            "symptom", "sick", "bleeding",
        )
        return any(c in text for c in cues)

    def _is_booking_commit(self, message: str, nlu: Any) -> bool:
        import re

        text = (message or "").lower().strip()
        if text in {
            "start booking",
            "book appointment",
            "book an appointment",
            "i would like to book an appointment",
        }:
            return True
        if "start booking" in text:
            return True

        doctor_names = getattr(getattr(nlu, "entities", None), "doctor_name", None)
        if doctor_names and any(k in text for k in ("book", "schedule", "appointment")):
            return True

        generic = (
            "good doctor", "best doctor", "a doctor", "the doctor", "some doctor",
        )
        if any(g in text for g in generic):
            return False

        if re.search(r"(book|schedule).{0,40}(with\s+dr\.?|with\s+[a-z])", text):
            return True
        return False

    def _is_doctor_quality_followup(self, message: str) -> bool:
        text = (message or "").lower()
        return any(
            p in text
            for p in (
                "good doctor", "is he", "is she", "are they", "experience",
                "qualified", "recommend him", "recommend her", "is ali",
                "about the doctor",
            )
        )

    def _doctor_followup_reply(self, doctor: dict[str, Any]) -> str:
        name = doctor.get("name") or "This doctor"
        title = doctor.get("title") or ""
        bio = (doctor.get("bio") or "").strip()
        bits = [f"{name}"]
        if title:
            bits.append(f"({title})")
        lead = " ".join(bits)
        if bio:
            return (
                f"Yes — {lead} specializes in care described as: {bio} "
                "Would you like to keep your appointment with them, or compare other doctors?"
            )
        return (
            f"Yes — {lead} is on our clinic team and accepting patients. "
            "Would you like to book or compare other doctors?"
        )

    def _resolve_doctor_from_message(
        self, clinic: Any, message: str
    ) -> dict[str, Any] | None:
        text = (message or "").strip()
        if not text:
            return None
        try:
            from apps.doctors.models import Doctor

            qs = Doctor.objects.filter(
                clinic=clinic, is_deleted=False, is_active=True
            )
            for d in qs[:25]:
                if d.full_name and d.full_name.lower() in text.lower():
                    return {
                        "id": str(d.id),
                        "name": d.full_name,
                        "title": d.title or "",
                        "bio": (d.bio or "")[:240],
                    }
                parts = d.full_name.replace("Dr.", "").strip().split()
                if parts and parts[-1].lower() in text.lower() and len(parts[-1]) > 3:
                    return {
                        "id": str(d.id),
                        "name": d.full_name,
                        "title": d.title or "",
                        "bio": (d.bio or "")[:240],
                    }
        except Exception:
            logger.exception("Doctor resolve from message failed")
        return None

    def _update_memory(
        self,
        session: Any,
        *,
        last_doctor: dict[str, Any] | None,
        last_specialty: dict[str, Any] | None,
        intent: str,
    ) -> None:
        try:
            ctx = dict(session.conversation_context or {})
            if last_doctor and last_doctor.get("id"):
                ctx["last_doctor"] = last_doctor
            if last_specialty and last_specialty.get("id"):
                ctx["last_specialty"] = last_specialty
            ctx["current_intent"] = intent
            session.conversation_context = ctx
            session.save(update_fields=["conversation_context", "last_active_at"])
        except Exception:
            logger.exception("Failed to update conversation memory")
