"""Chat routing evaluation harness — large paraphrased batteries, no live LLM required."""

from __future__ import annotations

from apps.chatbot.eval.cases import EvalCase, build_eval_cases
from apps.chatbot.eval.runner import EvalReport, evaluate_cases, evaluate_routing_case

__all__ = [
    "EvalCase",
    "EvalReport",
    "build_eval_cases",
    "evaluate_cases",
    "evaluate_routing_case",
]
