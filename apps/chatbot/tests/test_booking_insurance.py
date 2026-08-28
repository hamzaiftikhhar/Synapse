"""Phase 42A — insurance selected during booking must resolve to a real
InsurancePlan and survive to the final Appointment, not just get folded
into a free-text `reason` string (the old behavior: never resolved, never
shown at review, never actually set on Appointment.insurance_plan despite
the FK existing)."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.test import TestCase
from django.utils import timezone

from apps.appointments.models import Appointment
from apps.chatbot.booking.service import BookingService
from apps.chatbot.booking.state import BookingStep
from apps.chatbot.models import ChatSession, ChatSessionStatus
from apps.clinics.models import Clinic
from apps.doctors.models import Doctor, DoctorSchedule
from apps.insurance.models import InsurancePlan
from apps.widget.models import WidgetSettings

_TZ = ZoneInfo("America/New_York")


def _next_weekday(weekday: int, *, from_days_ahead: int = 1):
    d = timezone.localdate() + timedelta(days=from_days_ahead)
    while d.weekday() != weekday:
        d += timedelta(days=1)
    return d


class InsuranceThreadedThroughBookingTests(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="insurance-booking-clinic",
            name="Insurance Booking Clinic",
            email="insurance-booking@clinic.com",
            phone="+12125550700",
            timezone="America/New_York",
        )
        WidgetSettings.objects.create(
            clinic=self.clinic,
            configuration={"booking": {"verification_mode": "none"}},
        )
        self.plan = InsurancePlan.objects.create(
            clinic=self.clinic,
            provider_name="Aetna",
            plan_name="PPO",
            plan_type="PPO",
            is_accepted=True,
        )
        self.doctor = Doctor.objects.create(clinic=self.clinic, full_name="Dr. Open")
        self.target_date = _next_weekday(timezone.localdate().weekday())
        DoctorSchedule.objects.create(
            clinic=self.clinic,
            doctor=self.doctor,
            day_of_week=self.target_date.weekday(),
            start_time=time(9, 0),
            end_time=time(11, 0),
            slot_duration_min=30,
        )
        self.chat_session = ChatSession.objects.create(
            clinic=self.clinic,
            session_token="tok-insurance-1",
            status=ChatSessionStatus.ACTIVE,
            is_authenticated=False,
        )
        start = datetime(
            self.target_date.year, self.target_date.month, self.target_date.day, 9, 0,
            tzinfo=_TZ,
        )
        end = start + timedelta(minutes=30)
        self.slot_start = start.isoformat()
        self.slot_end = end.isoformat()

    def test_start_resolves_insurance_name_to_a_real_plan(self):
        started = BookingService.start(
            clinic=self.clinic,
            chat_session=self.chat_session,
            doctor_id=str(self.doctor.id),
            doctor_name=self.doctor.full_name,
            slot_start=self.slot_start,
            slot_end=self.slot_end,
            insurance_name="Aetna PPO",
        )
        booking = (self.chat_session.conversation_context or {}).get("booking") or {}
        self.assertEqual(booking.get("insurance_plan_id"), str(self.plan.id))
        self.assertIn("Aetna", booking.get("insurance_plan_name") or "")

    def test_confirmed_appointment_has_the_resolved_insurance_plan(self):
        started = BookingService.start(
            clinic=self.clinic,
            chat_session=self.chat_session,
            doctor_id=str(self.doctor.id),
            doctor_name=self.doctor.full_name,
            slot_start=self.slot_start,
            slot_end=self.slot_end,
            insurance_name="Aetna PPO",
        )
        BookingService.apply_step(
            clinic=self.clinic,
            chat_session=self.chat_session,
            booking_id=started["booking_id"],
            action="submit_details",
            value={
                "first_name": "Sam",
                "phone": "+15559990111",
                "date_of_birth": "1990-01-01",
            },
        )
        result = BookingService.apply_step(
            clinic=self.clinic,
            chat_session=self.chat_session,
            booking_id=started["booking_id"],
            action="confirm_review",
            value={},
        )
        self.assertEqual(result["step"], BookingStep.CONFIRMED.value)
        appt = Appointment.objects.get(clinic=self.clinic)
        self.assertEqual(appt.insurance_plan_id, self.plan.id)

    def test_unmatched_insurance_name_does_not_crash_or_set_a_wrong_plan(self):
        started = BookingService.start(
            clinic=self.clinic,
            chat_session=self.chat_session,
            doctor_id=str(self.doctor.id),
            doctor_name=self.doctor.full_name,
            slot_start=self.slot_start,
            slot_end=self.slot_end,
            insurance_name="Some Totally Unknown Insurer Co",
        )
        booking = (self.chat_session.conversation_context or {}).get("booking") or {}
        self.assertIsNone(booking.get("insurance_plan_id"))

    def test_no_insurance_selected_leaves_appointment_plan_null(self):
        started = BookingService.start(
            clinic=self.clinic,
            chat_session=self.chat_session,
            doctor_id=str(self.doctor.id),
            doctor_name=self.doctor.full_name,
            slot_start=self.slot_start,
            slot_end=self.slot_end,
        )
        BookingService.apply_step(
            clinic=self.clinic,
            chat_session=self.chat_session,
            booking_id=started["booking_id"],
            action="submit_details",
            value={
                "first_name": "Sam",
                "phone": "+15559990112",
                "date_of_birth": "1990-01-01",
            },
        )
        BookingService.apply_step(
            clinic=self.clinic,
            chat_session=self.chat_session,
            booking_id=started["booking_id"],
            action="confirm_review",
            value={},
        )
        appt = Appointment.objects.get(clinic=self.clinic)
        self.assertIsNone(appt.insurance_plan_id)


class ReviewPayloadCompletenessTests(TestCase):
    """Phase 42A: the Review & Confirm screen must show everything the
    final booking would actually create — patient contact, insurance,
    location, verification status, and a disclaimer — not just time/
    doctor/date/service (the old REVIEW payload's full field list)."""

    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="review-payload-clinic",
            name="Review Payload Clinic",
            email="review-payload@clinic.com",
            phone="+12125550701",
            address={"street": "1 Main St", "city": "Boston", "state": "MA", "zip": "02101"},
            timezone="America/New_York",
        )
        WidgetSettings.objects.create(
            clinic=self.clinic,
            configuration={"booking": {"verification_mode": "none"}},
        )
        self.plan = InsurancePlan.objects.create(
            clinic=self.clinic, provider_name="Aetna", plan_name="PPO",
            plan_type="PPO", is_accepted=True,
        )
        self.doctor = Doctor.objects.create(clinic=self.clinic, full_name="Dr. Open")
        self.target_date = _next_weekday(timezone.localdate().weekday())
        DoctorSchedule.objects.create(
            clinic=self.clinic, doctor=self.doctor,
            day_of_week=self.target_date.weekday(),
            start_time=time(9, 0), end_time=time(11, 0), slot_duration_min=30,
        )
        self.chat_session = ChatSession.objects.create(
            clinic=self.clinic, session_token="tok-review-payload-1",
            status=ChatSessionStatus.ACTIVE, is_authenticated=False,
        )
        start = datetime(
            self.target_date.year, self.target_date.month, self.target_date.day, 9, 0,
            tzinfo=_TZ,
        )
        self.slot_start = start.isoformat()
        self.slot_end = (start + timedelta(minutes=30)).isoformat()

    def test_review_payload_includes_contact_insurance_location_and_disclaimer(self):
        started = BookingService.start(
            clinic=self.clinic,
            chat_session=self.chat_session,
            doctor_id=str(self.doctor.id),
            doctor_name=self.doctor.full_name,
            slot_start=self.slot_start,
            slot_end=self.slot_end,
            insurance_name="Aetna PPO",
        )
        result = BookingService.apply_step(
            clinic=self.clinic,
            chat_session=self.chat_session,
            booking_id=started["booking_id"],
            action="submit_details",
            value={
                "first_name": "Sam",
                "last_name": "Rivera",
                "phone": "+15559990300",
                "email": "sam@example.com",
                "date_of_birth": "1990-01-01",
            },
        )
        self.assertEqual(result["step"], BookingStep.REVIEW.value)
        review = result["review"]
        self.assertEqual(review["first_name"], "Sam")
        self.assertEqual(review["last_name"], "Rivera")
        self.assertEqual(review["phone"], "+15559990300")
        self.assertEqual(review["email"], "sam@example.com")
        self.assertIn("Aetna", review["insurance_plan_name"])
        self.assertIn("Boston", review["location"])
        self.assertTrue(review["disclaimer"])

    def test_review_payload_shows_not_selected_when_no_insurance_given(self):
        started = BookingService.start(
            clinic=self.clinic,
            chat_session=self.chat_session,
            doctor_id=str(self.doctor.id),
            doctor_name=self.doctor.full_name,
            slot_start=self.slot_start,
            slot_end=self.slot_end,
        )
        result = BookingService.apply_step(
            clinic=self.clinic,
            chat_session=self.chat_session,
            booking_id=started["booking_id"],
            action="submit_details",
            value={
                "first_name": "Sam",
                "phone": "+15559990301",
                "date_of_birth": "1990-01-01",
            },
        )
        self.assertIsNone(result["review"]["insurance_plan_name"])

    def test_confirmed_payload_also_includes_location_and_service(self):
        started = BookingService.start(
            clinic=self.clinic,
            chat_session=self.chat_session,
            doctor_id=str(self.doctor.id),
            doctor_name=self.doctor.full_name,
            slot_start=self.slot_start,
            slot_end=self.slot_end,
        )
        BookingService.apply_step(
            clinic=self.clinic,
            chat_session=self.chat_session,
            booking_id=started["booking_id"],
            action="submit_details",
            value={
                "first_name": "Sam",
                "phone": "+15559990302",
                "date_of_birth": "1990-01-01",
            },
        )
        confirmed = BookingService.apply_step(
            clinic=self.clinic,
            chat_session=self.chat_session,
            booking_id=started["booking_id"],
            action="confirm_review",
            value={},
        )
        self.assertIn("Boston", confirmed["confirmation"]["location"])
