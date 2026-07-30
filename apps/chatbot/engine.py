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

        from apps.chatbot.nlu.schemas import Intent
        ctx = conversation_context or self._build_context(session) or {}
        last_doctor = ctx.get("last_doctor") if isinstance(ctx.get("last_doctor"), dict) else None
        last_specialty = (
            ctx.get("last_specialty") if isinstance(ctx.get("last_specialty"), dict) else None
        )

        # Explicit booking commit vs exploratory book intent
        booking_commit = self._is_booking_commit(message, nlu_result)
        is_booking_intent = nlu_result.intent in {
            Intent.BOOK_APPOINTMENT,
            Intent.RESCHEDULE_APPOINTMENT,
        }

        # Soft medical / symptom path — recommend, don't dump or fail
        soft_medical = (
            (
                nlu_result.intent == Intent.MEDICAL_QUESTION
                or bool(getattr(nlu_result.entities, "symptom", None))
                or self._looks_like_symptom(message)
            )
            and not is_booking_intent
        )

        # Follow-up about last doctor ("is he a good doctor?")
        doctor_followup = self._is_doctor_quality_followup(message) and last_doctor

        suggested: list[dict[str, Any]] = []
        guidance = ""

        # Fast template paths — no tools / LLM needed
        if route == Route.EMERGENCY or nlu_result.is_emergency:
            t0 = time.perf_counter()
            response_text = self._fast_path(decision, message, clinic)
            timings["fast_path_ms"] = (time.perf_counter() - t0) * 1000

        elif (
            route == Route.DIRECT_RESPONSE
            and nlu_result.intent
            in {
                Intent.GREETING,
                Intent.FAREWELL,
                Intent.OFF_TOPIC,
            }
            and not soft_medical
            and not is_booking_intent
        ):
            t0 = time.perf_counter()
            response_text = self._fast_path(decision, message, clinic)
            timings["fast_path_ms"] = (time.perf_counter() - t0) * 1000

        elif route == Route.CLARIFY and not soft_medical and not is_booking_intent:
            t0 = time.perf_counter()
            response_text = self._fast_path(decision, message, clinic)
            timings["fast_path_ms"] = (time.perf_counter() - t0) * 1000

        else:
            # ── Full pipeline: SQL + vector → Gemini/OpenAI synthesis ─────────
            from apps.chatbot.booking.config import get_booking_config
            from apps.chatbot.booking.discovery import suggest_specialties

            needs_sql = bool(decision.needs_sql)
            needs_vector = bool(decision.needs_vector)

            # Always pull SQL for structured clinic facts
            if nlu_result.intent in {
                Intent.INSURANCE_ACCEPTED,
                Intent.INSURANCE_VERIFICATION,
                Intent.CLINIC_HOURS,
                Intent.CLINIC_LOCATION,
                Intent.SERVICES_OFFERED,
                Intent.PRICING,
                Intent.DOCTOR_SEARCH,
                Intent.DOCTOR_AVAILABILITY,
            }:
                needs_sql = True

            # Vector knowledge for FAQs / soft medical / insurance / services
            if nlu_result.intent in {
                Intent.FAQ,
                Intent.MEDICAL_QUESTION,
                Intent.INSURANCE_ACCEPTED,
                Intent.INSURANCE_VERIFICATION,
                Intent.SERVICES_OFFERED,
                Intent.PRICING,
                Intent.CLINIC_HOURS,
                Intent.CLINIC_LOCATION,
                Intent.DOCTOR_SEARCH,
            } or soft_medical or doctor_followup:
                needs_vector = True

            if is_booking_intent or soft_medical:
                cfg = get_booking_config(clinic)
                if cfg.get("ai_discovery"):
                    suggested, guidance = suggest_specialties(clinic, message=message)

            if is_booking_intent and booking_commit:
                resolved = self._resolve_doctor_from_message(clinic, message)
                if resolved:
                    last_doctor = resolved

            if needs_sql and not is_booking_intent:
                t0 = time.perf_counter()
                sql_rows = self._run_sql(clinic, nlu_result, patient=patient)
                timings["sql_ms"] = (time.perf_counter() - t0) * 1000

            if needs_vector:
                t0 = time.perf_counter()
                vector_rows = self._run_vector(clinic, message)
                timings["vector_ms"] = (time.perf_counter() - t0) * 1000

            extra_bits: list[str] = []
            if suggested:
                names = ", ".join(
                    (s.get("plain_label") or s.get("name") or "") for s in suggested[:4]
                )
                extra_bits.append(
                    "Soft specialty suggestions (not a diagnosis): " + names
                )
            if guidance:
                extra_bits.append("Discovery guidance: " + guidance)
            if last_doctor:
                extra_bits.append(
                    "Last discussed doctor: "
                    + json.dumps(last_doctor, default=str)[:400]
                )
            if last_specialty:
                extra_bits.append(
                    "Last specialty: "
                    + json.dumps(last_specialty, default=str)[:200]
                )
            if is_booking_intent and booking_commit:
                extra_bits.append(
                    "User is ready to book. Invite them to tap Start Booking. "
                    "Do not invent available slots."
                )
            elif is_booking_intent:
                extra_bits.append(
                    "Exploratory booking. Soft-recommend specialties; invite "
                    "Find a Doctor or Start Booking. Do not dump all doctors."
                )
            if soft_medical:
                extra_bits.append(
                    "Symptom / medical question. Empathize, never diagnose, "
                    "suggest specialty options and offer to find a doctor."
                )

            t0 = time.perf_counter()
            response_text = self._generate_response(
                clinic=clinic,
                message=message,
                nlu=nlu_result,
                sql_rows=sql_rows,
                vector_rows=vector_rows,
                session=session,
                extra_context="\n".join(extra_bits),
            )
            timings["llm_ms"] = (time.perf_counter() - t0) * 1000

        timings["total_ms"] = (time.perf_counter() - started) * 1000

        # Remember doctors shown this turn
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
            needs_sql=decision.needs_sql,
            needs_vector=decision.needs_vector,
            needs_llm=True,
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
                    "heading": h.chunk.heading or "",
                    "text": h.chunk.content,
                    "document": h.document.file_name,
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
        extra_context: str = "",
    ) -> str:
        """Synthesize final reply via Gemini (dev) or OpenAI (prod swap)."""
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

        # Grounded fallbacks — never invent
        if sql_rows:
            return format_sql_results(sql_rows)
        if vector_rows:
            top = vector_rows[0]
            snippet = (top.get("text") or "").strip()
            if snippet:
                return snippet[:500]
        return (
            "I couldn't find enough clinic information for that. "
            "Please try again or call the clinic directly."
        )
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

    def _looks_like_symptom(self, message: str) -> bool:
        text = (message or "").lower()
        cues = (
            "pain",
            "ache",
            "itch",
            "fever",
            "cough",
            "dizzy",
            "nausea",
            "headache",
            "rash",
            "swelling",
            "feeling",
            "hurt",
            "sore",
            "symptom",
            "sick",
            "bleeding",
        )
        return any(c in text for c in cues)

    def _is_booking_commit(self, message: str, nlu: Any) -> bool:
        """True when user is ready to open the booking wizard."""
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
        if doctor_names and any(
            k in text for k in ("book", "schedule", "appointment")
        ):
            return True

        # "book with Dr X" — not vague "good doctor"
        generic = (
            "good doctor",
            "best doctor",
            "a doctor",
            "the doctor",
            "some doctor",
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
                "good doctor",
                "is he",
                "is she",
                "are they",
                "experience",
                "qualified",
                "recommend him",
                "recommend her",
                "is ali",
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
                # Match last name tokens
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
