"""booking/slots.py: consolidated slot generation used by both the booking
wizard (serializers._slots_for_day) and the conversational availability
handler (sql_tool.handlers.doctors.doctor_availability)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.test import TestCase
from django.utils import timezone

_TZ = ZoneInfo("America/New_York")

from apps.appointments.models import Appointment, AppointmentStatus
from apps.chatbot.booking.service import BookingService
from apps.chatbot.booking.slots import active_holds_for_date, compute_slots_for_day
from apps.chatbot.booking.state import BookingStep
from apps.chatbot.models import ChatSession, ChatSessionStatus
from apps.clinics.models import Clinic
from apps.doctors.models import Doctor, DoctorLeave, DoctorSchedule
from apps.patients.models import Patient
from apps.services.models import Service


def _next_weekday(weekday: int, *, from_days_ahead: int = 3) -> date:
    """A date at least `from_days_ahead` out (avoids the 'skip past times for
    today' cutoff) that falls on the given weekday (0=Monday)."""
    d = timezone.localdate() + timedelta(days=from_days_ahead)
    while d.weekday() != weekday:
        d += timedelta(days=1)
    return d


class ComputeSlotsForDayTests(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="slots-clinic",
            name="Slots Clinic",
            email="slots@clinic.com",
            phone="+12125550002",
            timezone="America/New_York",
        )
        self.doctor = Doctor.objects.create(
            clinic=self.clinic, full_name="Dr. Slot Test", is_active=True
        )
        self.target_date = _next_weekday(0)  # a Monday, safely in the future
        DoctorSchedule.objects.create(
            clinic=self.clinic,
            doctor=self.doctor,
            day_of_week=self.target_date.weekday(),
            start_time=time(9, 0),
            end_time=time(11, 0),
            slot_duration_min=30,
        )

    def test_generates_slots_from_schedule(self):
        slots = compute_slots_for_day(
            self.clinic, target_date=self.target_date, doctors=[self.doctor]
        )
        # 09:00-11:00 in 30-min increments = 4 slots
        self.assertEqual(len(slots), 4)
        self.assertEqual(slots[0]["doctor_id"], str(self.doctor.id))

    def test_no_schedule_that_day_returns_empty(self):
        other_day = self.target_date + timedelta(days=1)
        slots = compute_slots_for_day(
            self.clinic, target_date=other_day, doctors=[self.doctor]
        )
        self.assertEqual(slots, [])

    def test_leave_excludes_doctor_entirely(self):
        tz_start = datetime.combine(self.target_date, time.min, tzinfo=_TZ)
        tz_end = datetime.combine(self.target_date, time.max, tzinfo=_TZ)
        DoctorLeave.objects.create(
            clinic=self.clinic,
            doctor=self.doctor,
            start_at=tz_start,
            end_at=tz_end,
            is_active=True,
        )
        slots = compute_slots_for_day(
            self.clinic, target_date=self.target_date, doctors=[self.doctor]
        )
        self.assertEqual(slots, [])

    def test_existing_appointment_removes_that_slot(self):
        patient = Patient.objects.create(
            clinic=self.clinic, first_name="Pat", last_name="Ient", phone="+15551234567"
        )
        start = datetime.combine(self.target_date, time(9, 0), tzinfo=_TZ)
        Appointment.objects.create(
            clinic=self.clinic,
            doctor=self.doctor,
            patient=patient,
            start_time=start,
            end_time=start + timedelta(minutes=30),
            status=AppointmentStatus.CONFIRMED,
        )
        slots = compute_slots_for_day(
            self.clinic, target_date=self.target_date, doctors=[self.doctor]
        )
        self.assertEqual(len(slots), 3)
        self.assertNotIn("09:00 AM", [s["label"] for s in slots])

    def test_midnight_open_is_treated_as_nine_am(self):
        DoctorSchedule.objects.filter(doctor=self.doctor).update(
            start_time=time(0, 0), end_time=time(17, 0)
        )
        slots = compute_slots_for_day(
            self.clinic, target_date=self.target_date, doctors=[self.doctor]
        )
        labels = [s["label"] for s in slots]
        self.assertTrue(labels)
        self.assertNotIn("12:00 AM", labels)
        self.assertEqual(labels[0], "09:00 AM")

    def test_excluded_keys_removes_held_slot(self):
        start = datetime.combine(self.target_date, time(9, 0), tzinfo=_TZ)
        key = f"{self.doctor.id}|{start.isoformat()}"
        slots = compute_slots_for_day(
            self.clinic,
            target_date=self.target_date,
            doctors=[self.doctor],
            excluded_keys={key},
        )
        self.assertEqual(len(slots), 3)

    def test_max_slots_caps_output(self):
        slots = compute_slots_for_day(
            self.clinic, target_date=self.target_date, doctors=[self.doctor], max_slots=2
        )
        self.assertLessEqual(len(slots), 2)


class PerDoctorSlotIsolationTests(TestCase):
    """Each doctor must own their own timetable. Selecting or generating
    slots for Dr. A on a day must not leak Dr. B's hours, even when both
    are free at the same clock time."""

    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="per-doc-slots",
            name="Per Doctor Clinic",
            email="perdoc@clinic.com",
            phone="+12125550022",
            timezone="America/New_York",
        )
        self.morning_doc = Doctor.objects.create(
            clinic=self.clinic, full_name="Dr. Morning", is_active=True
        )
        self.afternoon_doc = Doctor.objects.create(
            clinic=self.clinic, full_name="Dr. Afternoon", is_active=True
        )
        self.overlap_doc = Doctor.objects.create(
            clinic=self.clinic, full_name="Dr. Overlap", is_active=True
        )
        self.target_date = _next_weekday(0)
        weekday = self.target_date.weekday()
        DoctorSchedule.objects.create(
            clinic=self.clinic,
            doctor=self.morning_doc,
            day_of_week=weekday,
            start_time=time(9, 0),
            end_time=time(11, 0),
            slot_duration_min=30,
        )
        DoctorSchedule.objects.create(
            clinic=self.clinic,
            doctor=self.afternoon_doc,
            day_of_week=weekday,
            start_time=time(14, 0),
            end_time=time(16, 0),
            slot_duration_min=30,
        )
        DoctorSchedule.objects.create(
            clinic=self.clinic,
            doctor=self.overlap_doc,
            day_of_week=weekday,
            start_time=time(9, 0),
            end_time=time(11, 0),
            slot_duration_min=30,
        )

    def test_compute_slots_tags_each_row_with_its_doctor(self):
        slots = compute_slots_for_day(
            self.clinic,
            target_date=self.target_date,
            doctors=[self.morning_doc, self.afternoon_doc],
        )
        by_doctor = {}
        for slot in slots:
            by_doctor.setdefault(slot["doctor_id"], set()).add(slot["label"])
        self.assertEqual(
            by_doctor[str(self.morning_doc.id)],
            {"09:00 AM", "09:30 AM", "10:00 AM", "10:30 AM"},
        )
        self.assertEqual(
            by_doctor[str(self.afternoon_doc.id)],
            {"02:00 PM", "02:30 PM", "03:00 PM", "03:30 PM"},
        )

    def test_slots_for_one_doctor_do_not_include_the_other(self):
        from apps.chatbot.booking.serializers import _slots_for_day

        morning = _slots_for_day(
            self.clinic,
            target_date=self.target_date,
            doctor_id=str(self.morning_doc.id),
            service_id=None,
            mode="choose_doctor",
        )
        afternoon = _slots_for_day(
            self.clinic,
            target_date=self.target_date,
            doctor_id=str(self.afternoon_doc.id),
            service_id=None,
            mode="choose_doctor",
        )
        self.assertTrue(morning)
        self.assertTrue(afternoon)
        self.assertTrue(all(s["doctor_id"] == str(self.morning_doc.id) for s in morning))
        self.assertTrue(all(s["doctor_id"] == str(self.afternoon_doc.id) for s in afternoon))
        self.assertTrue(
            {s["label"] for s in morning}.isdisjoint({s["label"] for s in afternoon})
        )

    def test_overlapping_clock_times_have_distinct_ids_and_holds(self):
        from apps.chatbot.booking.serializers import _slots_for_day

        morning = _slots_for_day(
            self.clinic,
            target_date=self.target_date,
            doctor_id=str(self.morning_doc.id),
            service_id=None,
            mode="choose_doctor",
        )
        overlap = _slots_for_day(
            self.clinic,
            target_date=self.target_date,
            doctor_id=str(self.overlap_doc.id),
            service_id=None,
            mode="choose_doctor",
        )
        morning_ids = {s["id"] for s in morning}
        overlap_ids = {s["id"] for s in overlap}
        self.assertTrue(morning_ids)
        self.assertTrue(overlap_ids)
        self.assertTrue(morning_ids.isdisjoint(overlap_ids))

        held_start = next(s for s in morning if s["label"] == "09:00 AM")
        held = compute_slots_for_day(
            self.clinic,
            target_date=self.target_date,
            doctors=[self.overlap_doc],
            excluded_keys={f"{self.morning_doc.id}|{held_start['start']}"},
        )
        self.assertIn("09:00 AM", [s["label"] for s in held])

    def test_time_options_follow_the_pinned_doctor(self):
        from apps.chatbot.booking.serializers import _time_options
        from apps.chatbot.booking.state import BookingSession

        session = BookingSession(
            booking_id="test-time-options",
            clinic_id=str(self.clinic.id),
            mode="choose_doctor",
            step="time",
            doctor_id=str(self.afternoon_doc.id),
            doctor_name="Dr. Afternoon",
            date=self.target_date.isoformat(),
            show_all_times=True,
        )
        options = _time_options(self.clinic, session, {"max_slots_preview": 40})
        slots = options["slots"]
        self.assertTrue(slots)
        self.assertTrue(all(s["doctor_id"] == str(self.afternoon_doc.id) for s in slots))
        self.assertNotIn("09:00 AM", [s["label"] for s in slots])
        self.assertEqual(options["doctor_name"], "Dr. Afternoon")


class WizardPerDoctorTimeStepTests(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="wizard-per-doc",
            name="Wizard Per Doc",
            email="wizard-per-doc@clinic.com",
            phone="+12125550023",
            timezone="America/New_York",
        )
        self.doc_a = Doctor.objects.create(
            clinic=self.clinic, full_name="Dr. Alpha", is_active=True
        )
        self.doc_b = Doctor.objects.create(
            clinic=self.clinic, full_name="Dr. Beta", is_active=True
        )
        self.target_date = _next_weekday(0)
        weekday = self.target_date.weekday()
        DoctorSchedule.objects.create(
            clinic=self.clinic,
            doctor=self.doc_a,
            day_of_week=weekday,
            start_time=time(9, 0),
            end_time=time(10, 0),
            slot_duration_min=30,
        )
        DoctorSchedule.objects.create(
            clinic=self.clinic,
            doctor=self.doc_b,
            day_of_week=weekday,
            start_time=time(15, 0),
            end_time=time(16, 0),
            slot_duration_min=30,
        )
        self.chat_session = ChatSession.objects.create(
            clinic=self.clinic,
            session_token="tok-per-doc",
            status=ChatSessionStatus.ACTIVE,
        )

    def _times_for(self, doctor: Doctor) -> list[dict]:
        started = BookingService.start(
            clinic=self.clinic,
            chat_session=self.chat_session,
            doctor_id=str(doctor.id),
            doctor_name=doctor.full_name,
        )
        dated = BookingService.apply_step(
            clinic=self.clinic,
            chat_session=self.chat_session,
            booking_id=started["booking_id"],
            action="select_date",
            value={"date": self.target_date.isoformat()},
        )
        self.assertEqual(dated["step"], BookingStep.TIME.value)
        return dated["options"]["slots"]

    def test_switching_doctor_loads_that_doctors_slots_only(self):
        slots_a = self._times_for(self.doc_a)
        self.assertTrue(all(s["doctor_id"] == str(self.doc_a.id) for s in slots_a))
        self.assertEqual({s["label"] for s in slots_a}, {"09:00 AM", "09:30 AM"})

        slots_b = self._times_for(self.doc_b)
        self.assertTrue(all(s["doctor_id"] == str(self.doc_b.id) for s in slots_b))
        self.assertEqual({s["label"] for s in slots_b}, {"03:00 PM", "03:30 PM"})
        self.assertTrue(
            {s["id"] for s in slots_a}.isdisjoint({s["id"] for s in slots_b})
        )


class ActiveHoldsForDateTests(TestCase):
    def test_no_active_sessions_returns_empty_set(self):
        clinic = Clinic.objects.create(
            slug="holds-clinic",
            name="Holds Clinic",
            email="holds@clinic.com",
            phone="+12125550003",
            timezone="America/New_York",
        )
        held = active_holds_for_date(clinic, timezone.localdate())
        self.assertEqual(held, set())

    def test_a_real_hold_is_not_lost_among_many_dormant_sessions(self):
        """Live-confirmed at a real clinic with 400+ ACTIVE ChatSessions:
        the scan behind active_holds_for_date used to be capped at 200
        rows with no ordering, so the DB was free to return any 200 of
        them -- a genuinely live hold could be silently excluded, letting
        that "held" slot be double-booked out from under the patient
        holding it. A hold can only exist on a session touched within the
        hold window, so ordering by most-recently-active first must
        always surface it regardless of how many older, dormant sessions
        exist."""
        clinic = Clinic.objects.create(
            slug="holds-scale-clinic",
            name="Holds Scale Clinic",
            email="holds-scale@clinic.com",
            phone="+12125550005",
            timezone="America/New_York",
        )
        target_date = timezone.localdate() + timedelta(days=3)
        held_start = timezone.make_aware(
            datetime.combine(target_date, time(9, 0)), _TZ
        )

        # 250 old, dormant sessions with no hold at all -- more than the
        # scan's [:200] cap, and all with an older last_active_at than the
        # one real hold below.
        old = timezone.now() - timedelta(days=1)
        ChatSession.objects.bulk_create(
            [
                ChatSession(
                    clinic=clinic,
                    session_token=f"dormant-{i}",
                    status=ChatSessionStatus.ACTIVE,
                    conversation_context={},
                    last_active_at=old,
                )
                for i in range(250)
            ]
        )

        ChatSession.objects.create(
            clinic=clinic,
            session_token="the-real-hold",
            status=ChatSessionStatus.ACTIVE,
            conversation_context={
                "booking": {
                    "doctor_id": "doc-1",
                    "slot_start": held_start.isoformat(),
                    "hold_expires_at": (timezone.now() + timedelta(minutes=10)).isoformat(),
                }
            },
            last_active_at=timezone.now(),
        )

        held = active_holds_for_date(clinic, target_date)
        self.assertIn(
            f"doc-1|{held_start.replace(second=0, microsecond=0).isoformat()}", held
        )


class BackFromDetailsReleasesHoldTests(TestCase):
    """Live-confirmed: picking a time held it (correctly), but clicking
    Back off of the DETAILS screen never released that hold -- so the time
    list Back returned to still excluded the just-abandoned slot as if
    someone else were holding it, until a *different* slot was picked and
    overwrote the stale hold. The patient going Back is explicitly
    un-picking that time."""

    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="back-hold-clinic",
            name="Back Hold Clinic",
            email="back-hold@clinic.com",
            phone="+12125550006",
            timezone="America/New_York",
        )
        self.doctor = Doctor.objects.create(
            clinic=self.clinic, full_name="Dr. Back Hold", is_active=True
        )
        self.service = Service.objects.create(
            clinic=self.clinic, name="Checkup", duration_min=30, price_cents=10000
        )
        self.target_date = _next_weekday(0)
        DoctorSchedule.objects.create(
            clinic=self.clinic,
            doctor=self.doctor,
            day_of_week=self.target_date.weekday(),
            start_time=time(9, 0),
            end_time=time(11, 0),
            slot_duration_min=30,
        )
        self.chat_session = ChatSession.objects.create(
            clinic=self.clinic, session_token="tok-back-hold", status=ChatSessionStatus.ACTIVE
        )

    def test_back_from_details_clears_the_slot_and_hold(self):
        start = BookingService.start(
            clinic=self.clinic, chat_session=self.chat_session,
            doctor_id=str(self.doctor.id), doctor_name=self.doctor.full_name,
            service_id=str(self.service.id), service_name=self.service.name,
        )
        booking_id = start["booking_id"]
        self.chat_session.refresh_from_db()
        step1 = BookingService.apply_step(
            clinic=self.clinic, chat_session=self.chat_session, booking_id=booking_id,
            action="select_date", value={"date": self.target_date.isoformat()},
        )
        slots = step1["options"]["slots"]
        target = slots[0]

        step2 = BookingService.apply_step(
            clinic=self.clinic, chat_session=self.chat_session, booking_id=booking_id,
            action="select_time",
            value={"start": target["start"], "end": target["end"], "doctor_id": str(self.doctor.id)},
        )
        self.assertEqual(step2["step"], BookingStep.DETAILS.value)

        held_while_on_details = active_holds_for_date(self.clinic, self.target_date)
        self.assertTrue(held_while_on_details, "the picked slot should be held")

        step3 = BookingService.apply_step(
            clinic=self.clinic, chat_session=self.chat_session, booking_id=booking_id,
            action="back", value={},
        )
        self.assertEqual(step3["step"], BookingStep.TIME.value)

        held_after_back = active_holds_for_date(self.clinic, self.target_date)
        self.assertEqual(
            held_after_back, set(), "Back must release the abandoned slot's hold"
        )
        times_after_back = [s["time"] for s in step3["options"]["slots"]]
        self.assertIn(target["time"], times_after_back)
