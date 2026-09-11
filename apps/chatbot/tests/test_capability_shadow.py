"""capability_shadow.py — must never affect or block the real response.

Context-mapping (`resolver_context_for_nlu`) now lives in, and is tested
in, capability_resolver.py/test_capability_resolver.py -- shared with the
live vertical slice so the two can never drift on "is this relevant."
`emit_capability_shadow` is tested only for its contract with the caller:
it must return immediately regardless of what the resolver does, and it
must never raise into the caller even if everything downstream fails.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from unittest.mock import patch

from django.test import TestCase

from apps.chatbot.booking.capability_shadow import emit_capability_shadow
from apps.chatbot.nlu.schemas import ExtractedEntities, Intent, NLUResult, ResolvedIds
from apps.clinics.models import Clinic


def _nlu(intent: Intent, **entity_kwargs) -> NLUResult:
    return NLUResult(
        intent=intent,
        confidence=0.9,
        entities=ExtractedEntities(**entity_kwargs),
        resolved_ids=ResolvedIds(),
    )


@dataclass
class _FakePlan:
    direct_mode: str | None = None
    sql_tasks: list | None = None
    resolved_service_ids: list | None = None


class EmitCapabilityShadowNeverBlocksOrRaisesTests(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="shadow-clinic",
            name="Shadow Clinic",
            email="shadow@clinic.test",
            phone="+12125550000",
            timezone="America/New_York",
        )

    def test_returns_immediately_even_if_resolver_is_slow(self):
        def _slow_resolve(*args, **kwargs):
            time.sleep(2)
            raise AssertionError("should never actually run in this test's timing window")

        with patch(
            "apps.chatbot.booking.capability_shadow.resolve_capability",
            side_effect=_slow_resolve,
        ):
            started = time.perf_counter()
            emit_capability_shadow(
                clinic=self.clinic,
                message="my teeth are a bit yellow",
                nlu_result=_nlu(Intent.MEDICAL_QUESTION, symptom="yellow teeth"),
                exec_plan=_FakePlan(sql_tasks=[]),
                sql_rows=[],
            )
            elapsed = time.perf_counter() - started
        self.assertLess(elapsed, 0.5)

    def test_skipped_intent_does_not_spawn_a_thread_at_all(self):
        with patch(
            "apps.chatbot.booking.capability_shadow.threading.Thread"
        ) as mock_thread:
            emit_capability_shadow(
                clinic=self.clinic,
                message="hello",
                nlu_result=_nlu(Intent.GREETING),
                exec_plan=_FakePlan(),
                sql_rows=[],
            )
        mock_thread.assert_not_called()

    def test_never_raises_even_if_thread_spawn_itself_fails(self):
        with patch(
            "apps.chatbot.booking.capability_shadow.threading.Thread",
            side_effect=RuntimeError("thread creation failed"),
        ):
            try:
                emit_capability_shadow(
                    clinic=self.clinic,
                    message="I need stitches",
                    nlu_result=_nlu(Intent.SERVICES_OFFERED),
                    exec_plan=_FakePlan(sql_tasks=["services"]),
                    sql_rows=[],
                )
            except Exception as exc:  # noqa: BLE001
                self.fail(f"emit_capability_shadow must never raise, got: {exc}")
