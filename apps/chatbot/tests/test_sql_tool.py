"""Tests for SQL Tool handlers."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.test import TestCase
from django.utils import timezone

from apps.appointments.models import Appointment, AppointmentSource, AppointmentStatus
from apps.chatbot.nlu.schemas import ExtractedEntities, Intent, NLUResult, ResolvedIds
from apps.chatbot.sql_tool import SQLContext, SQLTool, format_sql_results
from apps.chatbot.sql_tool.handlers import (
    clinic_hours,
    insurance_accepted,
    list_specialties,
    patient_appointments,
    search_doctors,
    services_offered,
)
from apps.clinics.models import Clinic, ClinicBusinessHours
from apps.doctors.models import Doctor, DoctorInsurance, DoctorSchedule, DoctorService, DoctorSpecialty
from apps.insurance.models import InsurancePlan
from apps.patients.models import Patient
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


class SQLToolTestBase(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="sql-tool-clinic",
            name="SQL Tool Clinic",
            email="sql@clinic.com",
            phone="+12125550000",
            address={
                "street": "1 Main St",
                "city": "Boston",
                "state": "MA",
                "zip": "02101",
            },
            timezone="America/New_York",
        )
        self.cardio = Specialty.objects.create(
            clinic=self.clinic,
            name="Cardiology",
            slug="cardiology",
        )
        Specialty.objects.create(
            clinic=self.clinic,
            name="General Practice",
            slug="general-practice",
        )
        self.consult = Service.objects.create(
            clinic=self.clinic,
            name="Consultation",
            duration_min=30,
            price_cents=20000,
        )
        self.blue = InsurancePlan.objects.create(
            clinic=self.clinic,
            provider_name="Blue Cross",
            plan_name="PPO",
            is_accepted=True,
        )
        self.doctor = Doctor.objects.create(
            clinic=self.clinic,
            full_name="Dr. Hamza Ali",
            title="MD",
            is_accepting_patients=True,
        )
        DoctorSpecialty.objects.create(
            clinic=self.clinic,
            doctor=self.doctor,
            specialty=self.cardio,
        )
        DoctorService.objects.create(
            clinic=self.clinic,
            doctor=self.doctor,
            service=self.consult,
        )
        DoctorInsurance.objects.create(
            clinic=self.clinic,
            doctor=self.doctor,
            insurance_plan=self.blue,
        )

        for day in range(5):
            ClinicBusinessHours.objects.create(
                clinic=self.clinic,
                day_of_week=day,
                open_time=time(8, 0),
                close_time=time(17, 0),
                is_closed=False,
            )
            DoctorSchedule.objects.create(
                clinic=self.clinic,
                doctor=self.doctor,
                day_of_week=day,
                start_time=time(9, 0),
                end_time=time(12, 0),
                slot_duration_min=30,
            )

        self.patient = Patient.objects.create(
            clinic=self.clinic,
            phone="+12125551111",
            first_name="Test",
            last_name="Patient",
        )

        tz = ZoneInfo("America/New_York")
        start = timezone.make_aware(
            datetime.combine(
                timezone.now().astimezone(tz).date() + timedelta(days=2),
                time(10, 0),
            ),
            tz,
        )
        Appointment.objects.create(
            clinic=self.clinic,
            doctor=self.doctor,
            patient=self.patient,
            service=self.consult,
            start_time=start,
            end_time=start + timedelta(minutes=30),
            status=AppointmentStatus.CONFIRMED,
            confirmation_code="SQL001",
            source=AppointmentSource.CHATBOT,
        )


class SearchDoctorsTests(SQLToolTestBase):
    def test_search_by_name(self):
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=_nlu(Intent.DOCTOR_SEARCH, entities=ExtractedEntities(doctor_name="Hamza")),
        )
        result = search_doctors(ctx)
        self.assertTrue(result.found)
        self.assertEqual(result.rows[0]["full_name"], "Dr. Hamza Ali")

    def test_search_by_specialty(self):
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=_nlu(Intent.DOCTOR_SEARCH, entities=ExtractedEntities(specialty="Cardiology")),
        )
        result = search_doctors(ctx)
        self.assertTrue(result.found)
        self.assertIn("Cardiology", result.rows[0]["specialties"])


class ListSpecialtiesTests(SQLToolTestBase):
    def test_lists_all_specialties(self):
        ctx = SQLContext(clinic=self.clinic, nlu=_nlu(Intent.DOCTOR_SEARCH))
        result = list_specialties(ctx)
        self.assertTrue(result.found)
        names = {row["name"] for row in result.rows}
        self.assertIn("Cardiology", names)
        self.assertIn("General Practice", names)


class InsuranceTests(SQLToolTestBase):
    def test_insurance_by_provider(self):
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=_nlu(
                Intent.INSURANCE_ACCEPTED,
                entities=ExtractedEntities(insurance_provider="Blue Cross"),
            ),
        )
        result = insurance_accepted(ctx)
        self.assertTrue(result.found)
        self.assertEqual(result.rows[0]["provider_name"], "Blue Cross")


class InsurancePlanTypeTests(SQLToolTestBase):
    """Phase 41: "Aetna HMO" and "Aetna PPO" used to return the identical
    row — provider matching ignored plan_type entirely, so whichever plan
    existed for that provider silently "answered" a question about a
    different type (reproduced live: both returned the HMO Plus row)."""

    def setUp(self):
        super().setUp()
        self.aetna_hmo = InsurancePlan.objects.create(
            clinic=self.clinic,
            provider_name="Aetna",
            plan_name="HMO Plus",
            plan_type="HMO",
            is_accepted=True,
        )
        self.aetna_ppo = InsurancePlan.objects.create(
            clinic=self.clinic,
            provider_name="Aetna",
            plan_name="PPO",
            plan_type="PPO",
            is_accepted=True,
        )

    def test_hmo_question_returns_hmo_plan(self):
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=_nlu(
                Intent.INSURANCE_ACCEPTED,
                entities=ExtractedEntities(insurance_provider=["Aetna HMO", "Aetna"]),
            ),
            message="Do you accept Aetna HMO?",
        )
        result = insurance_accepted(ctx)
        self.assertEqual(len(result.rows), 1)
        self.assertEqual(result.rows[0]["plan_type"], "HMO")
        self.assertIn("HMO Plus", result.summary)

    def test_ppo_question_returns_ppo_plan_not_hmo(self):
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=_nlu(
                Intent.INSURANCE_ACCEPTED,
                entities=ExtractedEntities(insurance_provider=["Aetna PPO", "Aetna"]),
            ),
            message="Do you accept Aetna PPO?",
        )
        result = insurance_accepted(ctx)
        self.assertEqual(len(result.rows), 1)
        self.assertEqual(result.rows[0]["plan_type"], "PPO")
        self.assertIn("PPO", result.summary)
        self.assertNotIn("HMO Plus", result.summary)

    def test_requested_type_not_on_file_is_honest_not_silent(self):
        """A provider with only an HMO plan, asked about PPO, must say so
        — never present the HMO plan as if it answered a PPO question."""
        self.aetna_ppo.delete()
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=_nlu(
                Intent.INSURANCE_ACCEPTED,
                entities=ExtractedEntities(insurance_provider=["Aetna PPO", "Aetna"]),
            ),
            message="Do you accept Aetna PPO?",
        )
        result = insurance_accepted(ctx)
        self.assertIn("don't see a Aetna PPO plan", result.summary)
        self.assertIn("HMO Plus", result.summary)


class ClinicHoursTests(SQLToolTestBase):
    def test_clinic_hours(self):
        ctx = SQLContext(clinic=self.clinic, nlu=_nlu(Intent.CLINIC_HOURS))
        result = clinic_hours(ctx)
        self.assertTrue(result.found)
        self.assertEqual(len(result.rows), 5)


class ServicesTests(SQLToolTestBase):
    def test_services_offered(self):
        ctx = SQLContext(clinic=self.clinic, nlu=_nlu(Intent.SERVICES_OFFERED))
        result = services_offered(ctx)
        self.assertTrue(result.found)
        self.assertEqual(result.rows[0]["name"], "Consultation")


class PatientAppointmentsTests(SQLToolTestBase):
    def test_requires_patient(self):
        ctx = SQLContext(clinic=self.clinic, nlu=_nlu(Intent.CANCEL_APPOINTMENT))
        result = patient_appointments(ctx)
        self.assertFalse(result.found)
        self.assertTrue(result.meta.get("requires_auth"))

    def test_returns_upcoming(self):
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=_nlu(Intent.CANCEL_APPOINTMENT),
            patient=self.patient,
        )
        result = patient_appointments(ctx)
        self.assertTrue(result.found)
        self.assertEqual(result.rows[0]["confirmation_code"], "SQL001")
        when = result.rows[0]["when"]
        self.assertRegex(when, r"\d{1,2}:\d{2} [AP]M")
        # No raw ISO datetime separator leaked through (e.g. "...T10:00...").
        # A bare "T" substring check is flaky here: the weekday abbreviation
        # itself is "Tue" or "Thu" roughly 2 days out of 7.
        self.assertNotRegex(when, r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")
        text = format_sql_results([result.to_dict()])
        self.assertIn(when, text)
        self.assertNotIn("T10:00", text)


class SQLToolDispatcherTests(SQLToolTestBase):
    def test_dispatch_insurance_intent(self):
        nlu = _nlu(
            Intent.INSURANCE_ACCEPTED,
            entities=ExtractedEntities(insurance_provider="Blue Cross"),
        )
        results = SQLTool.run(self.clinic, nlu)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].handler, "insurance_accepted")
        self.assertTrue(results[0].found)

    def test_dispatch_doctor_search_runs_search_doctors(self):
        nlu = _nlu(Intent.DOCTOR_SEARCH)
        results = SQLTool.run(self.clinic, nlu)
        handlers = {r.handler for r in results}
        self.assertIn("search_doctors", handlers)
        self.assertNotIn("list_specialties", handlers)


class SQLFormatterTests(SQLToolTestBase):
    def test_format_clinic_hours(self):
        ctx = SQLContext(clinic=self.clinic, nlu=_nlu(Intent.CLINIC_HOURS))
        result = clinic_hours(ctx)
        text = format_sql_results([result.to_dict()])
        self.assertIn("we're open", text.lower())
        self.assertIn("Monday", text)
