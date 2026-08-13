"""Entity guard and doctor-browse regression tests."""

from __future__ import annotations

from dataclasses import replace

from django.test import SimpleTestCase, TestCase

from apps.chatbot.nlu.entity_guard import entity_grounded_in_message, sanitize_entities
from apps.chatbot.nlu.resolvers import resolve_entities
from apps.chatbot.nlu.schemas import ExtractedEntities, Intent, NLUResult, ResolvedIds
from apps.chatbot.routing.heuristics import apply_routing_heuristics
from apps.chatbot.routing.signals import is_doctor_browse_query
from apps.chatbot.sql_tool import SQLContext
from apps.chatbot.sql_tool.handlers import search_doctors
from apps.clinics.models import Clinic
from apps.doctors.models import Doctor, DoctorSpecialty
from apps.services.models import Service
from apps.specialties.models import Specialty


class EntityGuardUnitTests(SimpleTestCase):
    def test_strips_catalog_only_specialty(self):
        entities = ExtractedEntities(specialty="Heart stunts")
        cleaned = sanitize_entities("which doctors do you have?", entities)
        self.assertIsNone(cleaned.specialty)

    def test_keeps_message_grounded_specialty(self):
        entities = ExtractedEntities(specialty="cardiologist")
        cleaned = sanitize_entities("do you have a cardiologist?", entities)
        self.assertEqual(cleaned.specialty, "cardiologist")

    def test_keeps_doctor_name_in_message(self):
        entities = ExtractedEntities(doctor_name=["Hamza", "dr hamza"])
        cleaned = sanitize_entities("do you have Dr Hamza?", entities)
        self.assertIsNotNone(cleaned.doctor_name)

    def test_heart_surgery_phrase_grounded(self):
        self.assertTrue(
            entity_grounded_in_message("heart surgery", "which doctors offer heart surgery?")
        )

    def test_strips_booking_ctx_date_from_bare_book_request(self):
        """Regression: confirmed booking JSON in NLU Ctx leaked
        entities.date=2026-08-25 into 'I would like to book an appointment',
        which then ran availability SQL for that leftover day at midnight."""
        entities = ExtractedEntities(date="2026-08-25")
        cleaned = sanitize_entities("I would like to book an appointment", entities)
        self.assertIsNone(cleaned.date)

    def test_keeps_date_when_message_names_the_day(self):
        entities = ExtractedEntities(date="2026-08-25")
        cleaned = sanitize_entities("book me for Thursday afternoon", entities)
        self.assertEqual(cleaned.date, "2026-08-25")

    def test_keeps_iso_date_typed_in_the_message(self):
        entities = ExtractedEntities(date="2026-08-25")
        cleaned = sanitize_entities("book 2026-08-25", entities)
        self.assertEqual(cleaned.date, "2026-08-25")


class DoctorBrowseSignalTests(SimpleTestCase):
    def test_browse_queries(self):
        for msg in (
            "which doctors do you have?",
            "how many doctors do you have?",
            "who are your doctors?",
            "list doctors",
            "do you have any doctors?",
        ):
            self.assertTrue(is_doctor_browse_query(msg), msg)

    def test_filtered_queries_not_browse(self):
        self.assertFalse(is_doctor_browse_query("do you have a cardiologist?"))
        self.assertFalse(is_doctor_browse_query("which doctors offer heart surgery?"))
        self.assertFalse(is_doctor_browse_query("do you have Dr Hamza?"))


class DoctorBrowseIntegrationTests(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="entity-guard-clinic",
            name="Entity Guard Clinic",
            email="eg@clinic.com",
            phone="+12125550099",
            address={"street": "1 Main", "city": "Boston", "state": "MA", "zip": "02101"},
            timezone="America/New_York",
        )
        self.cardio = Specialty.objects.create(
            clinic=self.clinic, name="Cardiology", slug="cardiology"
        )
        self.consult = Service.objects.create(
            clinic=self.clinic, name="Consultation", duration_min=30, price_cents=10000
        )
        self.hamza = Doctor.objects.create(
            clinic=self.clinic,
            full_name="Dr. Hamza Ali",
            is_accepting_patients=True,
        )
        self.other = Doctor.objects.create(
            clinic=self.clinic,
            full_name="Dr. Choe Martin",
            is_accepting_patients=True,
        )
        DoctorSpecialty.objects.create(
            clinic=self.clinic, doctor=self.hamza, specialty=self.cardio
        )

    def _run_search(self, message: str, entities: ExtractedEntities) -> list[str]:
        nlu = NLUResult(
            intent=Intent.DOCTOR_SEARCH,
            confidence=0.9,
            entities=entities,
            resolved_ids=ResolvedIds(),
            needs_sql=True,
        )
        nlu = apply_routing_heuristics(
            message=message,
            nlu=nlu,
            service_catalog=[{"id": str(self.consult.id), "name": "Heart stunts"}],
        )
        nlu = replace(
            nlu,
            resolved_ids=resolve_entities(self.clinic, nlu.entities),
        )
        ctx = SQLContext(clinic=self.clinic, nlu=nlu, message=message)
        result = search_doctors(ctx)
        return [r["full_name"] for r in result.rows]

    def test_browse_returns_all_doctors_despite_catalog_bleed(self):
        names = self._run_search(
            "which doctors do you have?",
            ExtractedEntities(specialty="Heart stunts"),
        )
        self.assertEqual(len(names), 2)
        self.assertIn("Dr. Hamza Ali", names)
        self.assertIn("Dr. Choe Martin", names)

    def test_how_many_doctors_browse(self):
        names = self._run_search(
            "how many doctors do you have?",
            ExtractedEntities(specialty="Heart stunts"),
        )
        self.assertEqual(len(names), 2)

    def test_who_are_your_doctors_browse(self):
        names = self._run_search(
            "who are your doctors?",
            ExtractedEntities(specialty="Heart stunts"),
        )
        self.assertEqual(len(names), 2)

    def test_cardiologist_filter_preserved(self):
        names = self._run_search(
            "do you have a cardiologist?",
            ExtractedEntities(specialty="cardiologist"),
        )
        self.assertEqual(len(names), 1)
        self.assertIn("Dr. Hamza Ali", names)

    def test_hamza_name_filter_preserved(self):
        names = self._run_search(
            "do you have Dr Hamza?",
            ExtractedEntities(doctor_name=["Hamza"]),
        )
        self.assertEqual(len(names), 1)
        self.assertIn("Dr. Hamza Ali", names)

    def test_heuristics_strip_leaked_booking_date(self):
        nlu = NLUResult(
            intent=Intent.BOOK_APPOINTMENT,
            confidence=0.85,
            entities=ExtractedEntities(date="2026-08-25"),
            resolved_ids=ResolvedIds(),
            needs_sql=True,
        )
        nlu = apply_routing_heuristics(
            message="I would like to book an appointment",
            nlu=nlu,
        )
        self.assertIsNone(nlu.entities.date)

    def test_heuristic_service_survives_sanitization(self):
        nlu = NLUResult(
            intent=Intent.SERVICES_OFFERED,
            confidence=0.9,
            entities=ExtractedEntities(),
            resolved_ids=ResolvedIds(),
            needs_sql=True,
        )
        catalog = [{"id": str(self.consult.id), "name": "Consultation"}]
        nlu = apply_routing_heuristics(
            message="how much is a Consultation?",
            nlu=nlu,
            service_catalog=catalog,
        )
        self.assertEqual(nlu.entities.service, "Consultation")
