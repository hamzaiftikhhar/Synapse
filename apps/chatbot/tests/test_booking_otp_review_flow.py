"""Phase 42A — the standard (non-shortcut) booking path: a new or
returning patient typing a phone/email OTP code.

Before this phase, BookingStep.REVIEW's own docstring said this path
"already requires entering a received code, which is itself a confirming
action, so it goes straight to CONFIRMED" — meaning the single most common
booking path had no review screen and no separate "yes, book it" gesture
at all; submitting the OTP code *was* the booking. These tests assert the
new, split behavior: verify_otp lands on REVIEW (no Appointment yet),
confirm_review is the one and only action that creates it."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.appointments.models import Appointment
from apps.chatbot.booking.service import BookingError, BookingService
from apps.chatbot.booking.state import BookingStep
from apps.chatbot.models import ChatSession, ChatSessionStatus
from apps.chatbot.services.otp_service import send_otp
from apps.clinics.models import Clinic
from apps.doctors.models import Doctor, DoctorSchedule

_TZ = ZoneInfo("America/New_York")


def _next_weekday(weekday: int, *, from_days_ahead: int = 1):
    d = timezone.localdate() + timedelta(days=from_days_ahead)
    while d.weekday() != weekday:
        d += timedelta(days=1)
    return d


@override_settings(DEBUG=True)
class StandardOtpBookingFlowTests(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="standard-otp-clinic",
            name="Standard OTP Clinic",
            email="standard-otp@clinic.com",
            phone="+12125550800",
            timezone="America/New_York",
        )
        self.doctor = Doctor.objects.create(clinic=self.clinic, full_name="Dr. Standard")
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
            session_token="tok-standard-otp-1",
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

    def _start_and_submit_details(self, *, email="sam@example.com", dob="1990-01-01"):
        started = BookingService.start(
            clinic=self.clinic,
            chat_session=self.chat_session,
            doctor_id=str(self.doctor.id),
            doctor_name=self.doctor.full_name,
            slot_start=self.slot_start,
            slot_end=self.slot_end,
        )
        submitted = BookingService.apply_step(
            clinic=self.clinic,
            chat_session=self.chat_session,
            booking_id=started["booking_id"],
            action="submit_details",
            value={"first_name": "Sam", "email": email, "date_of_birth": dob},
        )
        self.assertEqual(submitted["step"], BookingStep.OTP.value)
        return started["booking_id"], email

    def test_verify_otp_lands_on_review_without_creating_an_appointment(self):
        booking_id, email = self._start_and_submit_details()
        sent = send_otp(
            clinic=self.clinic, email=email,
            session_token=self.chat_session.session_token,
        )

        result = BookingService.apply_step(
            clinic=self.clinic,
            chat_session=self.chat_session,
            booking_id=booking_id,
            action="verify_otp",
            value={"otp_code": sent.debug_code},
        )
        self.assertEqual(result["step"], BookingStep.REVIEW.value)
        self.assertFalse(Appointment.objects.filter(clinic=self.clinic).exists())

    def test_confirm_review_after_verify_otp_creates_the_appointment_exactly_once(self):
        booking_id, email = self._start_and_submit_details()
        sent = send_otp(
            clinic=self.clinic, email=email,
            session_token=self.chat_session.session_token,
        )
        BookingService.apply_step(
            clinic=self.clinic,
            chat_session=self.chat_session,
            booking_id=booking_id,
            action="verify_otp",
            value={"otp_code": sent.debug_code},
        )
        confirmed = BookingService.apply_step(
            clinic=self.clinic,
            chat_session=self.chat_session,
            booking_id=booking_id,
            action="confirm_review",
            value={},
        )
        self.assertEqual(confirmed["step"], BookingStep.CONFIRMED.value)
        self.assertEqual(
            Appointment.objects.filter(clinic=self.clinic).count(), 1
        )

    def test_wrong_otp_code_stays_on_otp_step_no_appointment(self):
        booking_id, email = self._start_and_submit_details()
        send_otp(
            clinic=self.clinic, email=email,
            session_token=self.chat_session.session_token,
        )

        with self.assertRaises(BookingError):
            BookingService.apply_step(
                clinic=self.clinic,
                chat_session=self.chat_session,
                booking_id=booking_id,
                action="verify_otp",
                value={"otp_code": "000000"},
            )
        self.assertFalse(Appointment.objects.filter(clinic=self.clinic).exists())

    def test_wrong_dob_at_verify_otp_blocks_review_for_a_returning_patient(self):
        from apps.patients.models import Patient
        from datetime import date

        Patient.objects.create(
            clinic=self.clinic, phone="+15559995678", email="returning@example.com",
            first_name="Returning", last_name="Patient", date_of_birth=date(1980, 6, 15),
        )
        booking_id, email = self._start_and_submit_details(
            email="returning@example.com", dob="1999-12-31"
        )
        sent = send_otp(
            clinic=self.clinic, email=email,
            session_token=self.chat_session.session_token,
        )

        with self.assertRaises(BookingError) as ctx:
            BookingService.apply_step(
                clinic=self.clinic,
                chat_session=self.chat_session,
                booking_id=booking_id,
                action="verify_otp",
                value={"otp_code": sent.debug_code},
            )
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertFalse(Appointment.objects.filter(clinic=self.clinic).exists())

    def test_confirm_review_without_verify_otp_first_is_rejected(self):
        """The REVIEW step must not be reachable with an unverified
        identity by simply skipping straight to confirm_review — the
        session's own step machine already gates this (confirm_review
        requires session.step == REVIEW, which only verify_otp/the
        shortcut paths ever set)."""
        booking_id, _email = self._start_and_submit_details()
        with self.assertRaises(BookingError):
            BookingService.apply_step(
                clinic=self.clinic,
                chat_session=self.chat_session,
                booking_id=booking_id,
                action="confirm_review",
                value={},
            )


@override_settings(DEBUG=True)
class EditDetailsAtReviewTests(TestCase):
    """The Review screen lets a patient fix a typo'd name or change their
    insurance selection in place (edit_details), without re-running
    DETAILS→OTP. Phone/email/DOB are the identity-verification anchor and
    are deliberately not accepted here — changing those has to go back
    through real re-verification via the existing "back" action."""

    def setUp(self):
        from apps.insurance.models import InsurancePlan

        self.clinic = Clinic.objects.create(
            slug="edit-review-clinic",
            name="Edit Review Clinic",
            email="edit-review@clinic.com",
            phone="+12125550900",
            timezone="America/New_York",
        )
        self.plan = InsurancePlan.objects.create(
            clinic=self.clinic, provider_name="Aetna", plan_name="PPO",
            plan_type="PPO", is_accepted=True,
        )
        self.doctor = Doctor.objects.create(clinic=self.clinic, full_name="Dr. Editable")
        self.target_date = _next_weekday(timezone.localdate().weekday())
        DoctorSchedule.objects.create(
            clinic=self.clinic, doctor=self.doctor,
            day_of_week=self.target_date.weekday(),
            start_time=time(9, 0), end_time=time(11, 0), slot_duration_min=30,
        )
        self.chat_session = ChatSession.objects.create(
            clinic=self.clinic, session_token="tok-edit-review-1",
            status=ChatSessionStatus.ACTIVE, is_authenticated=False,
        )
        start = datetime(
            self.target_date.year, self.target_date.month, self.target_date.day, 9, 0,
            tzinfo=_TZ,
        )
        self.slot_start = start.isoformat()
        self.slot_end = (start + timedelta(minutes=30)).isoformat()

    def _reach_review(self, email="sam@example.com"):
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
            value={"first_name": "Sam", "email": email, "date_of_birth": "1990-01-01"},
        )
        sent = send_otp(
            clinic=self.clinic, email=email,
            session_token=self.chat_session.session_token,
        )
        review = BookingService.apply_step(
            clinic=self.clinic,
            chat_session=self.chat_session,
            booking_id=started["booking_id"],
            action="verify_otp",
            value={"otp_code": sent.debug_code},
        )
        return started["booking_id"], review

    def test_edit_details_updates_name_and_insurance_and_stays_on_review(self):
        booking_id, _review = self._reach_review()
        result = BookingService.apply_step(
            clinic=self.clinic,
            chat_session=self.chat_session,
            booking_id=booking_id,
            action="edit_details",
            value={
                "first_name": "Samantha",
                "last_name": "Rivera",
                "insurance_name": "Aetna PPO",
            },
        )
        self.assertEqual(result["step"], BookingStep.REVIEW.value)
        self.assertEqual(result["review"]["first_name"], "Samantha")
        self.assertEqual(result["review"]["last_name"], "Rivera")
        self.assertIn("Aetna", result["review"]["insurance_plan_name"])

    def test_edit_details_requires_first_name(self):
        booking_id, _review = self._reach_review()
        with self.assertRaises(BookingError):
            BookingService.apply_step(
                clinic=self.clinic,
                chat_session=self.chat_session,
                booking_id=booking_id,
                action="edit_details",
                value={"first_name": "  "},
            )

    def test_edit_details_before_review_step_is_rejected(self):
        started = BookingService.start(
            clinic=self.clinic,
            chat_session=self.chat_session,
            doctor_id=str(self.doctor.id),
            doctor_name=self.doctor.full_name,
            slot_start=self.slot_start,
            slot_end=self.slot_end,
        )
        with self.assertRaises(BookingError):
            BookingService.apply_step(
                clinic=self.clinic,
                chat_session=self.chat_session,
                booking_id=started["booking_id"],
                action="edit_details",
                value={"first_name": "Sam"},
            )

    def test_edit_details_ignores_phone_and_email_fields(self):
        booking_id, review = self._reach_review()
        original_email = review["review"]["email"]
        result = BookingService.apply_step(
            clinic=self.clinic,
            chat_session=self.chat_session,
            booking_id=booking_id,
            action="edit_details",
            value={
                "first_name": "Sam",
                "phone": "+19998887777",
                "email": "someone-else@example.com",
            },
        )
        self.assertEqual(result["review"]["email"], original_email)
        self.assertFalse(result["review"]["phone"])

    def test_confirmed_appointment_reflects_the_edited_name(self):
        booking_id, _review = self._reach_review()
        BookingService.apply_step(
            clinic=self.clinic,
            chat_session=self.chat_session,
            booking_id=booking_id,
            action="edit_details",
            value={"first_name": "Samantha", "last_name": "Rivera"},
        )
        confirmed = BookingService.apply_step(
            clinic=self.clinic,
            chat_session=self.chat_session,
            booking_id=booking_id,
            action="confirm_review",
            value={},
        )
        self.assertEqual(confirmed["step"], BookingStep.CONFIRMED.value)
        self.assertEqual(confirmed["confirmation"]["first_name"], "Samantha")
