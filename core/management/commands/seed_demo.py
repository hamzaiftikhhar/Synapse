"""
Seed a single demo clinic with realistic dummy data for console / Admin testing.

Usage:
    python manage.py seed_demo
    python manage.py seed_demo --reset   # delete previous demo clinic first
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.appointments.models import Appointment, AppointmentSource, AppointmentStatus
from apps.chatbot.models import ChatMessage, ChatSession, MessageRole, MessageType
from apps.clinics.models import Clinic, ClinicBusinessHours, ClinicStatus
from apps.doctors.models import (
    Doctor,
    DoctorInsurance,
    DoctorLeave,
    DoctorSchedule,
    DoctorService,
    DoctorSpecialty,
)
from apps.insurance.models import InsurancePlan
from apps.knowledge.models import Document, DocumentStatus, KnowledgeChunk
from apps.patients.models import Patient
from apps.services.models import Service
from apps.specialties.models import Specialty
from apps.widget.models import WidgetSettings


DEMO_SLUG = "acme-cardiology"


class Command(BaseCommand):
    help = "Load demo clinic data so you can exercise the database via Admin/shell."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help=f"Delete clinic '{DEMO_SLUG}' and recreate it.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if options["reset"]:
            deleted, _ = Clinic.objects.filter(slug=DEMO_SLUG).delete()
            self.stdout.write(f"Removed previous demo data ({deleted} objects).")

        if Clinic.objects.filter(slug=DEMO_SLUG).exists():
            self.stdout.write(
                self.style.WARNING(
                    f"Demo clinic '{DEMO_SLUG}' already exists. "
                    "Re-run with --reset to rebuild."
                )
            )
            return

        clinic = Clinic.objects.create(
            slug=DEMO_SLUG,
            name="Acme Cardiology",
            email="admin@acme-cardiology.example",
            phone="+12125550100",
            address={
                "street": "100 Heartbeat Ave",
                "city": "New York",
                "state": "NY",
                "zip": "10001",
                "country": "US",
            },
            timezone="America/New_York",
            status=ClinicStatus.ACTIVE,
        )

        WidgetSettings.objects.create(
            clinic=clinic,
            configuration={
                "widget": {
                    "primary_color": "#2563EB",
                    "position": "bottom-right",
                    "greeting": "Hi! How can Acme Cardiology help you today?",
                },
                "ai": {"model": "gpt-4o-mini", "temperature": 0.3},
                "booking": {"require_auth": True, "slot_duration_min": 30},
                "feature_flags": {
                    "booking": True,
                    "insurance": True,
                    "rag": True,
                    "doctor_search": True,
                },
            },
        )

        for day in range(7):
            ClinicBusinessHours.objects.create(
                clinic=clinic,
                day_of_week=day,
                open_time=None if day == 6 else time(8, 0),
                close_time=None if day == 6 else time(18, 0),
                is_closed=(day == 6),  # Sunday closed
            )

        cardio = Specialty.objects.create(
            clinic=clinic,
            name="Cardiology",
            slug="cardiology",
            description="Heart and vascular care",
        )
        gp = Specialty.objects.create(
            clinic=clinic,
            name="General Practice",
            slug="general-practice",
        )

        ecg = Service.objects.create(
            clinic=clinic,
            name="ECG",
            description="Electrocardiogram",
            duration_min=30,
            price_cents=15000,
        )
        mri = Service.objects.create(
            clinic=clinic,
            name="Cardiac MRI",
            description="MRI of the heart",
            duration_min=60,
            price_cents=90000,
        )
        consult = Service.objects.create(
            clinic=clinic,
            name="Cardiology Consultation",
            duration_min=30,
            price_cents=25000,
        )

        blue = InsurancePlan.objects.create(
            clinic=clinic,
            provider_name="Blue Cross Blue Shield",
            plan_name="PPO Gold",
            plan_type="PPO",
            is_accepted=True,
        )
        aetna = InsurancePlan.objects.create(
            clinic=clinic,
            provider_name="Aetna",
            plan_name="HMO Plus",
            plan_type="HMO",
            is_accepted=True,
        )

        rajat = Doctor.objects.create(
            clinic=clinic,
            full_name="Dr. Rajat Sharma",
            title="MD",
            bio="Interventional cardiologist with 12 years of experience.",
            languages=["en", "hi"],
            is_accepting_patients=True,
        )
        ali = Doctor.objects.create(
            clinic=clinic,
            full_name="Dr. Ali Hamza",
            title="MD",
            bio="General cardiology and preventive care.",
            languages=["en", "ur"],
            is_accepting_patients=True,
        )

        for doctor, specialty in ((rajat, cardio), (ali, cardio), (ali, gp)):
            DoctorSpecialty.objects.create(
                doctor=doctor, specialty=specialty, clinic=clinic
            )

        # Rajat: ECG + MRI + consult; Ali: ECG + consult only
        for doctor, service in (
            (rajat, ecg),
            (rajat, mri),
            (rajat, consult),
            (ali, ecg),
            (ali, consult),
        ):
            DoctorService.objects.create(doctor=doctor, service=service, clinic=clinic)

        for doctor, plan in ((rajat, blue), (rajat, aetna), (ali, blue)):
            DoctorInsurance.objects.create(
                doctor=doctor, insurance_plan=plan, clinic=clinic
            )

        for doctor in (rajat, ali):
            for day in range(5):  # Mon–Fri
                DoctorSchedule.objects.create(
                    clinic=clinic,
                    doctor=doctor,
                    day_of_week=day,
                    start_time=time(9, 0),
                    end_time=time(17, 0),
                    slot_duration_min=30,
                )

        DoctorLeave.objects.create(
            clinic=clinic,
            doctor=rajat,
            start_at=timezone.now() + timedelta(days=14),
            end_at=timezone.now() + timedelta(days=16),
            reason="Conference",
        )

        patient = Patient.objects.create(
            clinic=clinic,
            phone="+12125550999",
            email="jane.doe@example.com",
            first_name="Jane",
            last_name="Doe",
            date_of_birth=date(1990, 5, 15),
            preferred_language="en",
            is_verified=True,
        )

        tz = ZoneInfo(clinic.timezone)
        start = datetime.now(tz).replace(hour=10, minute=0, second=0, microsecond=0)
        if start.weekday() >= 5:
            start += timedelta(days=(7 - start.weekday()))
        start += timedelta(days=1)
        end = start + timedelta(minutes=30)

        Appointment.objects.create(
            clinic=clinic,
            doctor=rajat,
            patient=patient,
            service=consult,
            insurance_plan=blue,
            start_time=start,
            end_time=end,
            status=AppointmentStatus.CONFIRMED,
            confirmation_code="ACM001",
            notes="Chest discomfort follow-up",
            source=AppointmentSource.CHATBOT,
        )

        doc = Document.objects.create(
            clinic=clinic,
            title="Patient FAQ",
            file_name="faq.pdf",
            file_type="pdf",
            storage_path="clinics/acme-cardiology/faq.pdf",
            file_size_bytes=12000,
            status=DocumentStatus.INDEXED,
            chunk_count=2,
        )
        KnowledgeChunk.objects.create(
            clinic=clinic,
            document=doc,
            chunk_number=0,
            page_number=1,
            content="Acme Cardiology is open Monday–Saturday, 8am–6pm. Sunday closed.",
            token_count=20,
        )
        KnowledgeChunk.objects.create(
            clinic=clinic,
            document=doc,
            chunk_number=1,
            page_number=1,
            content="We accept Blue Cross PPO Gold and Aetna HMO Plus.",
            token_count=16,
        )

        session = ChatSession.objects.create(
            clinic=clinic,
            patient=patient,
            session_token="demo-session-token-001",
            locale="en",
            conversation_context={"current_intent": "BOOK_APPOINTMENT"},
            is_authenticated=True,
        )
        ChatMessage.objects.create(
            clinic=clinic,
            session=session,
            role=MessageRole.USER,
            message_type=MessageType.TEXT,
            content="I need a cardiologist appointment tomorrow.",
            sequence_number=1,
            metadata={"intent": "BOOK_APPOINTMENT"},
        )
        ChatMessage.objects.create(
            clinic=clinic,
            session=session,
            role=MessageRole.ASSISTANT,
            message_type=MessageType.TEXT,
            content="I can help with that. Dr. Rajat Sharma has openings.",
            sequence_number=2,
            metadata={"intent": "BOOK_APPOINTMENT", "latency": 210},
        )

        self.stdout.write(self.style.SUCCESS("Demo data loaded."))
        self.stdout.write(f"  Clinic slug : {clinic.slug}")
        self.stdout.write(f"  Clinic id   : {clinic.id}")
        self.stdout.write(f"  UUID version: {clinic.id.version}  (expect 7)")
        self.stdout.write("  Open Admin  : http://127.0.0.1:8000/admin/")
        self.stdout.write(
            "  Or shell    : python manage.py shell\n"
            "                from apps.clinics.models import Clinic\n"
            "                Clinic.objects.get(slug='acme-cardiology')"
        )
