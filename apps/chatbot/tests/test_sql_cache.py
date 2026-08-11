"""Regression tests for SQL clinic-fact cache (collision + tenant isolation)."""

from __future__ import annotations

from datetime import time

from django.core.cache import cache
from django.test import TestCase

from apps.chatbot.nlu.schemas import ExtractedEntities, Intent, NLUResult, ResolvedIds
from apps.chatbot.sql_tool import SQLTool
from apps.chatbot.sql_tool.cache import cache_key, get_cached_result, set_cached_result
from apps.clinics.models import Clinic, ClinicBusinessHours
from apps.doctors.models import Doctor, DoctorService, DoctorSpecialty
from apps.insurance.models import InsurancePlan
from apps.services.models import Service
from apps.specialties.models import Specialty


def _nlu(
    intent: Intent,
    *,
    entities: ExtractedEntities | None = None,
    resolved: ResolvedIds | None = None,
) -> NLUResult:
    return NLUResult(
        intent=intent,
        confidence=0.9,
        entities=entities or ExtractedEntities(),
        resolved_ids=resolved or ResolvedIds(),
        needs_sql=True,
    )


class SQLCacheTestBase(TestCase):
    def setUp(self):
        cache.clear()
        self.clinic = Clinic.objects.create(
            slug="cache-test-clinic",
            name="Cache Test Clinic",
            email="cache@clinic.com",
            phone="+12125550001",
            address={
                "street": "2 Main St",
                "city": "Boston",
                "state": "MA",
                "zip": "02101",
            },
            timezone="America/New_York",
        )
        self.clinic_b = Clinic.objects.create(
            slug="cache-test-clinic-b",
            name="Cache Test Clinic B",
            email="cacheb@clinic.com",
            phone="+12125550002",
            address={"street": "3 Oak Ave", "city": "Boston", "state": "MA", "zip": "02102"},
            timezone="America/New_York",
        )

        self.cardio = Specialty.objects.create(
            clinic=self.clinic, name="Cardiology", slug="cardiology"
        )
        self.gp = Specialty.objects.create(
            clinic=self.clinic, name="General Practice", slug="general-practice"
        )
        self.consult = Service.objects.create(
            clinic=self.clinic, name="Consultation", duration_min=30, price_cents=20000
        )
        self.checkup = Service.objects.create(
            clinic=self.clinic, name="Annual Checkup", duration_min=45, price_cents=15000
        )

        self.doctor_hamza = Doctor.objects.create(
            clinic=self.clinic,
            full_name="Dr. Hamza Ali",
            title="MD",
            is_accepting_patients=True,
        )
        self.doctor_other = Doctor.objects.create(
            clinic=self.clinic,
            full_name="Dr. Choe Martin",
            title="MD",
            is_accepting_patients=True,
        )
        DoctorSpecialty.objects.create(
            clinic=self.clinic, doctor=self.doctor_hamza, specialty=self.cardio
        )
        DoctorSpecialty.objects.create(
            clinic=self.clinic, doctor=self.doctor_other, specialty=self.gp
        )
        DoctorService.objects.create(
            clinic=self.clinic, doctor=self.doctor_hamza, service=self.consult
        )
        DoctorService.objects.create(
            clinic=self.clinic, doctor=self.doctor_other, service=self.checkup
        )

        self.insurance_blue = InsurancePlan.objects.create(
            clinic=self.clinic,
            provider_name="Blue Cross",
            plan_name="PPO",
            is_accepted=True,
        )
        self.insurance_aetna = InsurancePlan.objects.create(
            clinic=self.clinic,
            provider_name="Aetna",
            plan_name="HMO",
            is_accepted=True,
        )

        for day in range(5):
            ClinicBusinessHours.objects.create(
                clinic=self.clinic,
                day_of_week=day,
                open_time=time(8, 0),
                close_time=time(17, 0),
                is_closed=False,
            )
            ClinicBusinessHours.objects.create(
                clinic=self.clinic_b,
                day_of_week=day,
                open_time=time(9, 0),
                close_time=time(18, 0),
                is_closed=False,
            )

        self.doctor_b = Doctor.objects.create(
            clinic=self.clinic_b,
            full_name="Dr. Clinic B Only",
            title="MD",
            is_accepting_patients=True,
        )

    def tearDown(self):
        cache.clear()


class DoctorCacheCollisionTests(SQLCacheTestBase):
    def test_general_list_then_name_search(self):
        general = SQLTool.run_tasks(self.clinic, _nlu(Intent.DOCTOR_SEARCH), ["doctors"])
        hamza = SQLTool.run_tasks(
            self.clinic,
            _nlu(
                Intent.DOCTOR_SEARCH,
                entities=ExtractedEntities(doctor_name=["dr hamza", "hamza"]),
            ),
            ["doctors"],
        )
        self.assertGreaterEqual(len(general[0].rows), 2)
        self.assertEqual(len(hamza[0].rows), 1)
        self.assertIn("Hamza", hamza[0].rows[0]["full_name"])

    def test_name_search_then_general_list(self):
        hamza = SQLTool.run_tasks(
            self.clinic,
            _nlu(Intent.DOCTOR_SEARCH, entities=ExtractedEntities(doctor_name="Hamza")),
            ["doctors"],
        )
        general = SQLTool.run_tasks(self.clinic, _nlu(Intent.DOCTOR_SEARCH), ["doctors"])
        self.assertEqual(len(hamza[0].rows), 1)
        self.assertIn("Hamza", hamza[0].rows[0]["full_name"])
        self.assertGreaterEqual(len(general[0].rows), 2)

    def test_specialty_search_then_name_search(self):
        cardio = SQLTool.run_tasks(
            self.clinic,
            _nlu(Intent.DOCTOR_SEARCH, entities=ExtractedEntities(specialty="Cardiology")),
            ["doctors"],
        )
        hamza = SQLTool.run_tasks(
            self.clinic,
            _nlu(Intent.DOCTOR_SEARCH, entities=ExtractedEntities(doctor_name="Hamza")),
            ["doctors"],
        )
        self.assertEqual(len(cardio[0].rows), 1)
        self.assertIn("Hamza", cardio[0].rows[0]["full_name"])
        self.assertEqual(len(hamza[0].rows), 1)
        self.assertIn("Hamza", hamza[0].rows[0]["full_name"])

    def test_service_search_then_name_search(self):
        consult = SQLTool.run_tasks(
            self.clinic,
            _nlu(Intent.DOCTOR_SEARCH, entities=ExtractedEntities(service="Consultation")),
            ["doctors"],
        )
        hamza = SQLTool.run_tasks(
            self.clinic,
            _nlu(Intent.DOCTOR_SEARCH, entities=ExtractedEntities(doctor_name="Hamza")),
            ["doctors"],
        )
        self.assertEqual(len(consult[0].rows), 1)
        self.assertIn("Hamza", consult[0].rows[0]["full_name"])
        self.assertEqual(len(hamza[0].rows), 1)
        self.assertIn("Hamza", hamza[0].rows[0]["full_name"])

    def test_stale_doctors_cache_entry_is_ignored(self):
        """Legacy clinic_fact:*:doctors entries must not be read after the fix."""
        stale = [
            {
                "handler": "search_doctors",
                "found": True,
                "rows": [{"full_name": "Dr. Choe Martin"}],
                "summary": "Found 1 doctor(s): Dr. Choe Martin.",
                "meta": {},
            }
        ]
        cache.set(cache_key(self.clinic.id, "doctors"), stale, timeout=600)
        result = SQLTool.run_tasks(
            self.clinic,
            _nlu(Intent.DOCTOR_SEARCH, entities=ExtractedEntities(doctor_name="Hamza")),
            ["doctors"],
        )
        self.assertEqual(len(result[0].rows), 1)
        self.assertIn("Hamza", result[0].rows[0]["full_name"])


class InsuranceCacheTests(SQLCacheTestBase):
    def test_different_provider_queries_not_colliding(self):
        blue = SQLTool.run_tasks(
            self.clinic,
            _nlu(
                Intent.INSURANCE_ACCEPTED,
                entities=ExtractedEntities(insurance_provider="Blue Cross"),
            ),
            ["insurance"],
        )
        aetna = SQLTool.run_tasks(
            self.clinic,
            _nlu(
                Intent.INSURANCE_ACCEPTED,
                entities=ExtractedEntities(insurance_provider="Aetna"),
            ),
            ["insurance"],
        )
        blue_names = {r["provider_name"] for r in blue[0].rows}
        aetna_names = {r["provider_name"] for r in aetna[0].rows}
        self.assertIn("Blue Cross", blue_names)
        self.assertIn("Aetna", aetna_names)
        self.assertNotIn("Aetna", blue_names)


class StaticFactCacheTests(SQLCacheTestBase):
    def test_hours_cache_hit(self):
        nlu = _nlu(Intent.CLINIC_HOURS)
        first = SQLTool.run_tasks(self.clinic, nlu, ["hours"])
        self.assertIsNotNone(get_cached_result(self.clinic.id, "hours"))
        second = SQLTool.run_tasks(self.clinic, nlu, ["hours"])
        self.assertEqual(first[0].summary, second[0].summary)
        self.assertTrue(first[0].found)

    def test_location_cache_hit(self):
        nlu = _nlu(Intent.CLINIC_LOCATION)
        first = SQLTool.run_tasks(self.clinic, nlu, ["location"])
        self.assertIsNotNone(get_cached_result(self.clinic.id, "location"))
        second = SQLTool.run_tasks(self.clinic, nlu, ["location"])
        self.assertEqual(first[0].summary, second[0].summary)
        self.assertTrue(first[0].found)

    def test_doctors_not_cached(self):
        SQLTool.run_tasks(self.clinic, _nlu(Intent.DOCTOR_SEARCH), ["doctors"])
        self.assertIsNone(get_cached_result(self.clinic.id, "doctors"))
        self.assertIsNone(cache.get(cache_key(self.clinic.id, "doctors")))


class TenantIsolationTests(SQLCacheTestBase):
    def test_clinic_a_cache_does_not_affect_clinic_b(self):
        SQLTool.run_tasks(self.clinic, _nlu(Intent.DOCTOR_SEARCH), ["doctors"])
        result_b = SQLTool.run_tasks(
            self.clinic_b,
            _nlu(Intent.DOCTOR_SEARCH, entities=ExtractedEntities(doctor_name="Clinic B")),
            ["doctors"],
        )
        self.assertEqual(len(result_b[0].rows), 1)
        self.assertEqual(result_b[0].rows[0]["full_name"], "Dr. Clinic B Only")

    def test_set_cached_result_rejects_parameterized_tasks(self):
        rows = [{"handler": "search_doctors", "found": True, "rows": [], "summary": "", "meta": {}}]
        set_cached_result(self.clinic.id, "doctors", rows)
        self.assertIsNone(get_cached_result(self.clinic.id, "doctors"))
