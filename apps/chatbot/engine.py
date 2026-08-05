"""
ChatEngine — tiered orchestrator.

Lanes
─────
  direct      greeting / farewell / off_topic / emergency → templates
  sql_fast    hours / insurance / doctors / location → SQL + formatter (no Large LLM)
  booking     book explore/commit → discovery + inline wizard meta
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
        request_budget = float(getattr(settings, "CHAT_REQUEST_BUDGET_SECONDS", 20.0))
        min_llm_remaining = float(
            getattr(settings, "CHAT_RESPONSE_MIN_REMAINING_SECONDS", 2.0)
        )

        from apps.chatbot.routing import (
            Lane,
            apply_routing_heuristics,
            build_document_catalog,
            build_service_catalog,
            catalog_for_nlu_context,
            is_transactional_booking,
            looks_like_knowledge_question,
            matching_document_ids,
        )

        # Document + service catalogs for Small NLU + heuristics
        t0 = time.perf_counter()
        doc_catalog = build_document_catalog(clinic)
        service_catalog = build_service_catalog(clinic)
        timings["doc_catalog_ms"] = (time.perf_counter() - t0) * 1000

        ctx = conversation_context or self._build_context(session) or {}
        nlu_ctx = dict(ctx) if isinstance(ctx, dict) else {}
        catalog_text = catalog_for_nlu_context(doc_catalog)
        if catalog_text:
            nlu_ctx["document_catalog"] = catalog_text[:1200]
        if service_catalog:
            nlu_ctx["services"] = ", ".join(
                s.get("name") or "" for s in service_catalog[:20]
            )[:600]

        # ── 1. NLU (semantics) ──────────────────────────────────────────────
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

        # Heuristics as sensors: entity hints, phatic/emergency safety — not lane owner
        nlu_result = apply_routing_heuristics(
            message=message,
            nlu=nlu_result,
            document_catalog=doc_catalog,
            service_catalog=service_catalog,
        )

        from apps.chatbot.routing.confidence import (
            apply_confidence_policy,
            confidence_meta,
        )
        from apps.chatbot.routing.signals import (
            is_service_list_query,
            is_specialty_list_query,
            match_services_in_message,
        )
        from apps.chatbot.nlu.schemas import Intent, Route
        from apps.chatbot.planner import (
            apply_plan_to_nlu,
            build_execution_plan,
            build_planner_facts,
        )
        from apps.chatbot.nlu.decision import EMERGENCY_SAFETY_MESSAGE

        service_hit = bool(match_services_in_message(message, service_catalog))
        knowledge_q = looks_like_knowledge_question(message)
        conf_policy = apply_confidence_policy(
            nlu_result,
            has_catalog=bool(doc_catalog),
            service_hit=service_hit,
            knowledge_q=knowledge_q,
        )
        nlu_result = conf_policy.nlu
        timings["confidence_band"] = conf_policy.band.value

        sql_rows: list[dict[str, Any]] = []
        vector_rows: list[dict[str, Any]] = []
        response_text = ""
        suggested: list[dict[str, Any]] = []
        guidance = ""

        last_doctor = ctx.get("last_doctor") if isinstance(ctx.get("last_doctor"), dict) else None
        last_specialty = (
            ctx.get("last_specialty") if isinstance(ctx.get("last_specialty"), dict) else None
        )

        booking_commit = self._is_booking_commit(message, nlu_result)
        knowledge_q = looks_like_knowledge_question(message)
        is_booking_intent = (
            nlu_result.intent
            in {
                Intent.BOOK_APPOINTMENT,
                Intent.RESCHEDULE_APPOINTMENT,
            }
            and (is_transactional_booking(message) or booking_commit)
            and not knowledge_q
        )

        soft_medical = (
            (
                nlu_result.intent == Intent.MEDICAL_QUESTION
                or bool(getattr(nlu_result.entities, "symptom", None))
                or self._looks_like_symptom(message)
            )
            and not is_booking_intent
            and not knowledge_q
        )

        doctor_followup = bool(self._is_doctor_quality_followup(message) and last_doctor)
        matched_docs = matching_document_ids(message, doc_catalog)
        has_catalog = bool(doc_catalog)
        doc_match = bool(matched_docs) or (
            has_catalog
            and (
                knowledge_q
                or nlu_result.intent in {Intent.FAQ, Intent.MEDICAL_QUESTION, Intent.MEMBERSHIP}
            )
        )

        degraded = bool((nlu_result.raw or {}).get("_degraded")) or (
            getattr(nlu_result.timings, "classifier_source", "") == "rules_fallback"
            and float(nlu_result.confidence or 0) < 0.55
        )
        doctor_ranking_request = self._is_doctor_ranking_request(message)
        instruction_injection = self._looks_like_instruction_injection(message)
        unknown_doctor_requested = self._requests_unknown_doctor(message, clinic, nlu_result)

        # ── 2. Planner (no I/O) → ExecutionPlan ─────────────────────────────
        t0 = time.perf_counter()
        facts = build_planner_facts(
            message=message,
            nlu=nlu_result,
            is_booking_intent=is_booking_intent,
            booking_commit=booking_commit,
            soft_medical=soft_medical,
            knowledge_q=knowledge_q,
            specialty_list=is_specialty_list_query(message),
            service_list=is_service_list_query(message),
            has_catalog=has_catalog,
            doc_match=doc_match,
            matched_doc_ids=matched_docs or [],
            service_hit=service_hit,
            prefer_vector=conf_policy.prefer_vector,
            prefer_clarify=conf_policy.prefer_clarify,
            allow_hybrid=bool(conf_policy.allow_hybrid),
            degraded=degraded,
            doctor_ranking_request=doctor_ranking_request,
            instruction_injection=instruction_injection,
            unknown_doctor_requested=unknown_doctor_requested,
            doctor_followup=doctor_followup,
            confidence_band=conf_policy.band.value,
        )
        exec_plan = build_execution_plan(nlu=nlu_result, facts=facts)
        nlu_result = apply_plan_to_nlu(nlu_result, exec_plan)
        lane = exec_plan.primary_lane
        route = exec_plan.to_route()
        timings["decision_ms"] = (time.perf_counter() - t0) * 1000
        timings["lane"] = lane.value
        timings["planner_reason"] = exec_plan.reason

        # ── 3. Executor — run tasks from ExecutionPlan ──────────────────────
        safety_message = (
            EMERGENCY_SAFETY_MESSAGE
            if exec_plan.emergency or exec_plan.direct_mode == "emergency"
            else None
        )

        if exec_plan.direct or exec_plan.emergency:
            t0 = time.perf_counter()
            if exec_plan.direct_mode == "doctor_ranking_refusal":
                response_text = self._doctor_ranking_reply()
            elif exec_plan.direct_mode == "prompt_injection_refusal":
                response_text = self._instruction_injection_reply()
            elif exec_plan.direct_mode == "unknown_doctor_refusal":
                response_text = self._unknown_doctor_reply()
            elif exec_plan.direct_mode == "medical_advice_refusal":
                response_text = self._medical_advice_refusal_reply()
            elif exec_plan.doctor_followup and last_doctor:
                response_text = self._doctor_followup_reply(last_doctor)
            elif exec_plan.soft_medical or exec_plan.direct_mode == "soft_medical":
                response_text = self._soft_medical_reply(clinic, message)
                if not self._looks_like_aesthetic_request(message):
                    suggested, guidance = self._maybe_suggest_specialties(
                        clinic, message, timings
                    )
            else:
                response_text = self._fast_path_from_plan(
                    exec_plan, nlu_result, message, clinic, safety_message
                )
            timings["fast_path_ms"] = (time.perf_counter() - t0) * 1000

        else:
            # SQL tasks
            if exec_plan.sql_tasks:
                t0 = time.perf_counter()
                sql_rows = self._run_sql_tasks(
                    clinic,
                    nlu_result,
                    exec_plan.sql_tasks,
                    patient=patient,
                    message=message,
                )
                timings["sql_ms"] = (time.perf_counter() - t0) * 1000

            # Vector tasks
            if exec_plan.vector_tasks or exec_plan.use_response_llm:
                t0 = time.perf_counter()
                vector_rows = self._run_vector(
                    clinic, message, document_ids=matched_docs or None
                )
                timings["vector_ms"] = (time.perf_counter() - t0) * 1000

            # Booking UI prep (skip specialty discovery for aesthetic/service SKUs)
            if exec_plan.booking:
                if not self._looks_like_aesthetic_request(message):
                    suggested, guidance = self._maybe_suggest_specialties(
                        clinic, message, timings
                    )
                if booking_commit:
                    resolved = self._resolve_doctor_from_message(clinic, message)
                    if resolved:
                        last_doctor = resolved

            # Compose response from executed tasks
            response_text = self._compose_from_plan(
                clinic=clinic,
                message=message,
                nlu=nlu_result,
                exec_plan=exec_plan,
                sql_rows=sql_rows,
                vector_rows=vector_rows,
                session=session,
                booking_commit=booking_commit,
                suggested=suggested,
                guidance=guidance,
                soft_medical=soft_medical,
                timings=timings,
                request_started=started,
                request_budget=request_budget,
                min_llm_remaining=min_llm_remaining,
            )

            # Thin SQL + catalog: optional hybrid escalate when plan was sql-only
            remaining = request_budget - (time.perf_counter() - started)
            if (
                exec_plan.sql_tasks
                and not exec_plan.vector_tasks
                and not exec_plan.booking
                and remaining >= min_llm_remaining
                and self._should_hybrid_rag(
                    nlu=nlu_result,
                    sql_rows=sql_rows,
                    has_catalog=has_catalog,
                    knowledge_q=knowledge_q,
                    allow_hybrid=bool(conf_policy.allow_hybrid),
                )
            ):
                lane = Lane.VECTOR_RAG
                timings["lane"] = lane.value
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
                    deadline_seconds=request_budget - (time.perf_counter() - started),
                    timings=timings,
                )
                timings["llm_ms"] = (time.perf_counter() - t0) * 1000

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
        ui_meta["routing"] = confidence_meta(conf_policy)
        ui_meta["planner"] = exec_plan.to_dict()
        if nlu_result.service_filter_mode:
            ui_meta["service_filter_mode"] = nlu_result.service_filter_mode
        if nlu_result.sql_tool:
            ui_meta["sql_tool"] = nlu_result.sql_tool
        source = ""
        if nlu_result.timings and getattr(nlu_result.timings, "classifier_source", None):
            source = str(nlu_result.timings.classifier_source)
        if source in {"rules_fallback"} or (nlu_result.raw or {}).get("_degraded"):
            ui_meta["degraded"] = True
            ui_meta["degraded_reason"] = "nlu_timeout_or_fallback"
        if unknown_doctor_requested:
            ui_meta["unknown_doctor_requested"] = True
        if doctor_ranking_request:
            ui_meta["doctor_ranking_refused"] = True
        if instruction_injection:
            ui_meta["prompt_injection_refused"] = True

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

        logger.info(
            "chat_route clinic=%s lane=%s intent=%s sql_tasks=%s vector_tasks=%s "
            "degraded=%s planner=%s timings=%s",
            getattr(clinic, "id", None),
            lane.value,
            nlu_result.intent.value,
            exec_plan.sql_tasks,
            exec_plan.vector_tasks,
            bool(ui_meta.get("degraded")),
            exec_plan.to_dict(),
            {
                "nlu_ms": round(float(timings.get("nlu_ms", 0.0)), 1),
                "sql_ms": round(float(timings.get("sql_ms", 0.0)), 1),
                "vector_ms": round(float(timings.get("vector_ms", 0.0)), 1),
                "llm_ms": round(float(timings.get("llm_ms", 0.0)), 1),
                "total_ms": round(float(timings.get("total_ms", 0.0)), 1),
            },
        )

        self._emit_pipeline_debug(
            clinic=clinic,
            message=message,
            session=session,
            patient=patient,
            nlu_ctx=nlu_ctx,
            nlu_result=nlu_result,
            plan=exec_plan,
            lane=lane,
            route=route,
            sql_rows=sql_rows,
            vector_rows=vector_rows,
            response_text=response_text,
            timings=timings,
            ui_meta=ui_meta,
        )

        return EngineResult(
            response=response_text,
            route=route.value,
            intent=nlu_result.intent.value,
            confidence=nlu_result.confidence,
            needs_sql=bool(exec_plan.sql_tasks),
            needs_vector=bool(exec_plan.vector_tasks),
            needs_llm=bool(exec_plan.use_response_llm),
            safety_message=safety_message,
            sql_results=sql_rows,
            vector_results=vector_rows,
            timings=timings,
            meta=ui_meta,
            lane=lane.value,
        )

    def _emit_pipeline_debug(
        self,
        *,
        clinic: Any,
        message: str,
        session: Any | None,
        patient: Any | None,
        nlu_ctx: dict[str, Any],
        nlu_result: Any,
        plan: Any,
        lane: Any,
        route: Any,
        sql_rows: list[dict[str, Any]],
        vector_rows: list[dict[str, Any]],
        response_text: str,
        timings: dict[str, Any],
        ui_meta: dict[str, Any],
    ) -> None:
        """Print / save structured pipeline evidence when DEBUG_CHAT_PIPELINE is on."""
        from apps.chatbot.pipeline_debug import (
            ChatPipelineTrace,
            capture_nlu_prompts,
            capture_response_prompts,
            pipeline_debug_enabled,
        )

        if not pipeline_debug_enabled():
            return

        nlu_prompts = capture_nlu_prompts(message, nlu_ctx)
        nlu_source = ""
        if nlu_result.timings and getattr(nlu_result.timings, "classifier_source", None):
            nlu_source = str(nlu_result.timings.classifier_source)

        large_llm: dict[str, Any] = {
            "executed": False,
            "provider": getattr(settings, "CHAT_RESPONSE_PROVIDER", ""),
            "model": getattr(settings, "CHAT_RESPONSE_MODEL", ""),
            "latency_ms": round(float(timings.get("llm_ms", 0.0)), 1),
            "tokens": "n/a",
            "system_prompt": "",
            "user_prompt": "",
        }
        if float(timings.get("llm_ms", 0.0)) > 0 or lane.value == "vector_rag":
            history = self._load_history(session, limit=8)
            prompts = capture_response_prompts(
                clinic=clinic,
                message=message,
                nlu=nlu_result,
                sql_rows=sql_rows,
                vector_rows=vector_rows,
                history=history,
                extra_context="",
            )
            large_llm.update(
                {
                    "executed": True,
                    "system_prompt": prompts.get("system_prompt", ""),
                    "user_prompt": prompts.get("user_prompt", ""),
                }
            )

        handlers = [
            block.get("handler")
            for block in sql_rows
            if isinstance(block, dict) and block.get("handler")
        ]

        trace = ChatPipelineTrace(
            user_message=message,
            clinic_id=str(getattr(clinic, "id", "") or ""),
            clinic_name=str(getattr(clinic, "name", "") or ""),
            session_id=str(getattr(session, "id", "") or ""),
            patient_id=str(getattr(patient, "id", "") or ""),
            nlu={
                "source": nlu_source or nlu_result.provider or "-",
                "provider": nlu_result.provider,
                "model": nlu_result.model,
                "intent": nlu_result.intent.value,
                "confidence": nlu_result.confidence,
                "entities": nlu_result.entities.to_dict(),
                "needs_sql": nlu_result.needs_sql,
                "needs_vector": nlu_result.needs_vector,
                "needs_llm": nlu_result.needs_llm,
                "is_emergency": nlu_result.is_emergency,
                "document_needed": nlu_result.document_needed,
                "sql_tool": nlu_result.sql_tool,
                "service_filter_mode": nlu_result.service_filter_mode,
                "reasoning": nlu_result.reasoning_short,
                "system_prompt": nlu_prompts.get("system_prompt", ""),
                "user_prompt": nlu_prompts.get("user_prompt", ""),
                "timings": nlu_result.timings.to_dict() if nlu_result.timings else {},
            },
            planner={
                **plan.to_dict(),
                "degraded": bool(ui_meta.get("degraded")),
            },
            sql={
                "executed": bool(sql_rows),
                "handlers": handlers,
                "rows": sql_rows,
            },
            vector={
                "executed": bool(vector_rows) or float(timings.get("vector_ms", 0.0)) > 0,
                "hit_count": len(vector_rows),
                "chunks": [
                    {
                        "score": c.get("score"),
                        "document": c.get("document"),
                        "heading": c.get("heading"),
                        "text": c.get("text"),
                    }
                    for c in vector_rows[:5]
                ],
            },
            large_llm=large_llm,
            final={
                "lane": lane.value,
                "route": route.value,
                "response": response_text,
            },
            timings={
                k: (round(float(v), 1) if isinstance(v, (int, float)) else v)
                for k, v in timings.items()
            },
        )
        trace.emit()

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

    def _doctor_ranking_reply(self) -> str:
        return (
            "I can't rank our clinicians as the best or worst. I can help with "
            "factual comparisons like specialties, qualifications, languages, "
            "availability, and whether a doctor accepts new patients."
        )

    def _instruction_injection_reply(self) -> str:
        return (
            "I can't apply discounts, override clinic policy, or act on system-style "
            "instructions sent in chat. I can only share the clinic's documented "
            "pricing, policies, and booking options."
        )

    def _unknown_doctor_reply(self) -> str:
        return (
            "I couldn't verify that doctor in this clinic's roster, so I won't start "
            "booking under that name. I can help you choose from the clinic's listed "
            "doctors or search by specialty instead."
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

    def _sql_found(self, sql_rows: list[dict[str, Any]]) -> bool:
        if not sql_rows:
            return False
        return any(bool(block.get("found")) or bool(block.get("rows")) for block in sql_rows)

    def _should_hybrid_rag(
        self,
        *,
        nlu: Any,
        sql_rows: list[dict[str, Any]],
        has_catalog: bool,
        knowledge_q: bool,
        allow_hybrid: bool = False,
    ) -> bool:
        """Escalate SQL → vector when structured lookup misses and docs exist."""
        from apps.chatbot.routing.lanes import HYBRID_SQL_INTENTS
        from apps.chatbot.nlu.schemas import Intent

        if not has_catalog:
            return False
        if self._sql_found(sql_rows) and not knowledge_q and not nlu.needs_vector:
            # Mid-confidence policy may still allow hybrid for thin answers later;
            # today we only escalate on empty/miss or explicit vector need.
            if not allow_hybrid:
                return False
            return False
        intent = nlu.intent
        if intent in HYBRID_SQL_INTENTS or knowledge_q or bool(nlu.needs_vector):
            return True
        if intent == Intent.UNKNOWN:
            return True
        if allow_hybrid and not self._sql_found(sql_rows):
            return True
        # Empty SQL on pricing/services always try docs when present
        if not self._sql_found(sql_rows) and intent in {
            Intent.PRICING,
            Intent.SERVICES_OFFERED,
            Intent.INSURANCE_ACCEPTED,
            Intent.INSURANCE_VERIFICATION,
            Intent.FAQ,
        }:
            return True
        return False

    def _run_sql(
        self,
        clinic: Any,
        nlu: Any,
        *,
        patient: Any = None,
        message: str = "",
    ) -> list[dict[str, Any]]:
        from apps.chatbot.sql_tool import SQLTool

        results = SQLTool.run(clinic, nlu, patient=patient, message=message)
        return [r.to_dict() for r in results]

    def _run_sql_tasks(
        self,
        clinic: Any,
        nlu: Any,
        tasks: list[str],
        *,
        patient: Any = None,
        message: str = "",
    ) -> list[dict[str, Any]]:
        from apps.chatbot.sql_tool import SQLTool

        results = SQLTool.run_tasks(
            clinic, nlu, tasks, patient=patient, message=message
        )
        return [r.to_dict() for r in results]

    def _maybe_suggest_specialties(
        self,
        clinic: Any,
        message: str,
        timings: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], str]:
        from apps.chatbot.booking.config import get_booking_config
        from apps.chatbot.booking.discovery import suggest_specialties

        cfg = get_booking_config(clinic)
        if not cfg.get("ai_discovery"):
            return [], ""
        t0 = time.perf_counter()
        suggested, guidance = suggest_specialties(clinic, message=message)
        timings["discovery_ms"] = (time.perf_counter() - t0) * 1000
        return suggested or [], guidance or ""

    def _fast_path_from_plan(
        self,
        exec_plan: Any,
        nlu: Any,
        message: str,
        clinic: Any,
        safety_message: str | None,
    ) -> str:
        from apps.chatbot.nlu.schemas import Route
        from apps.chatbot.response_templates import get_response, resolve_direct_template

        clinic_phone = getattr(clinic, "phone", "") or ""
        if exec_plan.emergency or exec_plan.direct_mode == "emergency":
            return safety_message or get_response("EMERGENCY")
        if exec_plan.clarify or exec_plan.to_route() == Route.CLARIFY:
            if getattr(nlu, "clarification_question", None):
                return nlu.clarification_question
            return get_response("CLARIFY_GENERIC")
        template_id = resolve_direct_template(nlu.intent.value, message)
        return get_response(template_id, clinic_phone=clinic_phone)

    def _compose_from_plan(
        self,
        *,
        clinic: Any,
        message: str,
        nlu: Any,
        exec_plan: Any,
        sql_rows: list[dict[str, Any]],
        vector_rows: list[dict[str, Any]],
        session: Any | None,
        booking_commit: bool,
        suggested: list[dict[str, Any]],
        guidance: str,
        soft_medical: bool,
        timings: dict[str, Any],
        request_started: float | None = None,
        request_budget: float = 20.0,
        min_llm_remaining: float = 2.0,
    ) -> str:
        """Compose patient-facing text after tasks have been executed."""
        from apps.chatbot.sql_tool import format_sql_results

        booking_text = ""
        aesthetic = self._looks_like_aesthetic_request(message)
        if exec_plan.booking:
            if booking_commit:
                booking_text = (
                    "Sure — I'll help you schedule. Choose your preferences below "
                    "and we'll lock in a time."
                )
            else:
                bits = []
                if guidance and not aesthetic:
                    bits.append(guidance)
                if suggested and not aesthetic:
                    names = ", ".join(
                        (s.get("plain_label") or s.get("name") or "")
                        for s in suggested[:3]
                    )
                    bits.append(
                        f"Based on what you shared, these areas may help: {names}."
                    )
                bits.append(
                    "Use the booking form below to pick a specialty, doctor, and time."
                )
                booking_text = " ".join(bits)

        if exec_plan.direct_mode == "medical_advice_refusal":
            return self._medical_advice_refusal_reply()

        if exec_plan.use_response_llm or exec_plan.vector_tasks:
            if not vector_rows:
                from apps.chatbot.response_llm import empty_rag_reply

                grounded = empty_rag_reply(clinic)
                timings["degraded_reason"] = "empty_vector"
                if booking_text:
                    return f"{grounded}\n\n{booking_text}"
                return grounded

            remaining = request_budget
            if request_started is not None:
                remaining = request_budget - (time.perf_counter() - request_started)
            if remaining < min_llm_remaining:
                timings["degraded_reason"] = "response_llm_budget"
                from apps.chatbot.response_llm import empty_rag_reply

                grounded = (vector_rows[0].get("text") or "")[:400] or empty_rag_reply(
                    clinic
                )
                if booking_text:
                    return f"{grounded}\n\n{booking_text}"
                return grounded

            t0 = time.perf_counter()
            grounded = self._generate_response(
                clinic=clinic,
                message=message,
                nlu=nlu,
                sql_rows=sql_rows,
                vector_rows=vector_rows,
                session=session,
                extra_context=booking_text,
                deadline_seconds=remaining,
                timings=timings,
            )
            timings["llm_ms"] = (time.perf_counter() - t0) * 1000
            if booking_text and grounded:
                return f"{grounded}\n\n{booking_text}"
            return grounded or booking_text

        if exec_plan.sql_tasks:
            sql_text = format_sql_results(sql_rows)
            if soft_medical and not self._sql_found(sql_rows):
                sql_text = self._soft_medical_reply(clinic, message)
            if booking_text:
                return f"{sql_text}\n\n{booking_text}" if sql_text else booking_text
            return sql_text

        if exec_plan.booking:
            return booking_text

        if exec_plan.clarify:
            return self._fast_path_from_plan(exec_plan, nlu, message, clinic, None)

        return self._fast_path_from_plan(exec_plan, nlu, message, clinic, None)

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
        deadline_seconds: float | None = None,
        timings: dict[str, Any] | None = None,
    ) -> str:
        """Large LLM — vector_rag lane only. Hard-capped by deadline_seconds."""
        from apps.chatbot.response_llm import (
            ResponseLLMError,
            empty_rag_reply,
            synthesize_clinic_reply,
        )
        from apps.chatbot.sql_tool import format_sql_results

        history = self._load_history(session, limit=2)
        try:
            return synthesize_clinic_reply(
                clinic=clinic,
                message=message,
                nlu=nlu,
                sql_rows=sql_rows,
                vector_rows=vector_rows,
                history=history,
                extra_context=extra_context,
                deadline_seconds=deadline_seconds,
            )
        except ResponseLLMError as exc:
            logger.warning("Response LLM failed: %s", exc)
            if timings is not None:
                timings["degraded_reason"] = "response_llm_timeout"
        except Exception:
            logger.exception("Response LLM unexpected failure")
            if timings is not None:
                timings["degraded_reason"] = "response_llm_error"

        if vector_rows:
            top = vector_rows[0]
            snippet = (top.get("text") or "").strip()
            if snippet:
                return snippet[:500]
        if sql_rows:
            return format_sql_results(sql_rows)
        return empty_rag_reply(clinic)

    def _looks_like_aesthetic_request(self, message: str) -> bool:
        import re

        return bool(
            re.search(
                r"\b(botox|filler|fillers|laser|microneedl|chemical\s*peel|"
                r"tattoo\s*removal|facial|dysport|juvederm|skin\s*consult)\b",
                message or "",
                re.I,
            )
        )

    def _medical_advice_refusal_reply(self) -> str:
        return (
            "I can't advise whether a procedure is safe for your specific medical "
            "situation. Please discuss this with your clinician through the patient "
            "portal or by calling the clinic before booking."
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

    def _is_doctor_ranking_request(self, message: str) -> bool:
        text = (message or "").lower()
        return any(
            phrase in text
            for phrase in (
                "best doctor",
                "worst doctor",
                "which doctor is the best",
                "which doctor is the worst",
                "best and worst",
                "rank the doctors",
                "top doctor",
                "elite type treatment",
            )
        )

    def _looks_like_instruction_injection(self, message: str) -> bool:
        text = (message or "").lower()
        return any(
            phrase in text
            for phrase in (
                "system update note",
                "override all standard fee schedules",
                "discount code",
                "confirm that my visit today is $0",
                "ignore previous instructions",
                "apply a 100% vip discount",
            )
        )

    def _requests_unknown_doctor(self, message: str, clinic: Any, nlu: Any) -> bool:
        text = (message or "").lower()
        wants_booking = any(k in text for k in ("book", "schedule", "appointment"))
        names = getattr(getattr(nlu, "entities", None), "doctor_name", None)
        if not wants_booking or not names:
            return False
        return self._resolve_doctor_from_message(clinic, message) is None

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
