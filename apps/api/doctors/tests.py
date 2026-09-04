"""Doctor available-slots endpoint.

Powers the staff dashboard's manual "New appointment" dialog, which
previously only showed a doctor's recurring weekly hours as inert text
with no real availability/conflict check at all (see ROADMAP.md). Reuses
apps.chatbot.booking.slots.compute_slots_for_day, the same slot-
computation core the patient-facing chatbot booking flow already relies
on -- these tests cover the API wiring, not the slot math itself (already
covered by test_booking_slots.py).
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.test import TestCase
from django.utils import timezone

from apps.appointments.tests.factories import AppointmentWorld

LA = ZoneInfo("America/Los_Angeles")


def _next_weekday(after_days: int = 1) -> datetime.date:
    """A real, always-in-the-future Mon-Fri date -- AppointmentWorld's
    doctors have schedule rows for day_of_week 0-4 (Mon-Fri) only.
    Deliberately not the factory's fixed SLOT_START constant: that date is
    only meaningful relative to other fixed-time rows, and drifts into the
    past as wall-clock time advances -- exactly the kind of date-flake
    this repo already has one documented instance of (see ROADMAP.md /
    test_temporal_authority.py). compute_slots_for_day filters out any
    slot before "now", so this endpoint's tests need a date guaranteed to
    still be in the future whenever they run."""
    d = (timezone.now().astimezone(LA) + timedelta(days=after_days)).date()
    while d.weekday() > 4:
        d += timedelta(days=1)
    return d


class AvailableSlotsTests(TestCase):
    def setUp(self):
        self.world = AppointmentWorld(slug="slots-a", email="slots-a@test.com")
        self.target_date = _next_weekday()
        self.slot_start = datetime.combine(self.target_date, time(10, 0), tzinfo=LA)
        self.slot_end = self.slot_start + timedelta(minutes=30)

    def _url(self, doctor_id, **params):
        query = f"?date={self.target_date.isoformat()}"
        for key, value in params.items():
            query += f"&{key}={value}"
        return f"/api/v1/doctors/{doctor_id}/available-slots{query}"

    def test_returns_slots_from_schedule(self):
        resp = self.client.get(
            self._url(self.world.doctor_a.id), headers=self.world.headers
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        slots = resp.json()
        self.assertTrue(len(slots) > 0)
        self.assertIn("start", slots[0])
        self.assertIn("label", slots[0])

    def test_booked_slot_is_excluded(self):
        self.world.create_row(start_time=self.slot_start, end_time=self.slot_end)
        resp = self.client.get(
            self._url(self.world.doctor_a.id), headers=self.world.headers
        )
        starts = {s["start"] for s in resp.json()}
        self.assertNotIn(self.slot_start.isoformat(), starts)

    def test_editing_appointment_still_shows_its_own_slot(self):
        appt = self.world.create_row(start_time=self.slot_start, end_time=self.slot_end)
        resp = self.client.get(
            self._url(self.world.doctor_a.id, exclude_appointment_id=appt.id),
            headers=self.world.headers,
        )
        starts = {s["start"] for s in resp.json()}
        self.assertIn(self.slot_start.isoformat(), starts)

    def test_other_doctor_unaffected_by_booking(self):
        self.world.create_row(start_time=self.slot_start, end_time=self.slot_end)
        resp = self.client.get(
            self._url(self.world.doctor_b.id), headers=self.world.headers
        )
        starts = {s["start"] for s in resp.json()}
        self.assertIn(self.slot_start.isoformat(), starts)

    def test_invalid_date_rejected(self):
        resp = self.client.get(
            f"/api/v1/doctors/{self.world.doctor_a.id}/available-slots?date=not-a-date",
            headers=self.world.headers,
        )
        self.assertEqual(resp.status_code, 400)

    def test_unauthenticated_rejected(self):
        resp = self.client.get(self._url(self.world.doctor_a.id))
        self.assertEqual(resp.status_code, 401)
