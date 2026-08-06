"""UI orchestrator — primary component and progressive disclosure."""

from __future__ import annotations

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
