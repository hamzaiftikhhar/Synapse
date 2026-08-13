"""
Seed three real multi-vertical clinics for thorough product testing.

Usage:
    python manage.py seed_demo_clinics --reset

Clinics:
  - horizon-family-care  (Austin TX — DPC / urgent care)
  - apex-dental          (Beverly Hills — dental / ortho)
  - lumina-skin          (Seattle — medical + cosmetic derm)
"""

from __future__ import annotations

from datetime import time

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from apps.accounts.models import ClinicStaff, User, UserRole
from apps.appointments.models import Appointment
from apps.clinics.features import default_widget_configuration
from apps.clinics.models import Clinic, ClinicBusinessHours, ClinicStatus
from apps.doctors.models import (
    Doctor,
    DoctorInsurance,
    DoctorSchedule,
    DoctorService,
    DoctorSpecialty,
)
from apps.insurance.models import InsurancePlan
from apps.knowledge.models import (
    ChunkType,
    Document,
    DocumentStatus,
    KnowledgeChunk,
    ProcessingStage,
)
from apps.services.models import Service
from apps.specialties.models import Specialty
from apps.widget.models import WidgetSettings

CLINIC_SLUGS = (
    "horizon-family-care",
    "apex-dental",
    "lumina-skin",
)


class Command(BaseCommand):
    help = "Wipe clinic tenants and seed Horizon, Apex, and Lumina with real catalogs."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete ALL clinics (and related ops data) then recreate the three demos.",
        )

    def handle(self, *args, **options):
        if not options["reset"]:
            existing = list(
                Clinic.objects.filter(slug__in=CLINIC_SLUGS).values_list("slug", flat=True)
            )
            if existing:
                self.stdout.write(
                    self.style.WARNING(
                        f"Clinics already present: {', '.join(existing)}. "
                        "Re-run with --reset to wipe and rebuild."
                    )
                )
                self._ensure_super_admin()
                return
            # Fresh install of three clinics without full wipe
            with transaction.atomic():
                self._ensure_super_admin()
                self._seed_all()
            return

        with transaction.atomic():
            self._wipe_all_clinics()
            self._ensure_super_admin()
            self._seed_all()

        self.stdout.write(self.style.SUCCESS("Seeded Horizon, Apex, and Lumina."))

    def _wipe_all_clinics(self) -> None:
        # Appointments PROTECT doctor/patient — clear first
        n_appts = Appointment.objects.all().delete()[0]
        clinic_count = Clinic.objects.count()
        deleted, _ = Clinic.objects.all().delete()
        # Remove non–super-admin staff left without memberships
        orphans = User.objects.filter(is_superuser=False).exclude(
            role=UserRole.SUPER_ADMIN
        )
        # Keep users who still have memberships; drop demo clinic admins
        for u in orphans:
            if not ClinicStaff.objects.filter(user=u).exists():
                if u.email.endswith(".test") or u.email.endswith(".example"):
                    u.delete()
        self.stdout.write(
            f"Wiped {clinic_count} clinics ({deleted} objects), {n_appts} appointments."
        )

    def _ensure_super_admin(self) -> User:
        now = timezone.now()
        user, created = User.objects.get_or_create(
            email="superadmin@synapse.local",
            defaults={
                "username": "superadmin",
                "first_name": "Super",
                "last_name": "Admin",
                "role": UserRole.SUPER_ADMIN,
                "is_staff": True,
                "is_superuser": True,
                "is_active": True,
                "email_verified_at": now,
            },
        )
        user.role = UserRole.SUPER_ADMIN
        user.is_staff = True
        user.is_superuser = True
        user.is_active = True
        if not user.email_verified_at:
            user.email_verified_at = now
        user.set_password("superadmin123")
        user.save()
        if created:
            self.stdout.write("Created superadmin@synapse.local / superadmin123")
        return user

    def _seed_all(self) -> None:
        self._seed_horizon()
        self._seed_apex()
        self._seed_lumina()

    # ── helpers ──────────────────────────────────────────────────────────────

    def _hours(
        self,
        clinic: Clinic,
        rows: list[tuple[int, time | None, time | None, bool]],
    ) -> None:
        for day, open_t, close_t, closed in rows:
            ClinicBusinessHours.objects.create(
                clinic=clinic,
                day_of_week=day,
                open_time=open_t,
                close_time=close_t,
                is_closed=closed,
            )

    def _specialty(self, clinic: Clinic, name: str, description: str = "") -> Specialty:
        return Specialty.objects.create(
            clinic=clinic,
            name=name,
            slug=slugify(name)[:64],
            description=description,
            is_active=True,
        )

    def _service(
        self,
        clinic: Clinic,
        *,
        code: str,
        name: str,
        category: str,
        price_dollars: float,
        duration_min: int,
        description: str = "",
        metadata: dict | None = None,
    ) -> Service:
        return Service.objects.create(
            clinic=clinic,
            code=code,
            name=name,
            category=category,
            description=description,
            duration_min=duration_min,
            price_cents=int(round(price_dollars * 100)),
            is_active=True,
            metadata=metadata or {},
        )

    def _insurance(
        self,
        clinic: Clinic,
        provider: str,
        plan: str,
        plan_type: str,
        accepted: bool,
        notes: str = "",
    ) -> InsurancePlan:
        return InsurancePlan.objects.create(
            clinic=clinic,
            provider_name=provider,
            plan_name=plan,
            plan_type=plan_type,
            is_accepted=accepted,
            notes=notes,
        )

    def _doctor(
        self,
        clinic: Clinic,
        *,
        full_name: str,
        title: str,
        bio: str,
        languages: list[str],
        metadata: dict,
        specialties: list[Specialty],
        services: list[Service],
        plans: list[InsurancePlan],
        schedule: list[tuple[int, time, time, int]],
    ) -> Doctor:
        doc = Doctor.objects.create(
            clinic=clinic,
            full_name=full_name,
            title=title,
            bio=bio,
            languages=languages,
            is_active=True,
            is_accepting_patients=True,
            metadata=metadata,
        )
        for sp in specialties:
            DoctorSpecialty.objects.create(doctor=doc, specialty=sp, clinic=clinic)
        for svc in services:
            DoctorService.objects.create(doctor=doc, service=svc, clinic=clinic)
        for plan in plans:
            if plan.is_accepted:
                DoctorInsurance.objects.create(
                    doctor=doc, insurance_plan=plan, clinic=clinic
                )
        for day, start, end, slot in schedule:
            DoctorSchedule.objects.create(
                clinic=clinic,
                doctor=doc,
                day_of_week=day,
                start_time=start,
                end_time=end,
                slot_duration_min=slot,
                is_active=True,
            )
        return doc

    def _owner(self, clinic: Clinic, email: str, first: str, last: str) -> User:
        now = timezone.now()
        username = slugify(email.replace("@", "-").replace(".", "-"))[:40]
        user, created = User.objects.get_or_create(
            email=email,
            defaults={
                "username": username,
                "first_name": first,
                "last_name": last,
                "role": UserRole.CLINIC_ADMIN,
                "is_clinic_owner": True,
                "is_staff": True,
                "is_active": True,
                "email_verified_at": now,
            },
        )
        user.role = UserRole.CLINIC_ADMIN
        user.is_clinic_owner = True
        user.is_active = True
        if not user.email_verified_at:
            user.email_verified_at = now
        user.set_password("admin123")
        user.save()
        ClinicStaff.objects.get_or_create(
            user=user, clinic=clinic, defaults={"is_active": True}
        )
        return user

    def _widget(self, clinic: Clinic, config: dict) -> None:
        base = default_widget_configuration()
        # deep-ish merge for known keys
        for key, val in config.items():
            if isinstance(val, dict) and isinstance(base.get(key), dict):
                base[key] = {**base[key], **val}
            else:
                base[key] = val
        WidgetSettings.objects.create(clinic=clinic, configuration=base)

    def _knowledge(
        self,
        clinic: Clinic,
        *,
        title: str,
        chunks: list[tuple[str, str]],
        keywords: list[str],
        summary: str,
        uploaded_by: User | None,
    ) -> Document:
        doc = Document.objects.create(
            clinic=clinic,
            title=title,
            file_name=f"{slugify(title)}.txt",
            file_type="text/plain",
            storage_path=f"seeded/{clinic.slug}/{slugify(title)}.txt",
            file_size_bytes=sum(len(c[1]) for c in chunks),
            status=DocumentStatus.CHUNKED,
            processing_stage=ProcessingStage.COMPLETED,
            chunk_count=len(chunks),
            uploaded_by=uploaded_by,
            routing_summary=summary,
            routing_keywords=keywords,
            metadata={"source": "seed_demo_clinics"},
        )
        created_chunks: list[KnowledgeChunk] = []
        for i, (heading, content) in enumerate(chunks, start=1):
            created_chunks.append(
                KnowledgeChunk.objects.create(
                    clinic=clinic,
                    document=doc,
                    chunk_number=i,
                    heading=heading,
                    chunk_type=ChunkType.PARAGRAPH,
                    content=content,
                )
            )
        self._embed_seed_chunks(doc, created_chunks)
        return doc

    def _embed_seed_chunks(
        self, document: Document, chunks: list[KnowledgeChunk]
    ) -> None:
        """Embed seeded chunks so vector RAG works immediately after seed."""
        if not chunks:
            return
        try:
            from django.conf import settings

            from apps.knowledge.embeddings import EmbeddingError, get_embedding_service

            if not getattr(settings, "KNOWLEDGE_RUN_EMBEDDINGS", True):
                self.stdout.write(
                    self.style.WARNING(
                        f"  Skipping embeddings for '{document.title}' "
                        "(KNOWLEDGE_RUN_EMBEDDINGS=False)"
                    )
                )
                return

            service = get_embedding_service()
            vectors = service.embed_many([c.content for c in chunks])
            model_name = service.model_name
            for chunk, vector in zip(chunks, vectors, strict=True):
                chunk.embedding = vector
                chunk.embedding_model = model_name
                chunk.save(update_fields=["embedding", "embedding_model"])
            document.status = DocumentStatus.INDEXED
            document.save(update_fields=["status", "updated_at"])
            self.stdout.write(
                self.style.SUCCESS(
                    f"  Indexed '{document.title}' ({len(chunks)} chunks embedded)"
                )
            )
        except Exception as exc:
            # Leave CHUNKED — catalog still gates routing; reindex later
            self.stdout.write(
                self.style.WARNING(
                    f"  Could not embed '{document.title}': {exc}. "
                    "Document left CHUNKED — run reindex when embeddings are available."
                )
            )

    # ── Clinic 1: Horizon ────────────────────────────────────────────────────

    def _seed_horizon(self) -> None:
        clinic = Clinic.objects.create(
            slug="horizon-family-care",
            name="Horizon Family Medicine & Urgent Care",
            email="contact@horizonfamilycare.test",
            phone="(512) 555-0144",
            timezone="America/Chicago",
            status=ClinicStatus.ACTIVE,
            address={
                "street": "1420 North Interstate 35, Suite 100",
                "city": "Austin",
                "state": "TX",
                "zip": "78701",
                "country": "US",
            },
        )
        owner = self._owner(clinic, "admin@horizonfamilycare.test", "Horizon", "Admin")
        self._widget(
            clinic,
            {
                "widget": {
                    "greeting": "Hi! Welcome to Horizon Family Medicine & Urgent Care. How can we help?",
                    "primary_color": "#0f766e",
                },
                "booking": {
                    "mode": "service_first",
                    "ai_discovery": True,
                    "slot_duration_min": 20,
                    "verification_mode": "sms",
                },
            },
        )
        self._hours(
            clinic,
            [
                (0, time(7, 30), time(19, 0), False),
                (1, time(7, 30), time(19, 0), False),
                (2, time(7, 30), time(19, 0), False),
                (3, time(7, 30), time(19, 0), False),
                (4, time(7, 30), time(19, 0), False),
                (5, time(8, 0), time(16, 0), False),
                (6, None, None, True),
            ],
        )

        sp_fm = self._specialty(clinic, "Family Medicine", "Chronic care and primary care")
        sp_im = self._specialty(clinic, "Internal Medicine", "Adult internal medicine")
        sp_uc = self._specialty(clinic, "Urgent Care", "Walk-in acute care")
        sp_well = self._specialty(clinic, "Wellness & Acute Care", "Wellness exams and acute visits")

        svc_physical = self._service(
            clinic,
            code="SRV-FM-01",
            name="Establish Patient Adult Physical",
            category="Primary Care",
            price_dollars=185,
            duration_min=45,
        )
        svc_pedi = self._service(
            clinic,
            code="SRV-FM-02",
            name="Pediatric Well-Child Exam",
            category="Primary Care",
            price_dollars=120,
            duration_min=30,
        )
        svc_uc1 = self._service(
            clinic,
            code="SRV-UC-01",
            name="Urgent Care Visit (Level 1 / Basic)",
            category="Urgent Care",
            price_dollars=135,
            duration_min=20,
        )
        svc_suture = self._service(
            clinic,
            code="SRV-UC-02",
            name="Simple Wound Laceration Repair (Sutures)",
            category="Urgent Care",
            price_dollars=240,
            duration_min=45,
        )
        svc_strep = self._service(
            clinic,
            code="SRV-LAB-01",
            name="Rapid Strep / Flu Combo Swab",
            category="In-House Lab",
            price_dollars=35,
            duration_min=10,
        )
        svc_blood = self._service(
            clinic,
            code="SRV-LAB-02",
            name="Routine Blood Draw (Venipuncture)",
            category="In-House Lab",
            price_dollars=25,
            duration_min=15,
        )

        plans_in = [
            self._insurance(clinic, "Blue Cross Blue Shield", "PPO", "PPO", True),
            self._insurance(clinic, "Blue Cross Blue Shield", "Choice POS", "POS", True),
            self._insurance(clinic, "Aetna", "HMO Plus", "HMO", True),
            self._insurance(clinic, "Aetna", "PPO", "PPO", True),
            self._insurance(clinic, "UnitedHealthcare", "Choice", "PPO", True),
            self._insurance(clinic, "UnitedHealthcare", "Choice Plus", "PPO", True),
            self._insurance(
                clinic, "Medicare", "Part B", "Medicare", True, "Direct billing"
            ),
        ]
        self._insurance(
            clinic,
            "Medicaid",
            "Standard",
            "Medicaid",
            False,
            "Not accepted for non-established urgent care walk-ins",
        )
        self._insurance(
            clinic, "Humana", "HMO", "HMO", False, "Out-of-network / cash only"
        )
        self._insurance(
            clinic,
            "Kaiser Permanente",
            "All plans",
            "HMO",
            False,
            "All Kaiser plans are cash-pay only at Horizon",
        )

        primary_svcs = [svc_physical, svc_pedi, svc_strep, svc_blood]
        uc_svcs = [svc_uc1, svc_suture, svc_strep, svc_blood]
        all_svcs = [svc_physical, svc_pedi, svc_uc1, svc_suture, svc_strep, svc_blood]

        self._doctor(
            clinic,
            full_name="Dr. Elena Rostova",
            title="MD, FAAFP",
            bio="Family medicine and chronic care. Board-certified.",
            languages=["en", "ru"],
            metadata={"credentials": "MD, FAAFP", "focus": "Family Medicine, Chronic Care"},
            specialties=[sp_fm],
            services=primary_svcs,
            plans=plans_in,
            schedule=[
                (0, time(8, 0), time(16, 0), 30),
                (2, time(8, 0), time(16, 0), 30),
                (4, time(8, 0), time(16, 0), 30),
            ],
        )
        self._doctor(
            clinic,
            full_name="Dr. Marcus Vance",
            title="DO",
            bio="Internal medicine and urgent care.",
            languages=["en", "es"],
            metadata={"credentials": "DO", "focus": "Internal Medicine, Urgent Care"},
            specialties=[sp_im, sp_uc],
            services=uc_svcs + [svc_physical],
            plans=plans_in,
            schedule=[
                (1, time(8, 0), time(16, 0), 20),
                (3, time(8, 0), time(16, 0), 20),
                (5, time(8, 0), time(16, 0), 20),
            ],
        )
        self._doctor(
            clinic,
            full_name="Sarah Jenkins",
            title="FNP-C",
            bio="Nurse practitioner — acute care and wellness exams.",
            languages=["en"],
            metadata={"credentials": "FNP-C", "focus": "Acute Care, Wellness Exams"},
            specialties=[sp_well, sp_uc],
            services=all_svcs,
            plans=plans_in,
            schedule=[
                (0, time(10, 0), time(18, 0), 20),
                (1, time(10, 0), time(18, 0), 20),
                (2, time(10, 0), time(18, 0), 20),
                (3, time(10, 0), time(18, 0), 20),
                (4, time(10, 0), time(18, 0), 20),
            ],
        )

        self._knowledge(
            clinic,
            title="Urgent care triage & insurance SOP",
            summary=(
                "Horizon is a hybrid DPC and walk-in urgent care. "
                "Red-flag emergencies go to ER. Insurance vs cash-pay rules."
            ),
            keywords=[
                "insurance",
                "medicaid",
                "cash",
                "urgent",
                "emergency",
                "membership",
                "dpc",
                "kaiser",
                "humana",
            ],
            uploaded_by=owner,
            chunks=[
                (
                    "Emergency red flags",
                    "Patients describing chest pain, stroke symptoms (face droop, arm weakness, "
                    "speech difficulty), severe shortness of breath, uncontrolled bleeding, or "
                    "loss of consciousness should be directed to call 911 or go to the nearest ER. "
                    "Horizon urgent care is not an emergency department.",
                ),
                (
                    "Insurance vs cash-pay",
                    "In-network plans include Blue Cross Blue Shield (PPO, Choice POS), Aetna "
                    "(HMO Plus, PPO), UnitedHealthcare (Choice, Choice Plus), and Medicare Part B "
                    "with direct billing. Medicaid is not accepted for non-established urgent care "
                    "walk-ins. Humana HMO and all Kaiser Permanente plans are cash-pay / "
                    "out-of-network only. Standard cash prices are listed on each service.",
                ),
                (
                    "Membership / DPC note",
                    "Horizon offers Direct Primary Care membership options for established patients. "
                    "Membership questions should be answered from this SOP and escalated to front "
                    "desk for enrollment. Membership does not replace emergency care.",
                ),
                (
                    "Sunday hours",
                    "The clinic is closed on Sundays. An urgent care phone line remains open for "
                    "triage guidance only; no in-person Sunday visits.",
                ),
            ],
        )
        self.stdout.write(f"  ✓ {clinic.slug}")

    # ── Clinic 2: Apex ───────────────────────────────────────────────────────

    def _seed_apex(self) -> None:
        clinic = Clinic.objects.create(
            slug="apex-dental",
            name="Apex Dental & Orthodontics",
            email="frontdesk@apexdental.test",
            phone="(310) 555-0199",
            timezone="America/Los_Angeles",
            status=ClinicStatus.ACTIVE,
            address={
                "street": "8840 Wilshire Blvd, Suite 200",
                "city": "Beverly Hills",
                "state": "CA",
                "zip": "90211",
                "country": "US",
            },
        )
        owner = self._owner(clinic, "admin@apexdental.test", "Apex", "Admin")
        self._widget(
            clinic,
            {
                "widget": {
                    "greeting": "Welcome to Apex Dental & Orthodontics. Book cleanings, cosmetic, or ortho consults.",
                    "primary_color": "#1d4ed8",
                },
                "booking": {
                    "mode": "service_first",
                    "slot_duration_min": 30,
                    "date_horizon_days": 21,
                    "verification_mode": "sms",
                },
            },
        )
        self._hours(
            clinic,
            [
                (0, time(8, 0), time(17, 0), False),
                (1, time(8, 0), time(17, 0), False),
                (2, time(8, 0), time(17, 0), False),
                (3, time(8, 0), time(17, 0), False),
                (4, time(8, 0), time(14, 0), False),
                (5, None, None, True),
                (6, None, None, True),
            ],
        )

        sp_gen = self._specialty(
            clinic, "General & Cosmetic Dentistry", "Cleanings, restorations, whitening"
        )
        sp_ortho = self._specialty(
            clinic, "Orthodontics", "Invisalign and orthodontic consultations"
        )

        svc_clean = self._service(
            clinic,
            code="DNT-PREV-01",
            name="Adult Cleaning, Exam & X-Rays",
            category="Preventive",
            price_dollars=220,
            duration_min=60,
        )
        svc_white = self._service(
            clinic,
            code="DNT-COSM-01",
            name="In-Office Laser Teeth Whitening",
            category="Cosmetic",
            price_dollars=450,
            duration_min=90,
        )
        svc_fill = self._service(
            clinic,
            code="DNT-REST-01",
            name="Composite Resin Filling (1 Surface)",
            category="Restorative",
            price_dollars=180,
            duration_min=45,
        )
        svc_invis = self._service(
            clinic,
            code="DNT-ORTH-01",
            name="Invisalign Comprehensive Evaluation",
            category="Orthodontics",
            price_dollars=0,
            duration_min=30,
            description="Promotional free evaluation",
        )
        svc_ext = self._service(
            clinic,
            code="DNT-SURG-01",
            name="Surgical Tooth Extraction",
            category="Oral Surgery",
            price_dollars=350,
            duration_min=60,
        )

        plans_in = [
            self._insurance(clinic, "Delta Dental", "Premier", "PPO", True),
            self._insurance(clinic, "Delta Dental", "PPO", "PPO", True),
            self._insurance(clinic, "MetLife", "PDP Plus", "PPO", True),
            self._insurance(clinic, "Guardian", "Dental Guard Preferred", "PPO", True),
            self._insurance(clinic, "Cigna", "Dental DPPO", "PPO", True),
        ]
        self._insurance(
            clinic,
            "Medi-Cal / Denti-Cal",
            "All",
            "Medicaid",
            False,
            "Not accepted. Patients seen fee-for-service cash rates.",
        )
        self._insurance(
            clinic,
            "Dental HMO (DHMO)",
            "Any",
            "HMO",
            False,
            "Apex does not accept Dental HMO plans.",
        )

        self._doctor(
            clinic,
            full_name="Dr. Aris Thorne",
            title="DDS",
            bio="General and cosmetic dentistry.",
            languages=["en", "el"],
            metadata={"credentials": "DDS", "focus": "General & Cosmetic Dentistry"},
            specialties=[sp_gen],
            services=[svc_clean, svc_white, svc_fill, svc_ext],
            plans=plans_in,
            schedule=[
                (0, time(8, 0), time(17, 0), 30),
                (1, time(8, 0), time(17, 0), 30),
                (2, time(8, 0), time(17, 0), 30),
                (3, time(8, 0), time(17, 0), 30),
            ],
        )
        self._doctor(
            clinic,
            full_name="Dr. Maya Lin",
            title="DMD, MS",
            bio="Board-certified orthodontist. Friday mornings are ortho consults.",
            languages=["en", "zh"],
            metadata={
                "credentials": "DMD, MS",
                "focus": "Board Certified Orthodontist",
            },
            specialties=[sp_ortho],
            services=[svc_invis, svc_clean],
            plans=plans_in,
            schedule=[
                (1, time(8, 0), time(16, 0), 30),
                (3, time(8, 0), time(16, 0), 30),
                (4, time(8, 0), time(14, 0), 30),
            ],
        )

        self._knowledge(
            clinic,
            title="Cancellation, post-op & multi-step orthodontics",
            summary=(
                "Apex Dental cancellation window, post-op extraction care, "
                "and Invisalign multi-step funnel."
            ),
            keywords=[
                "cancel",
                "cancellation",
                "reschedule",
                "invisalign",
                "ortho",
                "extraction",
                "post-op",
                "hmo",
                "medi-cal",
            ],
            uploaded_by=owner,
            chunks=[
                (
                    "Cancellation policy",
                    "Appointments require at least 48 hours notice to cancel or reschedule. "
                    "Late cancellations or no-shows may incur a fee of up to 50% of the "
                    "scheduled service cash price. Same-day cancellations for surgical "
                    "extractions may forfeit the deposit.",
                ),
                (
                    "Invisalign funnel",
                    "Invisalign starts with a free comprehensive evaluation (DNT-ORTH-01). "
                    "If appropriate, records and a treatment plan visit follow, then "
                    "aligner delivery. Patients should not expect trays on the first visit.",
                ),
                (
                    "Insurance note",
                    "Accepted dental PPOs: Delta Dental Premier & PPO, MetLife PDP Plus, "
                    "Guardian Dental Guard Preferred, Cigna Dental DPPO. Apex does NOT "
                    "accept Medi-Cal, Denti-Cal, or any Dental HMO (DHMO). HMO patients "
                    "are seen under standard fee-for-service cash rates.",
                ),
                (
                    "Post-op extraction",
                    "After surgical extraction: bite on gauze 30–45 minutes, no straws or "
                    "smoking 72 hours, soft foods 24 hours, call the office for uncontrolled "
                    "bleeding or fever.",
                ),
            ],
        )
        self.stdout.write(f"  ✓ {clinic.slug}")

    # ── Clinic 3: Lumina ─────────────────────────────────────────────────────

    def _seed_lumina(self) -> None:
        clinic = Clinic.objects.create(
            slug="lumina-skin",
            name="Lumina Skin & Laser Dermatology",
            email="concierge@luminaskin.test",
            phone="(206) 555-0177",
            timezone="America/Los_Angeles",
            status=ClinicStatus.ACTIVE,
            address={
                "street": "500 Pine Street, 3rd Floor",
                "city": "Seattle",
                "state": "WA",
                "zip": "98101",
                "country": "US",
            },
        )
        owner = self._owner(clinic, "admin@luminaskin.test", "Lumina", "Admin")
        self._widget(
            clinic,
            {
                "widget": {
                    "greeting": "Hello from Lumina Skin & Laser. Medical derm or cosmetic — how can we help?",
                    "primary_color": "#7c3aed",
                },
                "booking": {
                    "mode": "service_first",
                    "slot_duration_min": 30,
                    "verification_mode": "sms_or_email",
                },
            },
        )
        self._hours(
            clinic,
            [
                (0, time(9, 0), time(18, 0), False),
                (1, time(9, 0), time(18, 0), False),
                (2, time(9, 0), time(18, 0), False),
                (3, time(9, 0), time(18, 0), False),
                (4, time(9, 0), time(18, 0), False),
                (5, time(9, 0), time(15, 0), False),
                (6, None, None, True),
            ],
        )

        sp_med = self._specialty(
            clinic, "Medical & Surgical Dermatology", "Acne, moles, skin cancer"
        )
        sp_cos = self._specialty(
            clinic, "Cosmetic Injectables & Lasers", "Botox, fillers, IPL"
        )

        svc_mole = self._service(
            clinic,
            code="DERM-MED-01",
            name="Full Body Mole & Cancer Screening",
            category="Medical",
            price_dollars=210,
            duration_min=30,
        )
        svc_acne = self._service(
            clinic,
            code="DERM-MED-02",
            name="Acne Vulgaris Initial Consultation",
            category="Medical",
            price_dollars=150,
            duration_min=30,
        )
        svc_botox = self._service(
            clinic,
            code="DERM-COS-01",
            name="Botox / Dysport Wrinkle Treatment",
            category="Cosmetic",
            price_dollars=14,
            duration_min=30,
            description="Priced at $14.00 per unit. Total depends on units used.",
            metadata={"pricing_unit": "unit", "unit_label": "unit"},
        )
        svc_filler = self._service(
            clinic,
            code="DERM-COS-02",
            name="Hyaluronic Acid Dermal Filler (1 Syringe)",
            category="Cosmetic",
            price_dollars=650,
            duration_min=45,
        )
        svc_ipl = self._service(
            clinic,
            code="DERM-COS-03",
            name="IPL Photofacial (Full Face)",
            category="Laser",
            price_dollars=350,
            duration_min=60,
        )

        plans_med = [
            self._insurance(clinic, "Regence BlueShield", "Standard", "PPO", True),
            self._insurance(clinic, "Premera Blue Cross", "Standard", "PPO", True),
            self._insurance(clinic, "Aetna", "PPO", "PPO", True),
        ]

        self._doctor(
            clinic,
            full_name="Dr. Chloe Bennet",
            title="MD, FAAD",
            bio="Medical and surgical dermatology.",
            languages=["en"],
            metadata={"credentials": "MD, FAAD", "focus": "Medical & Surgical Dermatology"},
            specialties=[sp_med],
            services=[svc_mole, svc_acne],
            plans=plans_med,
            schedule=[
                (0, time(9, 0), time(17, 0), 30),
                (1, time(9, 0), time(17, 0), 30),
                (3, time(9, 0), time(17, 0), 30),
            ],
        )
        self._doctor(
            clinic,
            full_name="Julian Reyes",
            title="MPAS, PA-C",
            bio="Cosmetic injectables and laser procedures.",
            languages=["en", "tl"],
            metadata={
                "credentials": "MPAS, PA-C",
                "focus": "Cosmetic Injectables & Lasers",
            },
            specialties=[sp_cos],
            services=[svc_botox, svc_filler, svc_ipl],
            plans=[],  # cosmetic cash — no medical plan linkage needed
            schedule=[
                (2, time(9, 0), time(17, 0), 30),
                (4, time(9, 0), time(17, 0), 30),
                (5, time(9, 0), time(15, 0), 30),
            ],
        )

        self._knowledge(
            clinic,
            title="Cosmetic self-pay, consults & Saturday policy",
            summary=(
                "Lumina medical derm may use insurance; Botox, fillers, and lasers "
                "are always self-pay. Saturday is cosmetic-only."
            ),
            keywords=[
                "botox",
                "filler",
                "cosmetic",
                "laser",
                "ipl",
                "insurance",
                "self-pay",
                "deposit",
                "consultation",
                "saturday",
            ],
            uploaded_by=owner,
            chunks=[
                (
                    "Cosmetic vs medical coverage",
                    "Medical dermatology services such as biopsies, acne consultations, and "
                    "skin cancer screenings may be billed to Regence BlueShield, Premera Blue "
                    "Cross, or Aetna PPO when medically necessary. Cosmetic procedures — Botox, "
                    "Dysport, dermal fillers, and IPL photofacials — are 100% cash / self-pay. "
                    "Health insurance never covers cosmetic treatments. The chatbot must flag "
                    "cosmetic inquiries as self-pay.",
                ),
                (
                    "Botox pricing",
                    "Botox / Dysport is priced at $14 per unit. Total cost depends on the number "
                    "of units used during treatment. A consultation may be required before first "
                    "injectable visits.",
                ),
                (
                    "Deposits & consults",
                    "Cosmetic procedure bookings may require a deposit. New cosmetic patients "
                    "should complete a pre-procedure medical questionnaire. Strict consultation "
                    "rules apply before lasers and fillers.",
                ),
                (
                    "Saturday hours",
                    "Saturday 9:00 AM – 3:00 PM is reserved for cosmetic procedures only. "
                    "Medical dermatology visits are scheduled Monday–Friday.",
                ),
            ],
        )
        self.stdout.write(f"  ✓ {clinic.slug}")
