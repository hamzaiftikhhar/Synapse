"""Structured AI pipeline debugger for chat requests.

On in local development by default (`DEBUG_CHAT_PIPELINE`, default True
in `config.settings.development`). Forced off under `manage.py test` and
`run_chat_eval` so the suite/eval don't dump a trace per case.

Prints a clean stage-by-stage trace to the terminal and optionally saves
JSON artifacts under logs/chat/ for later review.

This is the primary way to inspect Small-LLM input, planner scores,
SQL results, vector chunks, Large-LLM prompts, and final responses.
Swagger is only for sending requests — not for understanding the pipeline.
"""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from django.conf import settings

logger = logging.getLogger("apps.chatbot.pipeline")

# Same reason get_email_provider() never selects Resend under `manage.py test`:
# this process loads development settings (and a True default) but must not
# print a full pipeline dump for every unit test / eval case.
_SILENT_PIPELINE_COMMANDS = frozenset({"test", "run_chat_eval"})


def pipeline_debug_enabled() -> bool:
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command in _SILENT_PIPELINE_COMMANDS:
        return False
    return bool(getattr(settings, "DEBUG_CHAT_PIPELINE", False))


def _save_json_enabled() -> bool:
    return bool(getattr(settings, "DEBUG_CHAT_PIPELINE_SAVE_JSON", True))


def _truncate(text: str, limit: int = 2400) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n… [truncated {len(text) - limit} chars]"


def _safe(value: Any) -> Any:
    try:
        json.dumps(value, default=str)
        return value
    except Exception:
        return str(value)


@dataclass
class ChatPipelineTrace:
    """Accumulates one chat request's pipeline evidence."""

    user_message: str = ""
    clinic_id: str = ""
    clinic_name: str = ""
    session_id: str = ""
    patient_id: str = ""
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    nlu: dict[str, Any] = field(default_factory=dict)
    planner: dict[str, Any] = field(default_factory=dict)
    sql: dict[str, Any] = field(default_factory=dict)
    vector: dict[str, Any] = field(default_factory=dict)
    large_llm: dict[str, Any] = field(default_factory=dict)
    final: dict[str, Any] = field(default_factory=dict)
    timings: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at,
            "user_message": self.user_message,
            "clinic_id": self.clinic_id,
            "clinic_name": self.clinic_name,
            "session_id": self.session_id,
            "patient_id": self.patient_id,
            "nlu": self.nlu,
            "planner": self.planner,
            "sql": self.sql,
            "vector": self.vector,
            "large_llm": self.large_llm,
            "final": self.final,
            "timings": self.timings,
        }

    def emit(self) -> Path | None:
        """Print terminal report and optionally save JSON. Returns JSON path if saved."""
        if not pipeline_debug_enabled():
            return None
        report = self.render_terminal()
        # Print to stdout so runserver shows it clearly
        print(report, flush=True)
        logger.info("chat_pipeline_trace clinic=%s lane=%s", self.clinic_id, self.final.get("lane"))
        if _save_json_enabled():
            return self._save_json()
        return None

    def render_terminal(self) -> str:
        nlu = self.nlu
        planner = self.planner
        sql = self.sql
        vector = self.vector
        llm = self.large_llm
        final = self.final
        scores = planner.get("scores") or {}

        lines = [
            "",
            "==================== NEW CHAT REQUEST ====================",
            "",
            "User:",
            f'"{self.user_message}"',
            "",
            "Clinic:",
            self.clinic_name or self.clinic_id or "(unknown)",
            "",
            "----------------------------------------------------------",
            "1. Request Received",
            "----------------------------------------------------------",
            f"Clinic ID:  {self.clinic_id or '-'}",
            f"Session ID: {self.session_id or '-'}",
            f"Patient ID: {self.patient_id or '-'}",
            "",
            "----------------------------------------------------------",
            "2. Small LLM (NLU)",
            "----------------------------------------------------------",
            f"Source:     {nlu.get('source') or '-'}",
            f"Provider:   {nlu.get('provider') or '-'}",
            f"Model:      {nlu.get('model') or '-'}",
            f"Intent:     {nlu.get('intent') or '-'}",
            f"Confidence: {nlu.get('confidence')}",
            f"Entities:   {_fmt_json(nlu.get('entities'))}",
            f"Flags:      needs_sql={nlu.get('needs_sql')} needs_vector={nlu.get('needs_vector')} "
            f"needs_llm={nlu.get('needs_llm')} emergency={nlu.get('is_emergency')} "
            f"document_needed={nlu.get('document_needed')}",
            f"SQL tool:   {nlu.get('sql_tool') or '-'}",
            f"Filter:     {nlu.get('service_filter_mode') or '-'}",
            f"Reasoning:  {nlu.get('reasoning') or '-'}",
            "",
            "NLU System Prompt:",
            _truncate(str(nlu.get("system_prompt") or "(not captured)"), 1800),
            "",
            "NLU User Prompt:",
            _truncate(str(nlu.get("user_prompt") or "(not captured)"), 1800),
            "",
            "----------------------------------------------------------",
            "3. Execution Plan (Planner)",
            "----------------------------------------------------------",
            f"Primary Lane:  {planner.get('primary_lane') or planner.get('lane') or final.get('lane') or '-'}",
            f"Reason:        {planner.get('reason') or '-'}",
            f"Direct:        {planner.get('direct')} mode={planner.get('direct_mode') or '-'}",
            f"Booking:       {planner.get('booking')}",
            f"SQL tasks:     {planner.get('sql_tasks') or []}",
            f"Vector tasks:  {planner.get('vector_tasks') or []}",
            f"Use Large LLM: {planner.get('use_response_llm')}",
            f"Clarify:       {planner.get('clarify')}",
            f"Degraded:      {planner.get('degraded') or (planner.get('facts') or {}).get('degraded')}",
            "Scores:",
            f"  Emergency: {scores.get('emergency', 0):.3f}",
            f"  Direct:    {scores.get('direct', 0):.3f}",
            f"  Booking:   {scores.get('booking', 0):.3f}",
            f"  SQL:       {scores.get('sql', 0):.3f}",
            f"  Vector:    {scores.get('vector', 0):.3f}",
            f"  Clarify:   {scores.get('clarify', 0):.3f}",
            "",
            "----------------------------------------------------------",
            "4. SQL",
            "----------------------------------------------------------",
            f"Executed: {sql.get('executed', False)}",
            f"Handlers: {sql.get('handlers') or '-'}",
            "Returned rows:",
            _truncate(_fmt_json(sql.get("rows") or []), 2000),
            "",
            "----------------------------------------------------------",
            "5. Vector Search",
            "----------------------------------------------------------",
            f"Executed: {vector.get('executed', False)}",
            f"Hits:     {vector.get('hit_count', 0)}",
        ]

        chunks = vector.get("chunks") or []
        if not chunks:
            lines.append("(no chunks retrieved)")
        else:
            for i, chunk in enumerate(chunks[:5], start=1):
                lines.extend(
                    [
                        "",
                        f"Chunk {i}",
                        f"Similarity: {float(chunk.get('score') or 0):.4f}",
                        f"Source:     {chunk.get('document') or '-'}",
                        f"Heading:    {chunk.get('heading') or '-'}",
                        "Summary:",
                        _truncate(str(chunk.get("text") or ""), 500),
                    ]
                )

        lines.extend(
            [
                "",
                "----------------------------------------------------------",
                "6. Prompt Construction (Large LLM)",
                "----------------------------------------------------------",
                f"Called: {llm.get('executed', False)}",
                "",
                "System Prompt:",
                _truncate(str(llm.get("system_prompt") or "(not used — SQL/direct lane)"), 1800),
                "",
                "User / Context Prompt:",
                _truncate(str(llm.get("user_prompt") or "(not used — SQL/direct lane)"), 2400),
                "",
                "----------------------------------------------------------",
                "7. Large LLM",
                "----------------------------------------------------------",
                f"Provider: {llm.get('provider') or '-'}",
                f"Model:    {llm.get('model') or '-'}",
                f"Latency:  {llm.get('latency_ms', self.timings.get('llm_ms', 0))} ms",
                f"Tokens:   {llm.get('tokens') or 'n/a'}",
                "",
                "----------------------------------------------------------",
                "8. Final Response",
                "----------------------------------------------------------",
                f"Lane:  {final.get('lane') or '-'}",
                f"Route: {final.get('route') or '-'}",
                "Response:",
                _truncate(str(final.get("response") or ""), 1800),
                "",
                "Timings (ms):",
                _fmt_json(self.timings),
                "",
                "==========================================================",
                "",
            ]
        )
        return "\n".join(lines)

    def _save_json(self) -> Path | None:
        try:
            root = Path(getattr(settings, "BASE_DIR", Path.cwd())) / "logs" / "chat"
            root.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S_%f")
            path = root / f"{stamp}.json"
            path.write_text(
                json.dumps(self.to_dict(), indent=2, default=str, ensure_ascii=False),
                encoding="utf-8",
            )
            print(f"[pipeline-debug] saved {path}", flush=True)
            return path
        except Exception:
            logger.exception("Failed to save chat pipeline JSON")
            return None


def _fmt_json(value: Any) -> str:
    try:
        return json.dumps(_safe(value), indent=2, default=str, ensure_ascii=False)
    except Exception:
        return str(value)


def capture_nlu_prompts(message: str, conversation_context: dict[str, Any] | None) -> dict[str, str]:
    """Rebuild the Small-LLM prompts that classify_message uses."""
    try:
        from apps.chatbot.nlu.prompts import build_user_prompt, get_system_prompt

        return {
            "system_prompt": get_system_prompt(),
            "user_prompt": build_user_prompt(message, conversation_context),
        }
    except Exception:
        logger.exception("Failed to capture NLU prompts")
        return {"system_prompt": "", "user_prompt": ""}


def capture_response_prompts(
    *,
    clinic: Any,
    message: str,
    nlu: Any,
    sql_rows: list[dict[str, Any]],
    vector_rows: list[dict[str, Any]],
    history: list[dict[str, str]] | None = None,
    extra_context: str = "",
) -> dict[str, str]:
    """Rebuild the Large-LLM prompts used by synthesize_clinic_reply."""
    try:
        from apps.chatbot.response_llm import build_response_prompts

        return build_response_prompts(
            clinic=clinic,
            message=message,
            nlu=nlu,
            sql_rows=sql_rows,
            vector_rows=vector_rows,
            history=history or [],
            extra_context=extra_context,
        )
    except Exception:
        logger.exception("Failed to capture response prompts")
        return {"system_prompt": "", "user_prompt": ""}
