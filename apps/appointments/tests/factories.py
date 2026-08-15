"""Shared fixtures for staff-JWT appointment tests."""

from __future__ import annotations

import itertools
from datetime import datetime, time, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from apps.api.test_helpers import make_clinic_admin
from apps.appointments.models import Appointment, AppointmentStatus
from apps.chatbot.models import ChatSession, ChatSessionStatus
from apps.doctors.models import Doctor, DoctorSchedule, DoctorService
from apps.insurance.models import InsurancePlan
from apps.patients.models import Patient
from apps.services.models import Service

URL = "/api/v1/appointments"
LA = ZoneInfo("America/Los_Angeles")
UTC = ZoneInfo("UTC")

# Thursday 20 Aug 2026, 15:00 America/Los_Angeles (3:00 PM PDT = 22:00 UTC)
SLOT_START = datetime(2026, 8, 20, 15, 0, tzinfo=LA)
SLOT_END = SLOT_START + timedelta(minutes=30)

_seq = itertools.count(1)


def unique_code() -> str:
    return f"T{next(_seq):05d}"


def unique_phone() -> str:
    n = next(_seq)
    return f"+1555{n:07d}"


class AppointmentWorld:
    """One clinic with two doctors, two patients, a service, and Mon–Fri hours."""

    def __init__(self, *, slug: str, email: str, timezone: str = "America/Los_Angeles"):
        self.user, self.clinic, self.headers = make_clinic_admin(
            email=email, clinic_slug=slug
        )
        self.clinic.timezone = timezone
        self.clinic.save(update_fields=["timezone"])

        self.doctor_a = Doctor.objects.create(
            clinic=self.clinic, full_name="Dr. Alpha", is_active=True, is_accepting_patients=True
        )
        self.doctor_b = Doctor.objects.create(
            clinic=self.clinic, full_name="Dr. Bravo", is_active=True, is_accepting_patients=True
        )
        self.patient_a = Patient.objects.create(
            clinic=self.clinic, first_name="Pat", last_name="Alpha", phone=unique_phone()
        )
        self.patient_b = Patient.objects.create(
            clinic=self.clinic, first_name="Pat", last_name="Bravo", phone=unique_phone()
        )
        self.service = Service.objects.create(
            clinic=self.clinic, name="Consult", duration_min=30
        )
        self.other_service = Service.objects.create(
            clinic=self.clinic, name="Follow-up", duration_min=45
        )
        DoctorService.objects.create(
            clinic=self.clinic, doctor=self.doctor_a, service=self.service
        )
        DoctorService.objects.create(
            clinic=self.clinic, doctor=self.doctor_b, service=self.service
        )
        self.insurance = InsurancePlan.objects.create(
            clinic=self.clinic, provider_name="Aetna", plan_name="PPO"
        )
        for doctor in (self.doctor_a, self.doctor_b):
            for day in range(5):
                DoctorSchedule.objects.create(
                    clinic=self.clinic,
                    doctor=doctor,
                    day_of_week=day,
                    start_time=time(9, 0),
                    end_time=time(17, 0),
                    slot_duration_min=30,
                )

    def payload(self, **overrides) -> dict:
        body = {
            "doctor_id": str(self.doctor_a.id),
            "patient_id": str(self.patient_a.id),
            "service_id": str(self.service.id),
            "start_time": SLOT_START.isoformat(),
            "end_time": SLOT_END.isoformat(),
            "status": "confirmed",
            "source": "admin",
            "notes": "",
        }
        body.update(overrides)
        return body

    def create_row(self, **overrides) -> Appointment:
        defaults = {
            "clinic": self.clinic,
            "doctor": self.doctor_a,
            "patient": self.patient_a,
            "service": self.service,
            "start_time": SLOT_START,
            "end_time": SLOT_END,
            "status": AppointmentStatus.CONFIRMED,
            "confirmation_code": unique_code(),
            "source": "admin",
        }
        defaults.update(overrides)
        return Appointment.objects.create(**defaults)

    def otp_session(self, patient: Patient, token: str) -> ChatSession:
        return ChatSession.objects.create(
            clinic=self.clinic,
            patient=patient,
            session_token=token,
            status=ChatSessionStatus.ACTIVE,
            is_authenticated=True,
        )


def random_uuid() -> str:
    return str(uuid4())
