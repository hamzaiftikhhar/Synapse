"""Clinic Capability Resolver — shadow mode (fallback comparison tool).

Runs `resolve_capability` + `decide_routing` against real live requests,
purely for comparison logging. This module must NEVER be allowed to
influence a real response: it is fired from a background daemon thread
*after* the real pipeline has already produced its answer, and any
exception here is caught and logged, never raised into the request path.

Now that the live vertical slice (`planner.apply_capability_resolution`,
called synchronously from `engine.py`) handles every message
`resolver_context_for_nlu` returns non-None for, `engine.py` skips calling
this module for any turn where the live path already consulted the
resolver (`exec_plan.capability_resolver_used`) -- avoiding a redundant
second LLM call for the identical purpose. This module is kept, unchanged
in behavior, as the fallback comparison tool for any future case the live
slice doesn't cover (e.g. if its gating is narrowed again during
rollback), not deleted per "keep old mechanisms available."

Cost/latency discipline: only intents with a plausible capability-
resolution shape are shadow-evaluated at all (`resolver_context_for_nlu`)
-- greeting/hours/insurance/farewell/off_topic/etc. are skipped entirely.
Everything here reuses existing NLU output; nothing here adds a new NLU
field or prompt rule.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

from django.db import close_old_connections

from apps.chatbot.booking.capability_resolver import (
    resolve_capability,
    resolver_context_for_nlu,
)
from apps.chatbot.booking.capability_routing_policy import decide_routing

logger = logging.getLogger(__name__)

_LOG_PATH = Path("logs") / "capability_shadow" / "shadow.jsonl"
_WRITE_LOCK = threading.Lock()


def _write_log_line(record: dict[str, Any]) -> None:
    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, default=str) + "\n"
    with _WRITE_LOCK:
        try:
            import fcntl

            with open(_LOG_PATH, "a") as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                try:
                    f.write(line)
                finally:
                    fcntl.flock(f, fcntl.LOCK_UN)
        except ImportError:
            # fcntl is POSIX-only; fall back to the in-process lock alone
            # (still race-safe across threads in one process, just not
            # across separate worker processes on a non-POSIX host).
            with open(_LOG_PATH, "a") as f:
                f.write(line)


def _run_shadow(
    *,
    clinic_id: str,
    message: str,
    context: str,
    old_pipeline: dict[str, Any],
) -> None:
    close_old_connections()
    try:
        from apps.clinics.models import Clinic

        clinic = Clinic.objects.filter(id=clinic_id).first()
        if clinic is None:
            return

        started = time.perf_counter()
        resolution = resolve_capability(clinic, message, context=context)
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        decision = decide_routing(context, resolution)

        record = {
            "clinic_id": clinic_id,
            "message": message,
            "context": context,
            "resolver": {
                "outcome": resolution.outcome,
                "latency_ms": latency_ms,
                "candidates": [
                    {
                        "type": c.target_type,
                        "id": c.id,
                        "name": c.name,
                        "confidence": c.confidence,
                        "reasoning": c.reasoning,
                    }
                    for c in resolution.candidates
                ],
            },
            "routing_decision": {
                "action": decision.action,
                "specialty_ids": decision.specialty_ids,
                "service_ids": decision.service_ids,
                "informational_service_candidates": decision.informational_service_candidates,
                "reasoning": decision.reasoning,
            },
            "old_pipeline": old_pipeline,
        }
        _write_log_line(record)
    except Exception:
        logger.exception("capability_shadow failed clinic=%s", clinic_id)
    finally:
        close_old_connections()


def emit_capability_shadow(
    *,
    clinic: Any,
    message: str,
    nlu_result: Any,
    exec_plan: Any,
    sql_rows: list[dict[str, Any]] | None,
) -> None:
    """Fire-and-forget: never blocks, never raises, never touches the real
    response. Call this only after the real pipeline's response has
    already been fully decided."""
    context = resolver_context_for_nlu(nlu_result)
    if context is None:
        return

    handlers = [
        block.get("handler")
        for block in (sql_rows or [])
        if isinstance(block, dict) and block.get("handler")
    ]
    n_rows = sum(
        len(block.get("rows") or [])
        for block in (sql_rows or [])
        if isinstance(block, dict)
    )
    old_pipeline = {
        "intent": nlu_result.intent.value,
        "direct_mode": getattr(exec_plan, "direct_mode", None),
        "sql_tasks": list(getattr(exec_plan, "sql_tasks", []) or []),
        "resolved_service_ids": list(getattr(exec_plan, "resolved_service_ids", []) or []),
        "sql_handlers": handlers,
        "sql_found": any(
            bool(block.get("found"))
            for block in (sql_rows or [])
            if isinstance(block, dict)
        ),
        "n_rows": n_rows,
    }

    clinic_id = str(getattr(clinic, "id", "") or "")
    if not clinic_id:
        return

    try:
        threading.Thread(
            target=_run_shadow,
            kwargs={
                "clinic_id": clinic_id,
                "message": message,
                "context": context,
                "old_pipeline": old_pipeline,
            },
            name="capability-shadow",
            daemon=True,
        ).start()
    except Exception:
        # Thread creation itself failing (e.g. resource exhaustion) must
        # still never propagate into the real response -- this function's
        # whole contract is "never raises, never blocks."
        logger.exception("capability_shadow thread spawn failed")
