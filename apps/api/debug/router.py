"""Development-only debug endpoints — not mounted in production."""

import time

from django.conf import settings
from ninja import Router
from ninja.errors import HttpError

from apps.api.auth.deps import clinic_from, jwt_auth
from apps.api.debug.schemas import (
    DebugNLUIn,
    DebugNLUOut,
    DebugSQLBlockOut,
    DebugSQLIn,
    DebugSQLOut,
    DebugSearchHitOut,
    DebugSearchIn,
    DebugSearchOut,
)
from apps.chatbot.nlu import DecisionEngine, IntentEntityService, NLUError
from apps.chatbot.sql_tool import SQLTool, format_sql_results
from apps.knowledge.embeddings import get_embedding_service
from apps.knowledge.services.similarity_search import SimilaritySearchService

router = Router(tags=["Debug"])


@router.post("/search", response=DebugSearchOut, auth=jwt_auth)
def debug_search(request, payload: DebugSearchIn):
    """
    Test vector retrieval without calling an LLM.

    Only available when DEBUG=True.
    """
    if not settings.DEBUG:
        raise HttpError(404, "Not found")

    clinic = clinic_from(request)
    service = get_embedding_service()
    top_k = max(1, min(payload.top_k, 20))

    hits = SimilaritySearchService.search(
        clinic=clinic,
        query=payload.query,
        top_k=top_k,
    )

    return DebugSearchOut(
        query=payload.query,
        embedding_provider=service.provider_name,
        embedding_model=service.model_name,
        embedding_dimensions=service.dimensions,
        top_results=[
            DebugSearchHitOut(
                score=hit.score,
                document=hit.document.file_name,
                chunk_number=hit.chunk.chunk_number,
                heading=hit.chunk.heading or "",
                text=hit.chunk.content,
            )
            for hit in hits
        ],
    )


@router.post("/nlu", response=DebugNLUOut, auth=jwt_auth)
def debug_nlu(request, payload: DebugNLUIn):
    """
    Test Intent & Entity classification + Decision Engine routing.

    Does not run SQL, vector search, or final LLM reply generation.
    Only available when DEBUG=True.
    """
    if not settings.DEBUG:
        raise HttpError(404, "Not found")

    clinic = clinic_from(request)
    try:
        nlu = IntentEntityService().analyze(
            clinic=clinic,
            message=payload.message,
            conversation_context=payload.conversation_context or None,
            log_usage=True,
        )
    except NLUError as exc:
        raise HttpError(400, str(exc)) from exc

    t0 = time.perf_counter()
    decision = DecisionEngine.decide(nlu)
    nlu.timings.decision_engine_ms = (time.perf_counter() - t0) * 1000

    return DebugNLUOut(
        message=payload.message,
        nlu_provider=nlu.provider,
        nlu_model=nlu.model,
        classifier_source=nlu.timings.classifier_source,
        route=decision.route.value,
        needs_sql=decision.needs_sql,
        needs_vector=decision.needs_vector,
        needs_llm=decision.needs_llm,
        safety_message=decision.safety_message,
        timings=nlu.timings.to_dict(),
        nlu=nlu.to_dict(),
    )


@router.post("/sql", response=DebugSQLOut, auth=jwt_auth)
def debug_sql(request, payload: DebugSQLIn):
    """
    Test SQL Tool handlers for a message (NLU → Decision → SQL queries).

    Does not call vector search or final LLM reply generation.
    Only available when DEBUG=True.
    """
    if not settings.DEBUG:
        raise HttpError(404, "Not found")

    clinic = clinic_from(request)
    try:
        nlu = IntentEntityService().analyze(
            clinic=clinic,
            message=payload.message,
            conversation_context=payload.conversation_context or None,
            log_usage=False,
        )
    except NLUError as exc:
        raise HttpError(400, str(exc)) from exc

    if payload.intent:
        from apps.chatbot.nlu.schemas import Intent, VALID_INTENTS

        intent_raw = payload.intent.strip().lower()
        if intent_raw in VALID_INTENTS:
            nlu.intent = Intent(intent_raw)

    decision = DecisionEngine.decide(nlu)
    if not decision.needs_sql:
        return DebugSQLOut(
            message=payload.message,
            intent=nlu.intent.value,
            route=decision.route.value,
            sql_ms=0.0,
            formatted_response="Decision engine did not request SQL for this message.",
            results=[],
        )

    t0 = time.perf_counter()
    sql_results = SQLTool.run(clinic, nlu)
    sql_ms = (time.perf_counter() - t0) * 1000
    sql_dicts = [r.to_dict() for r in sql_results]

    return DebugSQLOut(
        message=payload.message,
        intent=nlu.intent.value,
        route=decision.route.value,
        sql_ms=sql_ms,
        formatted_response=format_sql_results(sql_dicts),
        results=[
            DebugSQLBlockOut(
                handler=block["handler"],
                found=block["found"],
                summary=block["summary"],
                row_count=len(block.get("rows") or []),
                rows=block.get("rows") or [],
                meta=block.get("meta") or {},
            )
            for block in sql_dicts
        ],
    )
