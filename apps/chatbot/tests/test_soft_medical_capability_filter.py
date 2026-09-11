"""Live-reproduced bug (ROADMAP.md): a real "Lumina Skin & Laser
Dermatology" transcript showed two unrelated messages --

    "CAN i use skinorene cream after a sunburn"
    "whihc US based sunblock is best for a sensitive skin"

-- both getting the byte-identical "Found 2 doctors who may be a good
fit" response, with zero acknowledgment of either question. Root cause,
confirmed via real pipeline-debug logs (logs/chat/2026-09-11_13-37-*.json):

1. `planner.compute_message_sensors`'s `soft_medical` flag fired purely
   from `medical_question_mode not in ("definitional", "risk")` -- no
   requirement the message actually describe a personal concern. The
   second message had NO symptom entity and confidence 0.65 (the
   classifier's own reasoning: "unclear if asking about product use or
   sun protection") yet still set `soft_medical=True`.
2. Once `soft_medical=True` reached `apply_capability_resolution` and the
   resolver found a matching specialty (trivial for a narrow, single-
   specialty clinic like Lumina, where nearly any skin-adjacent word
   resolves to its one specialty), the plan was converted straight to a
   bare `sql_tasks=["doctors"]` SQL dispatch -- bypassing
   `_soft_medical_reply`/`_maybe_suggest_specialties` entirely, so the
   final text was pure SQL-formatter boilerplate with no framing at all.

Two independent fixes, both covered here:
  (a) gate the mode-only soft_medical trigger on the confidence band
      (planner.py) so a low-confidence, no-symptom "personal" label
      doesn't alone trigger the concern-routing lane;
  (b) when soft_medical *does* still convert into a real doctor search
      via the capability resolver, prepend a short no-advice
      acknowledgment instead of a bare doctor list (engine.py).
"""

from __future__ import annotations

from unittest.mock import Mock

from django.test import SimpleTestCase

from apps.chatbot.engine import ChatEngine
from apps.chatbot.nlu.schemas import ExtractedEntities, Intent, NLUResult
from apps.chatbot.planner import ExecutionPlan, compute_message_sensors


def _nlu(**kwargs) -> NLUResult:
    defaults = dict(
        intent=Intent.MEDICAL_QUESTION,
        confidence=0.85,
        entities=ExtractedEntities(),
        medical_question_mode="personal",
    )
    defaults.update(kwargs)
    return NLUResult(**defaults)


class SoftMedicalConfidenceGateTests(SimpleTestCase):
    """compute_message_sensors's soft_medical computation, isolated from
    everything downstream."""

    def test_low_confidence_personal_mode_with_no_symptom_does_not_trigger(self):
        """The exact live-reproduced shape: mode='personal', no symptom
        entity, confidence low enough to land below the mid threshold."""
        nlu = _nlu(confidence=0.65, entities=ExtractedEntities())
        sensors = compute_message_sensors(
            message="whihc US based sunblock is best for a sensitive skin",
            nlu=nlu,
            document_catalog=[],
            service_catalog=[],
        )
        self.assertFalse(sensors.soft_medical)

    def test_high_confidence_personal_mode_with_real_symptom_still_triggers(self):
        """The genuinely personal case in the same transcript ("...after a
        sunburn", entities.symptom='sunburn', confidence 0.85) must be
        completely unaffected by the gate."""
        nlu = _nlu(
            confidence=0.85,
            entities=ExtractedEntities(symptom="sunburn"),
        )
        sensors = compute_message_sensors(
            message="CAN i use skinorene cream after a sunburn",
            nlu=nlu,
            document_catalog=[],
            service_catalog=[],
        )
        self.assertTrue(sensors.soft_medical)

    def test_low_confidence_but_real_symptom_entity_still_triggers(self):
        """A real, Python-verified symptom signal must fire soft_medical
        regardless of how unsure the classifier's confidence score was --
        only the mode-only branch is gated, not the symptom-entity branch."""
        nlu = _nlu(
            confidence=0.5,
            entities=ExtractedEntities(symptom="knee pain"),
        )
        sensors = compute_message_sensors(
            message="something about my knee pain",
            nlu=nlu,
            document_catalog=[],
            service_catalog=[],
        )
        self.assertTrue(sensors.soft_medical)

    def test_low_confidence_but_looks_like_symptom_keyword_still_triggers(self):
        """Same as above for the other existing OR-branch (deterministic
        keyword match), independent of the NLU-confidence gate."""
        nlu = _nlu(confidence=0.5, entities=ExtractedEntities())
        sensors = compute_message_sensors(
            message="I have a bad headache today",
            nlu=nlu,
            document_catalog=[],
            service_catalog=[],
        )
        self.assertTrue(sensors.soft_medical)

    def test_mid_confidence_personal_mode_with_no_symptom_still_triggers(self):
        """Only LOW/VERY_LOW bands are gated -- a mid-or-higher-confidence
        personal-mode classification with no symptom entity (the
        classifier plausibly extracted the concern into free text instead
        of the symptom field) keeps today's existing behavior."""
        nlu = _nlu(confidence=0.85, entities=ExtractedEntities())
        sensors = compute_message_sensors(
            message="I'm worried I might have some kind of skin condition",
            nlu=nlu,
            document_catalog=[],
            service_catalog=[],
        )
        self.assertTrue(sensors.soft_medical)


class SoftMedicalCapabilityFilterPreambleTests(SimpleTestCase):
    """engine.py's _compose_from_plan: when a soft_medical concern was
    converted into a real doctor search by the capability resolver
    (planner.apply_capability_resolution's "filter" branch, which leaves
    `soft_medical=True` on the resulting plan -- see its `replace()`
    call), the final text must acknowledge the question instead of
    handing back a bare, boilerplate doctor list."""

    def _sql_rows(self):
        return [
            {
                "handler": "search_doctors",
                "found": True,
                "rows": [
                    {"id": "doc-1", "full_name": "Dr. Chloe Bennet"},
                    {"id": "doc-2", "full_name": "Dr. Naomi Cross"},
                ],
                "meta": {},
            }
        ]

    def _base_kwargs(self, exec_plan):
        return dict(
            clinic=Mock(),
            message="whihc US based sunblock is best for a sensitive skin",
            nlu=_nlu(confidence=0.65, entities=ExtractedEntities()),
            exec_plan=exec_plan,
            sql_rows=self._sql_rows(),
            vector_rows=[],
            session=None,
            booking_commit=False,
            suggested=[],
            guidance="",
            soft_medical=True,
            timings={},
        )

    def test_capability_resolver_filtered_doctor_list_gets_acknowledgment(self):
        exec_plan = ExecutionPlan(
            sql_tasks=["doctors"],
            soft_medical=True,
            capability_resolver_used=True,
            reason="planner_soft_medical_direct|capability_resolver_filter",
        )
        text = ChatEngine()._compose_from_plan(**self._base_kwargs(exec_plan))
        self.assertIn("can't give medical or product advice", text)
        self.assertIn("Found 2 doctors", text)

    def test_ordinary_doctor_search_without_capability_resolver_is_unchanged(self):
        """A completely normal doctor_search-intent SQL dispatch
        (capability_resolver_used=False, soft_medical=False) must not pick
        up the new preamble -- this only fires for the specific soft_
        medical -> resolver-filter conversion."""
        exec_plan = ExecutionPlan(
            sql_tasks=["doctors"],
            soft_medical=False,
            capability_resolver_used=False,
            reason="planner_execution_plan|sql:doctors",
        )
        kwargs = self._base_kwargs(exec_plan)
        kwargs["soft_medical"] = False
        text = ChatEngine()._compose_from_plan(**kwargs)
        self.assertNotIn("can't give medical or product advice", text)
        self.assertIn("Found 2 doctors", text)
