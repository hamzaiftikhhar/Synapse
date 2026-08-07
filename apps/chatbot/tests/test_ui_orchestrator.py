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

    @patch("apps.chatbot.booking.discovery.suggest_specialties", return_value=([], ""))
    def test_unauthenticated_cancel_shows_verify_identity(self, _mock_suggest):
        """patient_appointments returns meta={requires_auth: True} when
        ctx.patient is None (apps/chatbot/sql_tool/handlers/appointments.py)
        — that must surface as a structured verify_identity card, not just
        prose the user has to read, and it must win primary_component.

        Regression: "I want to cancel my appointment" is a *transactional*
        cancel, so planner.py also sets exec_plan.booking=True — and
        build_ui_meta's booking-card branch used to `return` before the
        sql_results loop that reads patient_appointments ever ran, so
        verify_identity was silently dropped whenever this happened
        together with a real cancel/reschedule request (i.e. always, since
        patient_appointments only ever fires for those two intents)."""
        meta = build_ui_meta(
            clinic=type("C", (), {"name": "Test", "phone": ""})(),
            intent="cancel_appointment",
            route="sql_fast",
            sql_results=[
                {
                    "handler": "patient_appointments",
                    "found": False,
                    "rows": [],
                    "meta": {"requires_auth": True, "auth_prompt": True},
                }
            ],
            message="I want to cancel my appointment",
            ui_priority="booking",
            exec_plan_booking=True,
        )
        self.assertTrue(meta.get("verify_identity"))
        self.assertEqual(meta.get("primary_component"), "verify_identity")

    @patch("apps.chatbot.booking.discovery.suggest_specialties", return_value=([], ""))
    def test_authenticated_cancel_shows_appointment_cards(self, _mock_suggest):
        """Regression: real appointments must win primary_component over the
        "book a new visit instead" wizard card — both get attached together
        for a transactional cancel (exec_plan_booking=True), but the wizard
        used to be checked first in _pick_primary_component, so an
        authenticated patient asking to cancel would see a "start a new
        booking" wizard instead of their actual appointment with Cancel/
        Reschedule buttons — the opposite of what they asked for."""
        meta = build_ui_meta(
            clinic=type("C", (), {"name": "Test", "phone": ""})(),
            intent="cancel_appointment",
            route="sql_fast",
            sql_results=[
                {
                    "handler": "patient_appointments",
                    "found": True,
                    "rows": [
                        {
                            "id": "a1",
                            "doctor": "Dr. Thorne",
                            "doctor_id": "d1",
                            "service": "Cleaning",
                            "start_time": "2026-08-10T09:00:00",
                            "end_time": "2026-08-10T09:30:00",
                            "status": "confirmed",
                            "confirmation_code": "ABC123",
                        }
                    ],
                }
            ],
            message="I want to cancel my appointment",
            ui_priority="booking",
            exec_plan_booking=True,
        )
        self.assertNotIn("verify_identity", meta)
        self.assertIn("booking", meta)
        self.assertEqual(meta.get("primary_component"), "appointments")
        self.assertEqual(meta["appointments"][0]["doctor"], "Dr. Thorne")
        self.assertEqual(meta["appointments"][0]["id"], "a1")

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
