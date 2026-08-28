"""Authenticated patients must not re-enter DETAILS/OTP after picking a
slot — but they must still see a REVIEW step and take an explicit "Confirm
booking" action before a real Appointment is created. Skipping DETAILS/OTP
used to mean skipping straight to a committed, CONFIRMED appointment with
zero deliberate user gesture between picking a time and being told
"you're confirmed" — these tests originally asserted that old behavior;
they're updated here to assert the new REVIEW gate instead, not loosened."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.test import TestCase
from django.utils import timezone

from apps.appointments.models import Appointment, AppointmentStatus
from apps.chatbot.booking.service import BookingError, BookingService
from apps.chatbot.booking.state import BookingStep
from apps.chatbot.models import ChatSession, ChatSessionStatus
from apps.clinics.models import Clinic
from apps.doctors.models import Doctor, DoctorSchedule
from apps.patients.models import Patient
from apps.patients.services import patient_service

_TZ = ZoneInfo("America/New_York")


def _next_weekday(weekday: int, *, from_days_ahead: int = 0):
    d = timezone.localdate() + timedelta(days=from_days_ahead)
    while d.weekday() != weekday:
        d += timedelta(days=1)
    return d


class EmailPlaceholderPhoneTests(TestCase):
    def test_prefix_sharing_emails_get_distinct_placeholders(self):
        e1 = "collision-test-abcdefg@example.com"
        e2 = "collision-test-abcdefg@different.org"
        p1 = patient_service.email_placeholder_phone(e1)
        p2 = patient_service.email_placeholder_phone(e2)
        self.assertNotEqual(p1, p2)
        self.assertEqual(len(p1), 20)
        self.assertEqual(len(p2), 20)
        self.assertTrue(p1.startswith("email:"))
        # Old truncation would have collided:
        self.assertEqual((f"email:{e1}")[:20], (f"email:{e2}")[:20])

    def test_placeholder_is_case_insensitive(self):
        self.assertEqual(
            patient_service.email_placeholder_phone("Ali@Example.com"),
            patient_service.email_placeholder_phone("ali@example.com"),
        )


class AuthSkipConfirmTests(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="auth-skip-clinic",
            name="Auth Skip Clinic",
            email="auth-skip@clinic.com",
            phone="+12125550100",
            timezone="America/New_York",
        )
        self.doctor = Doctor.objects.create(clinic=self.clinic, full_name="Dr. Skip")
        self.target_date = _next_weekday(timezone.localdate().weekday(), from_days_ahead=1)
        DoctorSchedule.objects.create(
            clinic=self.clinic,
            doctor=self.doctor,
            day_of_week=self.target_date.weekday(),
            start_time=time(9, 0),
            end_time=time(11, 0),
            slot_duration_min=30,
        )
        self.patient = Patient.objects.create(
            clinic=self.clinic,
            first_name="Ali",
            last_name="Hamza",
            phone="+15551234567",
            email="ali@example.com",
            is_verified=True,
        )
        self.chat_session = ChatSession.objects.create(
            clinic=self.clinic,
            session_token="tok-auth-skip-1",
            status=ChatSessionStatus.ACTIVE,
            patient=self.patient,
            is_authenticated=True,
        )
        start = datetime(
            self.target_date.year,
            self.target_date.month,
            self.target_date.day,
            9,
            0,
            tzinfo=_TZ,
        )
        end = start + timedelta(minutes=30)
        self.slot_start = start.isoformat()
        self.slot_end = end.isoformat()

    def test_select_time_skips_details_to_review_when_authenticated(self):
        started = BookingService.start(
            clinic=self.clinic, chat_session=self.chat_session
        )
        result = BookingService.apply_step(
            clinic=self.clinic,
            chat_session=self.chat_session,
            booking_id=started["booking_id"],
            action="select_time",
            value={
                "start": self.slot_start,
                "end": self.slot_end,
                "doctor_id": str(self.doctor.id),
                "doctor": self.doctor.full_name,
            },
        )
        self.assertEqual(result["step"], BookingStep.REVIEW.value)
        self.assertEqual(result["review"]["first_name"], "Ali")
        # Landing on review must not itself create the appointment — only
        # an explicit confirm_review action does.
        self.assertFalse(
            Appointment.objects.filter(clinic=self.clinic, patient=self.patient).exists()
        )

    def test_review_progress_excludes_steps_this_session_never_shows(self):
        """Regression: an authenticated, slot-prefilled booking landed on
        REVIEW reporting "Step 6 of 6" — the full choose_doctor step count
        including DETAILS and OTP, neither of which this session ever
        actually showed. Progress must reflect only the steps this session
        can show (DOCTOR, DATE, TIME, REVIEW = 4), not the abstract mode
        list, so a patient's very first screen isn't mislabeled as the
        tail end of a sequence they never saw the start of."""
        result = BookingService.start(
            clinic=self.clinic,
            chat_session=self.chat_session,
            doctor_id=str(self.doctor.id),
            doctor_name=self.doctor.full_name,
            slot_start=self.slot_start,
            slot_end=self.slot_end,
        )
        self.assertEqual(result["step"], BookingStep.REVIEW.value)
        self.assertEqual(result["progress"], {"current": 4, "total": 4})

    def test_confirm_review_creates_the_appointment(self):
        """The actual new behavior: picking a time only ever *holds* it for
        an authenticated patient now — the real Appointment is created
        exactly once, on the explicit confirm_review tap, never before."""
        started = BookingService.start(
            clinic=self.clinic, chat_session=self.chat_session
        )
        reviewed = BookingService.apply_step(
            clinic=self.clinic,
            chat_session=self.chat_session,
            booking_id=started["booking_id"],
            action="select_time",
            value={
                "start": self.slot_start,
                "end": self.slot_end,
                "doctor_id": str(self.doctor.id),
                "doctor": self.doctor.full_name,
            },
        )
        self.assertEqual(reviewed["step"], BookingStep.REVIEW.value)

        result = BookingService.apply_step(
            clinic=self.clinic,
            chat_session=self.chat_session,
            booking_id=started["booking_id"],
            action="confirm_review",
            value={},
        )
        self.assertEqual(result["step"], BookingStep.CONFIRMED.value)
        self.assertEqual(result["confirmation"]["first_name"], "Ali")
        self.assertTrue(
            Appointment.objects.filter(
                clinic=self.clinic,
                patient=self.patient,
                status=AppointmentStatus.CONFIRMED,
            ).exists()
        )

    def test_confirm_review_rejected_before_review_step_reached(self):
        """A client can't skip straight to confirm_review from an earlier
        step — there must be something real to confirm."""
        started = BookingService.start(
            clinic=self.clinic, chat_session=self.chat_session
        )
        with self.assertRaises(BookingError):
            BookingService.apply_step(
                clinic=self.clinic,
                chat_session=self.chat_session,
                booking_id=started["booking_id"],
                action="confirm_review",
                value={},
            )

    def test_slot_prefill_start_skips_details_to_review_when_authenticated(self):
        """Availability-card / hero deep-link into start(slot_*) must also skip
        straight to REVIEW, not all the way to a committed appointment."""
        result = BookingService.start(
            clinic=self.clinic,
            chat_session=self.chat_session,
            doctor_id=str(self.doctor.id),
            doctor_name=self.doctor.full_name,
            slot_start=self.slot_start,
            slot_end=self.slot_end,
        )
        self.assertEqual(result["step"], BookingStep.REVIEW.value)
        self.assertEqual(result["review"]["first_name"], "Ali")
        self.assertFalse(
            Appointment.objects.filter(clinic=self.clinic, patient=self.patient).exists()
        )

    def test_back_from_review_skips_details_and_otp_straight_to_time_when_authenticated(
        self,
    ):
        """Review's Back button must honor the same skip invariant as the
        forward path — an authenticated patient was never shown DETAILS or
        OTP (see _route_to_review_if_authenticated skips *both*), so Back
        must not stop at either. Landing on DETAILS alone was tried first
        and confirmed wrong live: re-picking a time from the step before it
        skipped straight past DETAILS to REVIEW again, proving DETAILS was
        never a real stop for this session — just a Back-only dead end that
        asked an already-verified patient to re-enter contact info."""
        started = BookingService.start(
            clinic=self.clinic,
            chat_session=self.chat_session,
            doctor_id=str(self.doctor.id),
            doctor_name=self.doctor.full_name,
            slot_start=self.slot_start,
            slot_end=self.slot_end,
        )
        self.assertEqual(started["step"], BookingStep.REVIEW.value)

        result = BookingService.apply_step(
            clinic=self.clinic,
            chat_session=self.chat_session,
            booking_id=started["booking_id"],
            action="back",
            value={},
        )
        self.assertEqual(result["step"], BookingStep.TIME.value)
        self.assertEqual(result["options"]["doctor_name"], self.doctor.full_name)
        self.assertTrue(result["options"]["slots"])

        # And picking a time from here must route straight back to REVIEW
        # again, not resurrect a DETAILS stop — closing the loop the live
        # report found.
        reselected = BookingService.apply_step(
            clinic=self.clinic,
            chat_session=self.chat_session,
            booking_id=started["booking_id"],
            action="select_time",
            value={
                "start": self.slot_start,
                "end": self.slot_end,
                "doctor_id": str(self.doctor.id),
                "doctor": self.doctor.full_name,
            },
        )
        self.assertEqual(reselected["step"], BookingStep.REVIEW.value)

    def test_back_from_otp_itself_still_lands_on_details_when_unauthenticated(self):
        """The skip-OTP-on-back fix only applies when going back *from
        REVIEW* (where OTP was never actually shown). A patient genuinely
        sitting on the OTP step and tapping Back must land on DETAILS as
        before — REVIEW is never reached after a real OTP step (entering
        the code calls confirm() directly), so this is the only "back"
        exercised in the normal, non-skip flow."""
        self.chat_session.is_authenticated = False
        self.chat_session.patient = None
        self.chat_session.save(update_fields=["is_authenticated", "patient"])
        started = BookingService.start(
            clinic=self.clinic,
            chat_session=self.chat_session,
            doctor_id=str(self.doctor.id),
            doctor_name=self.doctor.full_name,
            slot_start=self.slot_start,
            slot_end=self.slot_end,
        )
        self.assertEqual(started["step"], BookingStep.DETAILS.value)
        submitted = BookingService.apply_step(
            clinic=self.clinic,
            chat_session=self.chat_session,
            booking_id=started["booking_id"],
            action="submit_details",
            value={
                "first_name": "Sam",
                "phone": "+15559990000",
                "email": "sam@example.com",
                "date_of_birth": "1990-01-01",
            },
        )
        self.assertEqual(submitted["step"], BookingStep.OTP.value)

        result = BookingService.apply_step(
            clinic=self.clinic,
            chat_session=self.chat_session,
            booking_id=started["booking_id"],
            action="back",
            value={},
        )
        self.assertEqual(result["step"], BookingStep.DETAILS.value)

    def test_unauthenticated_still_lands_on_details(self):
        self.chat_session.is_authenticated = False
        self.chat_session.patient = None
        self.chat_session.save(update_fields=["is_authenticated", "patient"])
        result = BookingService.start(
            clinic=self.clinic,
            chat_session=self.chat_session,
            doctor_id=str(self.doctor.id),
            doctor_name=self.doctor.full_name,
            slot_start=self.slot_start,
            slot_end=self.slot_end,
        )
        self.assertEqual(result["step"], BookingStep.DETAILS.value)

    def test_email_only_patient_does_not_leak_placeholder_phone(self):
        email = "email-only@example.com"
        email_patient = Patient.objects.create(
            clinic=self.clinic,
            first_name="Eve",
            last_name="Mail",
            phone=patient_service.email_placeholder_phone(email),
            email=email,
            is_verified=True,
        )
        self.chat_session.patient = email_patient
        self.chat_session.is_authenticated = True
        self.chat_session.save(update_fields=["patient", "is_authenticated"])

        result = BookingService.start(
            clinic=self.clinic,
            chat_session=self.chat_session,
            doctor_id=str(self.doctor.id),
            doctor_name=self.doctor.full_name,
            slot_start=self.slot_start,
            slot_end=self.slot_end,
        )
        self.assertEqual(result["step"], BookingStep.REVIEW.value)
        self.chat_session.refresh_from_db()
        booking = self.chat_session.conversation_context["booking"]
        self.assertEqual(booking["patient_email"], email)
        self.assertFalse((booking.get("patient_phone") or "").startswith("email:"))


class NoVerificationModeReviewTests(TestCase):
    """The clinic's second zero-review bypass: verification_mode="none"
    used to call BookingService.confirm() directly from submit_details, the
    instant contact details were typed in — no OTP, no review, nothing.
    Same fix as the authenticated-session bypass above: land on REVIEW and
    require an explicit confirm_review action."""

    def setUp(self):
        from apps.widget.models import WidgetSettings

        self.clinic = Clinic.objects.create(
            slug="no-verify-clinic",
            name="No Verify Clinic",
            email="no-verify@clinic.com",
            phone="+12125550101",
            timezone="America/New_York",
        )
        WidgetSettings.objects.create(
            clinic=self.clinic,
            configuration={"booking": {"verification_mode": "none"}},
        )
        self.doctor = Doctor.objects.create(clinic=self.clinic, full_name="Dr. Open")
        self.target_date = _next_weekday(timezone.localdate().weekday(), from_days_ahead=1)
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
            session_token="tok-no-verify-1",
            status=ChatSessionStatus.ACTIVE,
            is_authenticated=False,
        )
        start = datetime(
            self.target_date.year,
            self.target_date.month,
            self.target_date.day,
            9,
            0,
            tzinfo=_TZ,
        )
        end = start + timedelta(minutes=30)
        self.slot_start = start.isoformat()
        self.slot_end = end.isoformat()

    def test_submit_details_lands_on_review_not_confirmed(self):
        started = BookingService.start(
            clinic=self.clinic,
            chat_session=self.chat_session,
            doctor_id=str(self.doctor.id),
            doctor_name=self.doctor.full_name,
            slot_start=self.slot_start,
            slot_end=self.slot_end,
        )
        self.assertEqual(started["step"], BookingStep.DETAILS.value)

        result = BookingService.apply_step(
            clinic=self.clinic,
            chat_session=self.chat_session,
            booking_id=started["booking_id"],
            action="submit_details",
            value={
                "first_name": "Sam",
                "phone": "+15559990000",
                "date_of_birth": "1990-01-01",
            },
        )
        self.assertEqual(result["step"], BookingStep.REVIEW.value)
        self.assertFalse(Appointment.objects.filter(clinic=self.clinic).exists())

    def test_back_from_review_skips_otp_straight_to_details(self):
        """Same invariant as the authenticated-session case: OTP was never
        shown for a verification_mode="none" clinic, so Back from REVIEW
        must land on DETAILS (with the typed-in details preserved), not
        strand the patient on an OTP screen this clinic doesn't even use."""
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
            value={
                "first_name": "Sam",
                "phone": "+15559990000",
                "date_of_birth": "1990-01-01",
            },
        )
        self.assertEqual(submitted["step"], BookingStep.REVIEW.value)

        result = BookingService.apply_step(
            clinic=self.clinic,
            chat_session=self.chat_session,
            booking_id=started["booking_id"],
            action="back",
            value={},
        )
        self.assertEqual(result["step"], BookingStep.DETAILS.value)
        self.assertEqual(result["options"]["first_name"], "Sam")

    def test_confirm_review_then_creates_the_appointment(self):
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
                "phone": "+15559990000",
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
        self.assertTrue(
            Appointment.objects.filter(
                clinic=self.clinic, status=AppointmentStatus.CONFIRMED
            ).exists()
        )

    def test_confirm_review_persists_a_confirmation_chat_message(self):
        """BookingService.confirm() is its own API call, separate from the
        normal chat pipeline — without persist_confirmation_message, a
        confirmed booking left zero trace in the transcript, so a later
        /chat/resume could only ever replay the original wizard-launch
        card, which has no memory of ever completing."""
        from apps.chatbot.models import ChatMessage

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
                "phone": "+15559990000",
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
        confirmation_code = result["confirmation"]["confirmation_code"]

        messages = ChatMessage.objects.filter(session=self.chat_session)
        confirmation_messages = [
            m for m in messages if "confirmation" in (m.metadata or {})
        ]
        self.assertEqual(len(confirmation_messages), 1)
        saved = confirmation_messages[0].metadata["confirmation"]
        self.assertEqual(saved["confirmation_code"], confirmation_code)
        self.assertEqual(saved["doctor_name"], self.doctor.full_name)
        self.assertIn(self.doctor.full_name, confirmation_messages[0].content)
