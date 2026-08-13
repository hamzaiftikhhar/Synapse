"""Booking eligibility is doctors ↔ services, not doctors ↔ specialties."""

from __future__ import annotations

from django.test import TestCase

from apps.chatbot.booking.modes import PATH_TO_MODE, first_step
from apps.chatbot.booking.serializers import _doctor_options, _service_options
from apps.chatbot.booking.service import BookingService
from apps.chatbot.booking.state import BookingSession, BookingStep
from apps.chatbot.models import ChatSession, ChatSessionStatus
from apps.clinics.models import Clinic
from apps.doctors.models import Doctor, DoctorService, DoctorSpecialty
from apps.services.models import Service
from apps.specialties.models import Specialty


class ServiceFirstModeTests(TestCase):
    def test_help_choose_maps_to_service_then_doctor(self):
        self.assertEqual(PATH_TO_MODE["help_choose"], "service_first")
        self.assertEqual(first_step("service_first"), BookingStep.SERVICE)
        self.assertEqual(first_step("specialty_first"), BookingStep.SERVICE)

    def test_legacy_specialty_session_coerces_to_service(self):
        session = BookingSession.from_dict(
            {
                "booking_id": "b1",
                "clinic_id": "c1",
                "mode": "specialty_first",
                "step": "specialty",
            }
        )
        self.assertEqual(session.mode, "service_first")
        self.assertEqual(session.step, BookingStep.SERVICE.value)


class ServiceFirstEligibilityTests(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="svc-first",
            name="Service First Clinic",
            email="svc-first@clinic.com",
            phone="+12125550101",
            timezone="America/New_York",
        )
        self.derm = Specialty.objects.create(
            clinic=self.clinic, name="Dermatology", slug="dermatology"
        )
        self.botox = Service.objects.create(
            clinic=self.clinic, name="Botox", duration_min=30
        )
        self.acne = Service.objects.create(
            clinic=self.clinic, name="Acne Consultation", duration_min=20
        )
        self.followup = Service.objects.create(
            clinic=self.clinic, name="Follow-up Visit", duration_min=15
        )
        self.doctor_a = Doctor.objects.create(
            clinic=self.clinic, full_name="Doctor A", is_accepting_patients=True
        )
        self.doctor_b = Doctor.objects.create(
            clinic=self.clinic, full_name="Doctor B", is_accepting_patients=True
        )
        DoctorSpecialty.objects.create(
            clinic=self.clinic, doctor=self.doctor_a, specialty=self.derm
        )
        DoctorSpecialty.objects.create(
            clinic=self.clinic, doctor=self.doctor_b, specialty=self.derm
        )
        DoctorService.objects.create(
            clinic=self.clinic, doctor=self.doctor_a, service=self.botox
        )
        DoctorService.objects.create(
            clinic=self.clinic, doctor=self.doctor_a, service=self.acne
        )
        DoctorService.objects.create(
            clinic=self.clinic, doctor=self.doctor_b, service=self.followup
        )
        self.chat_session = ChatSession.objects.create(
            clinic=self.clinic,
            session_token="tok-svc-first",
            status=ChatSessionStatus.ACTIVE,
        )

    def test_service_step_lists_bookable_services(self):
        session = BookingSession.create(
            clinic_id=str(self.clinic.id), mode="service_first"
        )
        session.step = BookingStep.SERVICE.value
        names = {row["name"] for row in _service_options(self.clinic, session)["all"]}
        self.assertEqual(names, {"Botox", "Acne Consultation", "Follow-up Visit"})

    def test_specialty_does_not_make_a_doctor_eligible_for_a_service(self):
        """Doctor B is a dermatologist but does not offer Botox."""
        session = BookingSession.create(
            clinic_id=str(self.clinic.id), mode="service_first"
        )
        session.step = BookingStep.DOCTOR.value
        session.service_id = str(self.botox.id)
        session.service_name = "Botox"
        session.specialty_id = str(self.derm.id)
        session.specialty_name = "Dermatology"

        doctors = _doctor_options(self.clinic, session)["doctors"]
        names = {d["name"] for d in doctors}
        self.assertEqual(names, {"Doctor A"})
        self.assertNotIn("Doctor B", names)

    def test_select_service_filters_doctors_by_doctor_service(self):
        started = BookingService.start(
            clinic=self.clinic, chat_session=self.chat_session
        )
        pathed = BookingService.apply_step(
            clinic=self.clinic,
            chat_session=self.chat_session,
            booking_id=started["booking_id"],
            action="select_path",
            value={"path": "help_choose"},
        )
        self.assertEqual(pathed["step"], BookingStep.SERVICE.value)
        self.assertEqual(pathed["mode"], "service_first")

        chosen = BookingService.apply_step(
            clinic=self.clinic,
            chat_session=self.chat_session,
            booking_id=started["booking_id"],
            action="select_service",
            value={"id": str(self.followup.id), "name": "Follow-up Visit"},
        )
        self.assertEqual(chosen["step"], BookingStep.DOCTOR.value)
        self.assertEqual(chosen["service_chip"]["name"], "Follow-up Visit")
        names = {d["name"] for d in chosen["options"]["doctors"]}
        self.assertEqual(names, {"Doctor B"})

    def test_start_with_service_skips_to_doctors_who_offer_it(self):
        result = BookingService.start(
            clinic=self.clinic,
            chat_session=self.chat_session,
            service_id=str(self.botox.id),
            service_name="Botox",
        )
        self.assertEqual(result["step"], BookingStep.DOCTOR.value)
        self.assertEqual(result["mode"], "service_first")
        names = {d["name"] for d in result["options"]["doctors"]}
        self.assertEqual(names, {"Doctor A"})

    def test_start_with_specialty_only_lands_on_filtered_services(self):
        result = BookingService.start(
            clinic=self.clinic,
            chat_session=self.chat_session,
            specialty_id=str(self.derm.id),
            specialty_name="Dermatology",
        )
        self.assertEqual(result["step"], BookingStep.SERVICE.value)
        names = {row["name"] for row in result["options"]["all"]}
        self.assertEqual(names, {"Botox", "Acne Consultation", "Follow-up Visit"})
