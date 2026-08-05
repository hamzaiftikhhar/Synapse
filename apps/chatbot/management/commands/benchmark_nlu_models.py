"""Benchmark NLU models on the offline eval message set.

Usage:
  python manage.py benchmark_nlu_models
  python manage.py benchmark_nlu_models --models gpt-4.1-nano,gpt-4.1-mini --limit 50

Compares latency + lane accuracy. Does not guess a winner — prints a table.
"""

from __future__ import annotations

import time
from collections import Counter

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.chatbot.eval.cases import build_eval_cases
from apps.chatbot.eval.runner import evaluate_routing_case
from apps.chatbot.nlu.factory import reset_nlu_provider
from apps.chatbot.nlu.openai_provider import OpenAINLUProvider
from apps.chatbot.nlu.prompts import build_user_prompt, get_system_prompt
from apps.chatbot.nlu.rules import try_rule_classify


class Command(BaseCommand):
    help = "Benchmark NLU models for latency and routing accuracy"

    def add_arguments(self, parser):
        parser.add_argument(
            "--models",
            default="gpt-4.1-nano,gpt-4.1-mini",
            help="Comma-separated OpenAI model names",
        )
        parser.add_argument("--limit", type=int, default=80)
        parser.add_argument(
            "--live",
            action="store_true",
            help="Call live APIs (costs money). Default is rules-only smoke.",
        )

    def handle(self, *args, **options):
        models = [m.strip() for m in str(options["models"]).split(",") if m.strip()]
        limit = int(options["limit"])
        live = bool(options["live"])
        cases = build_eval_cases()[:limit]

        self.stdout.write(f"Cases: {len(cases)} live={live}")
        self.stdout.write(f"Prompt chars≈{len(get_system_prompt())}")

        if not live:
            # Offline baseline using existing evaluate_routing_case (rules path)
            started = time.perf_counter()
            passed = 0
            for case in cases:
                if evaluate_routing_case(case).passed:
                    passed += 1
            elapsed = (time.perf_counter() - started) * 1000
            self.stdout.write(
                self.style.SUCCESS(
                    f"offline_rules accuracy={passed}/{len(cases)} "
                    f"({100 * passed / max(1, len(cases)):.1f}%) "
                    f"total_ms={elapsed:.0f}"
                )
            )
            self.stdout.write(
                "Re-run with --live to measure gpt-4.1-nano vs gpt-4.1-mini latency/accuracy."
            )
            return

        if not settings.OPENAI_API_KEY:
            self.stderr.write("OPENAI_API_KEY required for --live")
            return

        rows = []
        for model in models:
            latencies: list[float] = []
            intent_ok = 0
            provider = OpenAINLUProvider(
                model_name=model, api_key=settings.OPENAI_API_KEY
            )
            for case in cases:
                # Prefer live NLU; compare intent family loosely via rules expected
                t0 = time.perf_counter()
                try:
                    raw = provider.classify(message=case.message, timeout=3.5)
                    latencies.append((time.perf_counter() - t0) * 1000)
                    pred = str((raw or {}).get("intent") or "")
                    # Soft check: live intent matches strong-rule intent when rules fire
                    rule = try_rule_classify(case.message, tier="strong") or try_rule_classify(
                        case.message, tier="fast"
                    )
                    if rule and rule.get("intent") == pred:
                        intent_ok += 1
                    elif not rule:
                        intent_ok += 1  # no gold rule — count as non-fail
                except Exception as exc:
                    latencies.append((time.perf_counter() - t0) * 1000)
                    self.stderr.write(f"{model} error: {exc}")
            avg = sum(latencies) / max(1, len(latencies))
            p95 = sorted(latencies)[int(0.95 * (len(latencies) - 1))] if latencies else 0
            rows.append((model, avg, p95, intent_ok, len(cases)))

        self.stdout.write("\nModel | avg_ms | p95_ms | soft_acc")
        for model, avg, p95, ok, n in rows:
            self.stdout.write(
                f"{model:16} | {avg:7.0f} | {p95:7.0f} | {ok}/{n} ({100*ok/max(1,n):.1f}%)"
            )
        reset_nlu_provider()
