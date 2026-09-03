"""BookingService.start() resumes an in-progress draft instead of always
creating a new BookingSession (the "booking restarts constantly" bug), and
supports slot-filling from free text ("Botox Friday after 5")."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.test import TestCase
from django.utils import timezone

from apps.chatbot.booking.service import BookingService
from apps.chatbot.booking.state import BookingStep
from apps.chatbot.models import ChatSession, ChatSessionStatus
from apps.clinics.models import Clinic
from apps.doctors.models import Doctor, DoctorSchedule, DoctorService, DoctorSpecialty
from apps.services.models import Service
from apps.specialties.models import Specialty


def _next_friday_matching_parse_natural_date(tz_name: str = "America/New_York"):
    """Mirrors sql_tool.utils.parse_natural_date's weekday resolution exactly,
    so the test's expected date always agrees with what start() computes."""
    today = timezone.now().astimezone(ZoneInfo(tz_name)).date()
    days_ahead = (4 - today.weekday()) % 7 or 7
    return today + timedelta(days=days_ahead)


class BookingResumeTests(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="resume-clinic",
            name="Resume Clinic",
            email="resume@clinic.com",
            phone="+12125550004",
            timezone="America/New_York",
        )
        self.chat_session = ChatSession.objects.create(
            clinic=self.clinic,
            session_token="tok-resume-1",
            status=ChatSessionStatus.ACTIVE,
        )
        self.doctor_a = Doctor.objects.create(clinic=self.clinic, full_name="Dr. A")
        self.doctor_b = Doctor.objects.create(clinic=self.clinic, full_name="Dr. B")

    def test_second_start_resumes_same_booking_id(self):
        first = BookingService.start(clinic=self.clinic, chat_session=self.chat_session)
        self.chat_session.refresh_from_db()
        second = BookingService.start(clinic=self.clinic, chat_session=self.chat_session)

        self.assertFalse(first["resumed"])
        self.assertTrue(second["resumed"])
        self.assertEqual(first["booking_id"], second["booking_id"])

    def test_correcting_doctor_updates_in_place_and_clears_date(self):
        first = BookingService.start(
            clinic=self.clinic,
            chat_session=self.chat_session,
            doctor_id=str(self.doctor_a.id),
        )
        self.chat_session.refresh_from_db()
        # Move to DATE step and pick a date, then "correct" the doctor.
        booking = self.chat_session.conversation_context["booking"]
        booking["date"] = timezone.localdate().isoformat()
        booking["slot_start"] = timezone.now().isoformat()
        booking["patient_first_name"] = "Jamie"
        self.chat_session.conversation_context["booking"] = booking
        self.chat_session.save(update_fields=["conversation_context"])

        second = BookingService.start(
            clinic=self.clinic,
            chat_session=self.chat_session,
            doctor_id=str(self.doctor_b.id),
        )

        self.assertEqual(first["booking_id"], second["booking_id"])
        self.chat_session.refresh_from_db()
        updated = self.chat_session.conversation_context["booking"]
        self.assertEqual(updated["doctor_id"], str(self.doctor_b.id))
        self.assertIsNone(updated["date"])
        self.assertIsNone(updated["slot_start"])
        # Patient-entered details are never erased by a doctor/specialty correction.
        self.assertEqual(updated["patient_first_name"], "Jamie")

    def test_generic_book_request_does_not_resume_time_step(self):
        first = BookingService.start(
            clinic=self.clinic,
            chat_session=self.chat_session,
            doctor_id=str(self.doctor_a.id),
            doctor_name="Dr. A",
        )
        self.chat_session.refresh_from_db()
        booking = self.chat_session.conversation_context["booking"]
        booking["step"] = BookingStep.TIME.value
        booking["date"] = timezone.localdate().isoformat()
        self.chat_session.conversation_context["booking"] = booking
        self.chat_session.save(update_fields=["conversation_context"])

        second = BookingService.start(
            clinic=self.clinic,
            chat_session=self.chat_session,
            message="i would like to book an appointment",
        )

        self.assertFalse(second["resumed"])
        self.assertNotEqual(first["booking_id"], second["booking_id"])
        self.assertEqual(second["step"], BookingStep.PATH.value)

    def test_colloquial_book_does_not_resume_date_step(self):
        first = BookingService.start(
            clinic=self.clinic,
            chat_session=self.chat_session,
            doctor_id=str(self.doctor_a.id),
            doctor_name="Dr. A",
        )
        self.chat_session.refresh_from_db()
        booking = self.chat_session.conversation_context["booking"]
        booking["step"] = BookingStep.DATE.value
        booking["date"] = timezone.localdate().isoformat()
        self.chat_session.conversation_context["booking"] = booking
        self.chat_session.save(update_fields=["conversation_context"])

        second = BookingService.start(
            clinic=self.clinic,
            chat_session=self.chat_session,
            message="can you book me",
        )

        self.assertFalse(second["resumed"])
        self.assertNotEqual(first["booking_id"], second["booking_id"])
        self.assertEqual(second["step"], BookingStep.PATH.value)

    def test_start_after_confirmed_creates_fresh_booking(self):
        first = BookingService.start(clinic=self.clinic, chat_session=self.chat_session)
        self.chat_session.refresh_from_db()
        booking = self.chat_session.conversation_context["booking"]
        booking["step"] = BookingStep.CONFIRMED.value
        self.chat_session.conversation_context["booking"] = booking
        self.chat_session.save(update_fields=["conversation_context"])

        second = BookingService.start(clinic=self.clinic, chat_session=self.chat_session)

        self.assertFalse(second["resumed"])
        self.assertNotEqual(first["booking_id"], second["booking_id"])

    def test_new_service_pick_does_not_inherit_stale_doctor(self):
        """Live-confirmed bug: an abandoned earlier draft pinned Dr. A and
        reached DETAILS (a _SLOT_COMMITTED_STEPS step). Picking a *different*
        service from a fresh service card (service_id, no doctor_id) — the
        exact call shape select_service in chat-widget.tsx sends — must ask
        the patient to choose a doctor for the new service, not silently
        resume straight to "Choose a date" with the old, unrelated doctor
        still attached."""
        service_x = Service.objects.create(
            clinic=self.clinic, name="Service X", duration_min=30, price_cents=10000
        )
        service_y = Service.objects.create(
            clinic=self.clinic, name="Service Y", duration_min=30, price_cents=10000
        )
        first = BookingService.start(
            clinic=self.clinic,
            chat_session=self.chat_session,
            doctor_id=str(self.doctor_a.id),
            doctor_name="Dr. A",
            service_id=str(service_x.id),
            service_name="Service X",
        )
        self.chat_session.refresh_from_db()
        booking = self.chat_session.conversation_context["booking"]
        booking["step"] = BookingStep.DETAILS.value
        self.chat_session.conversation_context["booking"] = booking
        self.chat_session.save(update_fields=["conversation_context"])

        second = BookingService.start(
            clinic=self.clinic,
            chat_session=self.chat_session,
            message="I would like to book Service Y",
            reason="I would like to book Service Y",
            service_id=str(service_y.id),
            service_name="Service Y",
        )

        self.assertEqual(first["booking_id"], second["booking_id"])
        self.assertEqual(second["step"], BookingStep.DOCTOR.value)
        self.chat_session.refresh_from_db()
        updated = self.chat_session.conversation_context["booking"]
        self.assertIsNone(updated["doctor_id"])
        self.assertIsNone(updated["doctor_name"])
        self.assertEqual(updated["service_id"], str(service_y.id))


class BookingSlotFillingIntegrationTests(TestCase):
    """End-to-end: "Book Botox Friday after 5" seeds service/date/time_hint
    and, once a doctor is chosen, jumps straight to the TIME step."""

    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="botox-clinic",
            name="Botox Clinic",
            email="botox@clinic.com",
            phone="+12125550005",
            timezone="America/New_York",
        )
        self.chat_session = ChatSession.objects.create(
            clinic=self.clinic,
            session_token="tok-botox-1",
            status=ChatSessionStatus.ACTIVE,
        )
        self.aesthetics = Specialty.objects.create(
            clinic=self.clinic, name="Aesthetics", slug="aesthetics"
        )
        self.botox = Service.objects.create(
            clinic=self.clinic, name="Botox", duration_min=30, price_cents=50000
        )
        self.doctor = Doctor.objects.create(
            clinic=self.clinic, full_name="Dr. Aesthetic", is_accepting_patients=True
        )
        DoctorSpecialty.objects.create(
            clinic=self.clinic, doctor=self.doctor, specialty=self.aesthetics
        )
        DoctorService.objects.create(
            clinic=self.clinic, doctor=self.doctor, service=self.botox
        )
        self.friday = _next_friday_matching_parse_natural_date()
        DoctorSchedule.objects.create(
            clinic=self.clinic,
            doctor=self.doctor,
            day_of_week=self.friday.weekday(),
            start_time=time(9, 0),
            end_time=time(18, 0),
            slot_duration_min=30,
        )

    def test_specialty_resolves_from_service(self):
        from apps.chatbot.nlu.resolvers import resolve_specialty_for_service

        self.assertEqual(
            resolve_specialty_for_service(self.clinic, str(self.botox.id)),
            str(self.aesthetics.id),
        )

    def test_start_seeds_date_and_time_hint_from_free_text(self):
        result = BookingService.start(
            clinic=self.clinic,
            chat_session=self.chat_session,
            message="Book Botox Friday after 5",
            service_id=str(self.botox.id),
        )
        self.assertEqual(result["mode"], "service_first")
        # Doctor not yet known -> stays at DOCTOR step (only date/time_hint are seeded).
        self.assertEqual(result["step"], BookingStep.DOCTOR.value)
        self.chat_session.refresh_from_db()
        booking = self.chat_session.conversation_context["booking"]
        self.assertEqual(booking["date"], self.friday.isoformat())
        self.assertEqual(booking["time_hint"], "17:00:00")

    def test_known_doctor_and_date_hint_jumps_straight_to_time_step(self):
        """When the chat engine has already resolved both the service
        and a named doctor from "Book Botox Friday after 5 with Dr. Aesthetic",
        start() should skip PATH/SERVICE/DOCTOR/DATE entirely."""
        result = BookingService.start(
            clinic=self.clinic,
            chat_session=self.chat_session,
            message="Book Botox Friday after 5",
            service_id=str(self.botox.id),
            doctor_id=str(self.doctor.id),
        )

        self.assertEqual(result["step"], BookingStep.TIME.value)
        slots = result["options"]["slots"]
        self.assertTrue(slots)
        for slot in slots:
            start = datetime.fromisoformat(slot["start"])
            self.assertGreaterEqual(start.time(), time(17, 0))


class BookingDraftIsolationTests(TestCase):
    """A new booking utterance must not inherit who/what/when it did not pin."""

    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="isolate-clinic",
            name="Isolate Clinic",
            email="iso@clinic.com",
            phone="+12125550055",
            timezone="America/Los_Angeles",
        )
        self.chat_session = ChatSession.objects.create(
            clinic=self.clinic,
            session_token="tok-isolate-1",
            status=ChatSessionStatus.ACTIVE,
        )
        self.maya = Doctor.objects.create(clinic=self.clinic, full_name="Dr. Maya Lin")
        self.aris = Doctor.objects.create(clinic=self.clinic, full_name="Dr. Aris Thorne")
        self.cleaning = Service.objects.create(
            clinic=self.clinic, name="Adult Cleaning, Exam & X-Rays"
        )

    def _seed_review_draft(self, *, doctor, service):
        BookingService.start(
            clinic=self.clinic,
            chat_session=self.chat_session,
            doctor_id=str(doctor.id),
            doctor_name=doctor.full_name,
            service_id=str(service.id),
            service_name=service.name,
        )
        self.chat_session.refresh_from_db()
        booking = self.chat_session.conversation_context["booking"]
        booking["step"] = BookingStep.REVIEW.value
        booking["date"] = timezone.localdate().isoformat()
        booking["slot_start"] = timezone.now().isoformat()
        booking["slot_end"] = (timezone.now() + timedelta(minutes=30)).isoformat()
        booking["service_id"] = str(service.id)
        booking["service_name"] = service.name
        self.chat_session.conversation_context["booking"] = booking
        self.chat_session.save(update_fields=["conversation_context"])
        return booking["booking_id"]

    def test_naming_a_doctor_drops_leftover_service_and_held_slot(self):
        leftover_id = self._seed_review_draft(doctor=self.aris, service=self.cleaning)
        result = BookingService.start(
            clinic=self.clinic,
            chat_session=self.chat_session,
            message="could you get me in with Dr Lin right away",
            doctor_id=str(self.maya.id),
            doctor_name=self.maya.full_name,
        )
        self.chat_session.refresh_from_db()
        updated = self.chat_session.conversation_context["booking"]
        self.assertEqual(updated["booking_id"], leftover_id)
        self.assertEqual(updated["doctor_id"], str(self.maya.id))
        self.assertIsNone(updated["service_id"])
        self.assertIsNone(updated["slot_start"])
        self.assertNotEqual(updated["step"], BookingStep.REVIEW.value)

    def test_same_doctor_reasked_without_a_slot_does_not_reuse_review(self):
        self._seed_review_draft(doctor=self.maya, service=self.cleaning)
        result = BookingService.start(
            clinic=self.clinic,
            chat_session=self.chat_session,
            message="put me down for Maya as soon as you can",
            doctor_id=str(self.maya.id),
            doctor_name=self.maya.full_name,
        )
        self.chat_session.refresh_from_db()
        updated = self.chat_session.conversation_context["booking"]
        self.assertIsNone(updated["service_id"])
        self.assertIsNone(updated["slot_start"])
        self.assertNotEqual(result["step"], BookingStep.REVIEW.value)

    def test_explicit_slot_tap_is_not_treated_as_stale(self):
        self._seed_review_draft(doctor=self.maya, service=self.cleaning)
        start = timezone.now().replace(microsecond=0)
        end = start + timedelta(minutes=30)
        # Slot revalidation needs an open schedule; if the slot is closed
        # start() falls back to DATE, which is still not leftover REVIEW.
        result = BookingService.start(
            clinic=self.clinic,
            chat_session=self.chat_session,
            doctor_id=str(self.maya.id),
            slot_start=start.isoformat(),
            slot_end=end.isoformat(),
        )
        self.assertNotEqual(result["step"], BookingStep.PATH.value)

    def test_service_picked_moments_ago_survives_an_immediate_doctor_pick(self):
        """Regression: an earlier version of stale_service fired on *any*
        doctor_id-without-service_id call, not just a committed (REVIEW/
        DETAILS/OTP) draft — so picking a service and then, in the very next
        action of the same live flow, picking a doctor silently dropped the
        service the patient had just chosen seconds earlier. Reproduced
        directly against BookingService.start() before this test existed:
        service_id survived the first call, then came back None after the
        very next start() call that only named a doctor."""
        result = BookingService.start(
            clinic=self.clinic,
            chat_session=self.chat_session,
            service_id=str(self.cleaning.id),
            service_name=self.cleaning.name,
        )
        self.assertEqual(result["step"], BookingStep.DOCTOR.value)

        result = BookingService.start(
            clinic=self.clinic,
            chat_session=self.chat_session,
            message="actually with dr maya",
            doctor_id=str(self.maya.id),
            doctor_name=self.maya.full_name,
        )
        self.chat_session.refresh_from_db()
        updated = self.chat_session.conversation_context["booking"]
        self.assertEqual(updated["service_id"], str(self.cleaning.id))
        self.assertEqual(updated["service_name"], self.cleaning.name)
        self.assertEqual(updated["doctor_id"], str(self.maya.id))
