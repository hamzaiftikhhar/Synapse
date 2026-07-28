"""Development-only debug endpoints — not mounted in production."""

from django.conf import settings
from ninja import Router
from ninja.errors import HttpError

from apps.api.auth.deps import clinic_from, jwt_auth
from apps.api.debug.schemas import (
    DebugNLUIn,
    DebugNLUOut,
    DebugSearchHitOut,
    DebugSearchIn,
    DebugSearchOut,
)
from apps.chatbot.nlu import DecisionEngine, IntentEntityService, NLUError
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

    decision = DecisionEngine.decide(nlu)
    return DebugNLUOut(
        message=payload.message,
        nlu_provider=nlu.provider,
        nlu_model=nlu.model,
        route=decision.route.value,
        needs_sql=decision.needs_sql,
        needs_vector=decision.needs_vector,
        needs_llm=decision.needs_llm,
        safety_message=decision.safety_message,
        nlu=nlu.to_dict(),
    )
