"""UI orchestrator — primary component and progressive disclosure."""

from __future__ import annotations

from unittest.mock import patch

from django.test import SimpleTestCase

from apps.chatbot.ui_meta import build_ui_meta, orchestrate_ui_meta


class UiOrchestratorTests(SimpleTestCase):
    def test_availability_primary_is_time_slots(self):
        meta = build_ui_meta(
            clinic=type("C", (), {"name": "Test", "phone": ""})(),
            intent="doctor_availability",
            route="sql_fast",
            sql_results=[
                {
                    "handler": "doctor_availability",
                    "found": True,
                    "rows": [
                        {
                            "doctor": "Dr. A",
                            "time": "9:00 AM",
                            "start": "2026-08-07T09:00:00",
                            "doctor_id": "1",
                        }
                    ],
                }
            ],
            ui_priority="primary",
        )
        self.assertEqual(meta.get("primary_component"), "time_slots")
        self.assertTrue(meta.get("time_slots"))

    def test_single_service_suppresses_extra(self):
        meta = orchestrate_ui_meta(
            {
                "services": [{"id": "1", "name": "X-Ray"}],
                "specialties": [{"id": "2", "name": "General"}],
                "recommended": {"type": "service", "action": "select_service"},
            },
            intent="services_offered",
            ui_priority="primary",
        )
        self.assertEqual(meta["primary_component"], "services")
        self.assertNotIn("specialties", meta)

    @patch("apps.chatbot.booking.discovery.suggest_specialties", return_value=([], ""))
    def test_cancel_appointment_gets_booking_card_when_transactional(self, _mock_suggest):
        """Regression: "I want to cancel my appointment" (facts.knowledge_q=False
        in the planner, so exec_plan.booking=True) composes a reply ending in
        "How would you like to book?" but ui_meta.py's booking-card block only
        checked intent in (BOOK_APPOINTMENT, RESCHEDULE_APPOINTMENT) — leaving
        cancel_appointment with no card behind that text at all."""
        meta = build_ui_meta(
            clinic=type("C", (), {"name": "Test", "phone": ""})(),
            intent="cancel_appointment",
            route="sql_vector_llm",
            sql_results=[],
            message="I want to cancel my appointment",
            ui_priority="booking",
            exec_plan_booking=True,
        )
        self.assertIn("booking", meta)
        self.assertTrue(meta["booking"]["launch"])

    def test_cancel_appointment_knowledge_question_gets_no_booking_card(self):
        """The planner deliberately keeps exec_plan.booking=False for a
        knowledge-only cancel question (e.g. "what's your cancellation fee?")
        so it stays on the vector/FAQ path — the card must not appear either,
        or a fee-policy answer would carry a dangling booking wizard."""
        meta = build_ui_meta(
            clinic=type("C", (), {"name": "Test", "phone": ""})(),
            intent="cancel_appointment",
            route="sql_vector_llm",
            sql_results=[],
            message="what's your cancellation fee policy",
            ui_priority="none",
            exec_plan_booking=False,
        )
        self.assertNotIn("booking", meta)
