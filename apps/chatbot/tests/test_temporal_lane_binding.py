"""A temporal refusal must survive every response lane.

The availability handler can correctly conclude that January 13 2024 has
passed and still have that answer overwritten downstream, because only the
sql_fast lane read the refusal. In the vector_rag lane the refusal became one
more context string for the response LLM, which replied "I couldn't find any
available slots for January 13, 2024" — asserting a search that never ran —
and on the next turn treated its own invention as established fact.

Python decides; the LLM does not get a second opinion.
"""

from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase

from apps.chatbot.engine import ChatEngine
from apps.chatbot.sql_tool.formatter import format_sql_results

_REFUSAL = (
    "This clinic is scheduling appointments through Tuesday, September 8, so "
    "December 2026 isn't open for booking yet."
)


def _block(summary=_REFUSAL, *, status="beyond_horizon", searchable=False, **extra):
    meta = {
        "temporal_status": status,
        "temporal_searchable": searchable,
        "authoritative_summary": True,
        "scope_start": "2026-12-01",
        "scope_end": "2026-12-31",
    }
    meta.update(extra)
    return {
        "handler": "doctor_availability",
        "found": False,
        "rows": [],
        "summary": summary,
        "meta": meta,
    }


class RefusalReachesTheReplyTests(TestCase):
    def test_the_refusal_is_detected_on_the_block(self):
        self.assertEqual(ChatEngine._temporal_refusal_text([_block()]), _REFUSAL)

    def test_every_refusing_status_is_detected(self):
        for status in ("past", "unresolved", "ambiguous", "beyond_horizon"):
            self.assertEqual(
                ChatEngine._temporal_refusal_text([_block(status=status)]),
                _REFUSAL,
                msg=status,
            )

    def test_a_searchable_scope_is_left_to_the_normal_lane(self):
        # "No slots that Tuesday" is an ordinary answer; the LLM may phrase it.
        block = _block(
            "No available slots found on Tuesday, August 25.",
            status="resolved",
            searchable=True,
        )
        self.assertEqual(ChatEngine._temporal_refusal_text([block]), "")

    def test_other_handlers_are_not_hijacked(self):
        block = _block()
        block["handler"] = "clinic_hours"
        self.assertEqual(ChatEngine._temporal_refusal_text([block]), "")

    def test_a_block_without_the_authoritative_flag_is_ignored(self):
        block = _block()
        block["meta"].pop("authoritative_summary")
        self.assertEqual(ChatEngine._temporal_refusal_text([block]), "")

    def test_empty_input_is_safe(self):
        self.assertEqual(ChatEngine._temporal_refusal_text([]), "")
        self.assertEqual(ChatEngine._temporal_refusal_text(None), "")


class RefusalBypassesTheResponseLLMTests(TestCase):
    """The vector_rag lane is where this silently failed."""

    def _compose(self, exec_plan, sql_rows):
        engine = ChatEngine()
        return engine._compose_from_plan(
            clinic=None,
            message="is there any slot available for coming december",
            nlu=None,
            exec_plan=exec_plan,
            sql_rows=sql_rows,
            vector_rows=[{"content": "Clinic FAQ text"}],
            session=None,
            booking_commit=None,
            suggested=None,
            guidance=None,
            soft_medical=False,
            timings={},
        )

    class _Plan:
        direct_mode = None
        use_response_llm = True
        vector_tasks = ["general_faq"]
        sql_tasks = ["doctor_availability"]
        booking = False

    def test_the_llm_is_never_called_for_a_refusal(self):
        with patch.object(
            ChatEngine, "_generate_response", side_effect=AssertionError(
                "response LLM must not run for a temporal refusal"
            )
        ):
            reply = self._compose(self._Plan(), [_block()])
        self.assertEqual(reply, _REFUSAL)

    def test_the_refusal_text_is_returned_verbatim(self):
        with patch.object(ChatEngine, "_generate_response", return_value="invented"):
            reply = self._compose(self._Plan(), [_block()])
        self.assertNotIn("invented", reply)
        self.assertIn("isn't open for booking yet", reply)

    def test_the_llm_still_runs_for_an_ordinary_empty_day(self):
        block = _block(
            "No available slots found on Tuesday, August 25.",
            status="resolved",
            searchable=True,
        )
        with patch.object(
            ChatEngine, "_generate_response", return_value="phrased by the llm"
        ):
            reply = self._compose(self._Plan(), [block])
        self.assertEqual(reply, "phrased by the llm")


class FormatterKeepsTheRefusalTests(TestCase):
    def test_the_sql_lane_prints_the_refusal_not_the_generic_empty_line(self):
        self.assertIn("isn't open for booking yet", format_sql_results([_block()]))

    def test_an_ordinary_empty_result_keeps_its_generic_wording(self):
        block = _block("", status="resolved", searchable=True)
        block["meta"].pop("authoritative_summary")
        self.assertNotIn("isn't open for booking", format_sql_results([block]))
