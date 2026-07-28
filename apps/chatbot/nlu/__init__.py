"""Provider-agnostic Intent & Entity NLU for clinic chatbot routing."""

from apps.chatbot.nlu.base import NLUError
from apps.chatbot.nlu.decision import DecisionEngine
from apps.chatbot.nlu.factory import get_nlu_provider, reset_nlu_provider
from apps.chatbot.nlu.intent_entity import IntentEntityService
from apps.chatbot.nlu.schemas import NLUResult, Route, RouteDecision

__all__ = [
    "DecisionEngine",
    "IntentEntityService",
    "NLUError",
    "NLUResult",
    "Route",
    "RouteDecision",
    "get_nlu_provider",
    "reset_nlu_provider",
]
#why we create the __all__ list? because it's a way to export the public API of the module.