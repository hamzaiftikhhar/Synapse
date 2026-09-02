"""Phase 51 — external, adversarial evaluation layer.

Separate from apps/chatbot/eval (the offline, no-live-LLM routing battery)
and apps/chatbot/tests (regression tests for confirmed bugs). This module
makes real, live ChatEngine calls against a real clinic and is meant to be
run deliberately (it costs real API calls and takes minutes), not on every
CI run — see RESEARCH_FINDINGS.md and TAXONOMY.md alongside this file for
the methodology and `core/management/commands/run_adversarial_eval.py` to
execute it.
"""
