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

from apps.accounts.models import ClinicStaff, User, UserRole
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

    def _ensure_staff(self, clinic: Clinic) -> None:
        staff_user, created = User.objects.get_or_create(
            email="admin@acme-cardiology.example",
            defaults={
                "username": "clinic_admin",
                "first_name": "Clinic",
                "last_name": "Admin",
                "role": UserRole.CLINIC_ADMIN,
                "is_clinic_owner": True,
                "is_staff": True,
            },
        )
        if created:
            staff_user.set_password("admin123")
            staff_user.save()
        else:
            # Keep demo credentials predictable across re-seeds
            updated = False
            if staff_user.role != UserRole.CLINIC_ADMIN:
                staff_user.role = UserRole.CLINIC_ADMIN
                updated = True
            if not staff_user.is_clinic_owner:
                staff_user.is_clinic_owner = True
                updated = True
            if updated:
                staff_user.save(update_fields=["role", "is_clinic_owner"])
        ClinicStaff.objects.get_or_create(
            user=staff_user,
            clinic=clinic,
            defaults={"is_active": True},
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if options["reset"]:
            clinic = Clinic.objects.filter(slug=DEMO_SLUG).first()
            if clinic is not None:
                # Appointments PROTECT doctor/patient — clear them first
                Appointment.objects.filter(clinic=clinic).delete()
                deleted, _ = Clinic.objects.filter(pk=clinic.pk).delete()
                self.stdout.write(f"Removed previous demo data ({deleted} objects).")
            else:
                self.stdout.write("No previous demo clinic to remove.")

        if Clinic.objects.filter(slug=DEMO_SLUG).exists():
            clinic = Clinic.objects.get(slug=DEMO_SLUG)
            self._ensure_staff(clinic)
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
            },# {"street": "Bahria", "city": "Lahore", "state": "Punjab", "zip": "55180", "country": "PK"}
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
        sofia = Doctor.objects.create(
            clinic=clinic,
            full_name="Dr. Sofia Mendes",
            title="MD, FACC",
            bio="Electrophysiology and arrhythmia management.",
            languages=["en", "pt", "es"],
            is_accepting_patients=True,
        )

        for doctor, specialty in (
            (rajat, cardio),
            (ali, cardio),
            (ali, gp),
            (sofia, cardio),
        ):
            DoctorSpecialty.objects.create(
                doctor=doctor, specialty=specialty, clinic=clinic
            )

        # Rajat: ECG + MRI + consult; Ali: ECG + consult; Sofia: MRI + consult
        for doctor, service in (
            (rajat, ecg),
            (rajat, mri),
            (rajat, consult),
            (ali, ecg),
            (ali, consult),
            (sofia, mri),
            (sofia, consult),
        ):
            DoctorService.objects.create(doctor=doctor, service=service, clinic=clinic)

        for doctor, plan in (
            (rajat, blue),
            (rajat, aetna),
            (ali, blue),
            (sofia, blue),
            (sofia, aetna),
        ):
            DoctorInsurance.objects.create(
                doctor=doctor, insurance_plan=plan, clinic=clinic
            )

        for doctor in (rajat, ali, sofia):
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

        jane = Patient.objects.create(
            clinic=clinic,
            phone="+12125550999",
            email="jane.doe@example.com",
            first_name="Jane",
            last_name="Doe",
            date_of_birth=date(1990, 5, 15),
            preferred_language="en",
            is_verified=True,
        )
        marcus = Patient.objects.create(
            clinic=clinic,
            phone="+12125551001",
            email="marcus.chen@example.com",
            first_name="Marcus",
            last_name="Chen",
            date_of_birth=date(1985, 11, 3),
            preferred_language="en",
            is_verified=True,
        )
        aisha = Patient.objects.create(
            clinic=clinic,
            phone="+12125551002",
            email="aisha.khan@example.com",
            first_name="Aisha",
            last_name="Khan",
            date_of_birth=date(1994, 2, 22),
            preferred_language="en",
            is_verified=False,
        )
        luis = Patient.objects.create(
            clinic=clinic,
            phone="+12125551003",
            email="luis.ortiz@example.com",
            first_name="Luis",
            last_name="Ortiz",
            date_of_birth=date(1978, 8, 9),
            preferred_language="es",
            is_verified=True,
        )

        # Next weekday at 10:00 clinic-local, then stagger slots so doctors never overlap
        tz = ZoneInfo(clinic.timezone)
        base = datetime.now(tz).replace(hour=10, minute=0, second=0, microsecond=0)
        if base.weekday() >= 5:
            base += timedelta(days=(7 - base.weekday()))
        base += timedelta(days=1)

        def slot(day_offset: int, hour: int, minute: int = 0, duration_min: int = 30):
            start = (base + timedelta(days=day_offset)).replace(
                hour=hour, minute=minute, second=0, microsecond=0
            )
            return start, start + timedelta(minutes=duration_min)

        appointments = [
            # Jane → Rajat consult (confirmed, chatbot)
            {
                "doctor": rajat,
                "patient": jane,
                "service": consult,
                "insurance_plan": blue,
                "start_end": slot(0, 10, 0),
                "status": AppointmentStatus.CONFIRMED,
                "confirmation_code": "ACM001",
                "notes": "Chest discomfort follow-up",
                "source": AppointmentSource.CHATBOT,
            },
            # Marcus → Ali ECG (pending, phone)
            {
                "doctor": ali,
                "patient": marcus,
                "service": ecg,
                "insurance_plan": blue,
                "start_end": slot(0, 11, 0),
                "status": AppointmentStatus.PENDING,
                "confirmation_code": "ACM002",
                "notes": "Annual ECG screening",
                "source": AppointmentSource.PHONE,
            },
            # Aisha → Sofia consult (confirmed, admin)
            {
                "doctor": sofia,
                "patient": aisha,
                "service": consult,
                "insurance_plan": aetna,
                "start_end": slot(0, 14, 0),
                "status": AppointmentStatus.CONFIRMED,
                "confirmation_code": "ACM003",
                "notes": "Palpitations — new patient",
                "source": AppointmentSource.ADMIN,
            },
            # Luis → Rajat MRI (pending, chatbot) — different day / later hour
            {
                "doctor": rajat,
                "patient": luis,
                "service": mri,
                "insurance_plan": aetna,
                "start_end": slot(1, 9, 0, duration_min=60),
                "status": AppointmentStatus.PENDING,
                "confirmation_code": "ACM004",
                "notes": "Pre-op cardiac MRI",
                "source": AppointmentSource.CHATBOT,
            },
            # Jane → Ali consult (completed, walk-in) — past-ish next-week morning for Ali
            {
                "doctor": ali,
                "patient": jane,
                "service": consult,
                "insurance_plan": None,
                "start_end": slot(2, 10, 30),
                "status": AppointmentStatus.COMPLETED,
                "confirmation_code": "ACM005",
                "notes": "Blood pressure check — completed",
                "source": AppointmentSource.WALK_IN,
            },
            # Marcus → Sofia consult (cancelled)
            {
                "doctor": sofia,
                "patient": marcus,
                "service": consult,
                "insurance_plan": blue,
                "start_end": slot(2, 15, 0),
                "status": AppointmentStatus.CANCELLED,
                "confirmation_code": "ACM006",
                "notes": "Patient cancelled — travel conflict",
                "source": AppointmentSource.ADMIN,
            },
        ]

        for row in appointments:
            start, end = row["start_end"]
            Appointment.objects.create(
                clinic=clinic,
                doctor=row["doctor"],
                patient=row["patient"],
                service=row["service"],
                insurance_plan=row["insurance_plan"],
                start_time=start,
                end_time=end,
                status=row["status"],
                confirmation_code=row["confirmation_code"],
                notes=row["notes"],
                source=row["source"],
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
            patient=jane,
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
        self.stdout.write("  Doctors     : Rajat Sharma, Ali Hamza, Sofia Mendes (3)")
        self.stdout.write("  Patients    :")
        self.stdout.write("                Jane Doe    +12125550999  (verified)")
        self.stdout.write("                Marcus Chen +12125551001  (verified)")
        self.stdout.write("                Aisha Khan  +12125551002  (unverified)")
        self.stdout.write("                Luis Ortiz  +12125551003  (verified)")
        self.stdout.write("  Appointments: 6 (confirmed/pending/completed/cancelled)")

        # Clinic staff for API login
        self._ensure_staff(clinic)
        self.stdout.write("  API login   : POST /api/v1/auth/login")
        self.stdout.write(
            "                email=admin@acme-cardiology.example  password=admin123"
        )
        self.stdout.write(f"                clinic_slug={clinic.slug}")
        self.stdout.write("  Widget OTP  : POST /api/v1/widget/otp/send|verify")
        self.stdout.write("                try phone +12125550999 (or any seeded number)")
        self.stdout.write("  API docs    : http://127.0.0.1:8000/api/v1/docs")
        self.stdout.write("  Open Admin  : http://127.0.0.1:8000/admin/")
