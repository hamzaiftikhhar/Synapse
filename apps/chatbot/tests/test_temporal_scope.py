"""Temporal availability correctness.

Production transcript: asking "is there any appointment available in December
12 morning" on 2026-08-18 returned August slots. The NLU had emitted
``["2023-12-12", "december 12"]`` and the handler took ``dates[0]``, so a year
the patient never typed decided the search; bare months ("November") parsed to
nothing and silently became tomorrow. These tests pin the resolution rules and
the scope guarantee that the answer and the chips both depend on.
"""

from __future__ import annotations

from datetime import date, time, timedelta
from zoneinfo import ZoneInfo

from django.test import TestCase
from django.utils import timezone

from apps.chatbot.nlu.schemas import ExtractedEntities, Intent, NLUResult, ResolvedIds
from apps.chatbot.sql_tool.base import SQLContext
from apps.chatbot.sql_tool.formatter import format_sql_results
from apps.chatbot.sql_tool.handlers.doctors import doctor_availability
from apps.chatbot.temporal import (
    TemporalStatus,
    day_label,
    resolve_temporal_query,
)
from apps.chatbot.ui_meta import build_ui_meta
from apps.clinics.models import Clinic
from apps.doctors.models import Doctor, DoctorSchedule

_TZ = ZoneInfo("America/Los_Angeles")
# A fixed Tuesday, so "December 12" and "December 15" have stable weekdays.
_TODAY = date(2026, 8, 18)
_HORIZON = 30


def _resolve(entities, *, message="", today=_TODAY, horizon=_HORIZON):
    return resolve_temporal_query(
        date_entities=entities,
        today=today,
        horizon_days=horizon,
        message=message,
        tz=_TZ,
    )


class HallucinatedDateTests(TestCase):
    """A normalized date the patient never typed must not win."""

    def test_model_invented_year_loses_to_the_patients_own_words(self):
        scope = _resolve(
            ["2023-12-12", "december 12"],
            message="is there any appointment available in December 12 morning",
        )
        self.assertEqual(scope.start, date(2026, 12, 12))
        self.assertEqual(scope.scope_label, "Saturday, December 12")

    def test_order_of_the_entity_list_does_not_decide(self):
        message = "is there any appointment available in December 12 morning"
        forward = _resolve(["2023-12-12", "december 12"], message=message)
        reversed_ = _resolve(["december 12", "2023-12-12"], message=message)
        self.assertEqual(forward.start, reversed_.start)
        self.assertEqual(forward.start, date(2026, 12, 12))

    def test_an_ungrounded_past_date_alone_is_not_trusted(self):
        # The message deliberately names no month: this asserts that an ISO
        # date the patient never typed is discarded, not that a month they
        # *did* type gets ignored (see MonthScopeTests for that half).
        scope = _resolve(["2023-12-12"], message="anything available then")
        self.assertIs(scope.status, TemporalStatus.UNRESOLVED)

    def test_a_past_date_the_patient_actually_typed_is_reported_as_past(self):
        scope = _resolve(["2023-12-12"], message="can I come on 2023-12-12")
        self.assertIs(scope.status, TemporalStatus.PAST)

    def test_an_explicit_future_iso_date_is_honoured(self):
        scope = _resolve(
            ["2026-09-02"], message="book me for 2026-09-02", horizon=90
        )
        self.assertIs(scope.status, TemporalStatus.RESOLVED)
        self.assertEqual(scope.start, date(2026, 9, 2))


class MonthScopeTests(TestCase):
    def test_bare_month_becomes_the_whole_month(self):
        scope = _resolve(["November"], message="anything in November", horizon=200)
        self.assertTrue(scope.is_range)
        self.assertEqual(scope.start, date(2026, 11, 1))
        self.assertEqual(scope.end, date(2026, 11, 30))
        self.assertEqual(scope.scope_label, "November 2026")

    def test_december_spans_the_full_month(self):
        scope = _resolve(["December"], message="anything in December", horizon=200)
        self.assertEqual(scope.start, date(2026, 12, 1))
        self.assertEqual(scope.end, date(2026, 12, 31))

    def test_a_month_already_gone_rolls_to_next_year(self):
        scope = _resolve(["February"], message="anything in February", horizon=400)
        self.assertEqual(scope.start, date(2027, 2, 1))
        self.assertEqual(scope.end, date(2027, 2, 28))

    def test_a_month_in_progress_starts_from_today_not_the_first(self):
        scope = _resolve(["August"], message="anything in August", horizon=60)
        self.assertEqual(scope.start, _TODAY)
        self.assertEqual(scope.end, date(2026, 8, 31))

    def test_a_bare_day_of_month_rolls_forward_a_year(self):
        scope = _resolve(["March 3"], message="how about March 3", horizon=400)
        self.assertEqual(scope.start, date(2027, 3, 3))


class NoSilentTomorrowTests(TestCase):
    def test_an_unreadable_constraint_stays_unresolved(self):
        scope = _resolve(["the week after my birthday"], message="the week after my birthday")
        self.assertIs(scope.status, TemporalStatus.UNRESOLVED)
        self.assertIsNone(scope.start)

    def test_no_constraint_at_all_scans_forward_from_tomorrow(self):
        scope = _resolve([], message="any doctor free?")
        self.assertIs(scope.status, TemporalStatus.UNSPECIFIED)
        self.assertEqual(scope.start, _TODAY + timedelta(days=1))
        self.assertEqual(scope.end, _TODAY + timedelta(days=_HORIZON))

    def test_asap_is_a_forward_scan_not_a_parse_failure(self):
        scope = _resolve(["asap"], message="I need something asap")
        self.assertIs(scope.status, TemporalStatus.UNSPECIFIED)

    def test_a_real_date_beats_a_flexible_one_in_the_same_turn(self):
        scope = _resolve(
            ["asap", "monday"], message="asap, monday works", horizon=60
        )
        self.assertIs(scope.status, TemporalStatus.RESOLVED)
        self.assertEqual(scope.start.weekday(), 0)


class BookingHorizonTests(TestCase):
    def test_a_month_past_the_horizon_is_refused_not_redirected(self):
        scope = _resolve(["November"], message="anything in November", horizon=30)
        self.assertIs(scope.status, TemporalStatus.BEYOND_HORIZON)
        self.assertEqual(scope.horizon_end, date(2026, 9, 17))

    def test_a_range_straddling_the_horizon_is_clamped(self):
        scope = _resolve(["September"], message="anything in September", horizon=30)
        self.assertIs(scope.status, TemporalStatus.RESOLVED)
        self.assertEqual(scope.start, date(2026, 9, 1))
        self.assertEqual(scope.end, date(2026, 9, 17))

    def test_declared_default_horizon_is_the_one_applied(self):
        from apps.chatbot.booking.config import (
            DEFAULT_BOOKING_CONFIG,
            get_booking_config,
        )

        clinic = Clinic.objects.create(
            slug="horizon-default-clinic",
            name="Horizon Clinic",
            email="horizon@clinic.com",
            phone="+12125550031",
            timezone="America/Los_Angeles",
        )
        self.assertEqual(
            get_booking_config(clinic)["date_horizon_days"],
            DEFAULT_BOOKING_CONFIG["date_horizon_days"],
        )

    def test_a_blank_stored_horizon_falls_back_to_the_declared_default(self):
        from apps.chatbot.booking.config import (
            DEFAULT_BOOKING_CONFIG,
            get_booking_config,
        )
        from apps.widget.models import WidgetSettings

        clinic = Clinic.objects.create(
            slug="horizon-blank-clinic",
            name="Blank Horizon Clinic",
            email="blank@clinic.com",
            phone="+12125550032",
            timezone="America/Los_Angeles",
        )
        WidgetSettings.objects.create(
            clinic=clinic, configuration={"booking": {"date_horizon_days": 0}}
        )
        self.assertEqual(
            get_booking_config(clinic)["date_horizon_days"],
            DEFAULT_BOOKING_CONFIG["date_horizon_days"],
        )

    def test_a_clinic_can_open_a_longer_horizon(self):
        from apps.chatbot.booking.config import booking_horizon_days
        from apps.widget.models import WidgetSettings

        clinic = Clinic.objects.create(
            slug="horizon-long-clinic",
            name="Long Horizon Clinic",
            email="long@clinic.com",
            phone="+12125550033",
            timezone="America/Los_Angeles",
        )
        WidgetSettings.objects.create(
            clinic=clinic, configuration={"booking": {"date_horizon_days": 180}}
        )
        self.assertEqual(booking_horizon_days(clinic), 180)


class WeekdayDerivationTests(TestCase):
    """The weekday is computed from the canonical date, never asserted by a model."""

    def test_dec_12_2026_is_a_saturday(self):
        self.assertEqual(day_label(date(2026, 12, 12)), "Saturday, December 12")

    def test_dec_15_2026_is_a_tuesday(self):
        self.assertEqual(day_label(date(2026, 12, 15)), "Tuesday, December 15")

    def test_resolved_label_matches_the_canonical_date(self):
        for day in (date(2026, 12, 12), date(2026, 12, 15)):
            scope = _resolve(
                [day.isoformat()], message=f"book {day.isoformat()}", horizon=400
            )
            self.assertEqual(scope.scope_label, f"{day.strftime('%A')}, December {day.day}")


def _nlu(*, dates=None, times=None) -> NLUResult:
    return NLUResult(
        intent=Intent.DOCTOR_AVAILABILITY,
        confidence=0.9,
        entities=ExtractedEntities(date=dates, time=times),
        resolved_ids=ResolvedIds(),
        needs_sql=True,
    )


class AvailabilityHandlerScopeTests(TestCase):
    """The transcript cases, end to end through the SQL handler."""

    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="temporal-clinic",
            name="Temporal Clinic",
            email="temporal@clinic.com",
            phone="+12125550030",
            timezone="America/Los_Angeles",
        )
        self.doctor = Doctor.objects.create(
            clinic=self.clinic,
            full_name="Dr. Temporal",
            is_active=True,
            is_accepting_patients=True,
        )
        for weekday in range(7):
            DoctorSchedule.objects.create(
                clinic=self.clinic,
                doctor=self.doctor,
                day_of_week=weekday,
                start_time=time(9, 0),
                end_time=time(17, 0),
                slot_duration_min=30,
            )

    def _run(self, message, dates=None, times=None):
        return doctor_availability(
            SQLContext(clinic=self.clinic, nlu=_nlu(dates=dates, times=times), message=message)
        )

    def _tomorrow(self):
        return timezone.now().astimezone(_TZ).date() + timedelta(days=1)

    def test_november_is_refused_instead_of_returning_next_week(self):
        result = self._run("is there any appointment available in November", dates=["November"])
        self.assertFalse(result.found)
        self.assertEqual(result.rows, [])
        self.assertEqual(result.meta["temporal_status"], "beyond_horizon")
        self.assertIn("isn't open for booking yet", result.summary)

    def test_december_is_refused_instead_of_returning_next_week(self):
        result = self._run("is there any appointment available in December", dates=["December"])
        self.assertFalse(result.found)
        self.assertEqual(result.rows, [])
        self.assertEqual(result.meta["temporal_status"], "beyond_horizon")

    def test_december_12_morning_never_returns_a_slot_from_this_month(self):
        result = self._run(
            "is there any appointment available in December 12 morning",
            dates=["2023-12-12", "december 12"],
            times=["morning"],
        )
        self.assertEqual(result.rows, [])
        self.assertEqual(result.meta["scope_start"], "2026-12-12")
        self.assertNotIn("August", result.summary)

    def test_december_15_morning_reports_the_correct_weekday(self):
        result = self._run(
            "is there any appointment available in December 15 morning",
            dates=["2023-12-15", "december 15"],
            times=["morning"],
        )
        self.assertEqual(result.meta["scope_label"], "Tuesday, December 15")

    def test_december_12_afternoon_morning_keeps_the_december_scope(self):
        result = self._run(
            "is there any appointment available in December 12 afternoon morning",
            dates=["December 12"],
            times=["afternoon", "morning"],
        )
        self.assertEqual(result.meta["scope_start"], "2026-12-12")

    def test_monday_morning_returns_monday_morning_slots(self):
        result = self._run(
            "is there any appointment available for Monday morning",
            dates=["monday"],
            times=["morning"],
        )
        self.assertTrue(result.found)
        for row in result.rows:
            day = date.fromisoformat(row["date"])
            self.assertEqual(day.weekday(), 0)
            self.assertLess(int(row["start"][11:13]), 12)

    def test_monday_night_finds_nothing_and_says_which_monday(self):
        result = self._run(
            "is there any appointment available for Monday night",
            dates=["monday"],
            times=["night"],
        )
        self.assertFalse(result.found)
        self.assertEqual(result.rows, [])
        self.assertIn("Monday", result.summary)

    def test_every_returned_row_falls_inside_the_resolved_scope(self):
        for message, dates in (
            ("anything monday", ["monday"]),
            ("anything tomorrow", ["tomorrow"]),
            ("any doctor free", None),
        ):
            result = self._run(message, dates=dates)
            start = result.meta["scope_start"]
            end = result.meta["scope_end"]
            for row in result.rows:
                self.assertGreaterEqual(row["date"], start, msg=message)
                self.assertLessEqual(row["date"], end, msg=message)

    def test_unspecified_request_still_finds_the_next_open_day(self):
        result = self._run("any doctor free", dates=None)
        self.assertTrue(result.found)
        self.assertEqual(result.meta["temporal_status"], "unspecified")
        self.assertEqual(result.meta["target_date"], self._tomorrow().isoformat())

    def test_unparseable_constraint_asks_rather_than_answering_for_tomorrow(self):
        result = self._run("some time after my trip", dates=["after my trip"])
        self.assertFalse(result.found)
        self.assertEqual(result.rows, [])
        self.assertEqual(result.meta["temporal_status"], "unresolved")
        self.assertNotIn(self._tomorrow().strftime("%A"), result.summary)


class ScopeReachesTheAnswerAndTheChipsTests(TestCase):
    """A refusal must survive formatting, and no chip may contradict it."""

    def _block(self, **over):
        block = {
            "handler": "doctor_availability",
            "found": False,
            "rows": [],
            "summary": "This clinic is scheduling appointments through Thursday, "
            "September 17, so November 2026 isn't open for booking yet.",
            "meta": {
                "temporal_status": "beyond_horizon",
                "scope_start": "2026-11-01",
                "scope_end": "2026-11-30",
                "authoritative_summary": True,
            },
        }
        block.update(over)
        return block

    def test_horizon_refusal_survives_formatting(self):
        text = format_sql_results([self._block()])
        self.assertIn("isn't open for booking yet", text)
        self.assertNotIn("couldn't retrieve availability", text)

    def test_generic_copy_still_covers_a_summary_less_block(self):
        text = format_sql_results([self._block(summary="", meta={})])
        self.assertIn("couldn't retrieve availability", text)

    def test_out_of_scope_rows_never_become_clickable_chips(self):
        block = self._block(
            found=True,
            rows=[
                {
                    "doctor_id": "d1",
                    "doctor": "Dr. Temporal",
                    "start": "2026-08-19T09:00:00-07:00",
                    "end": "2026-08-19T09:30:00-07:00",
                    "date": "2026-08-19",
                    "time": "09:00 AM",
                }
            ],
        )
        meta = build_ui_meta(
            clinic=None,
            intent="doctor_availability",
            route="sql_only",
            sql_results=[block],
        )
        self.assertFalse(meta.get("time_slots"))
        self.assertFalse(meta.get("recommended"))

    def test_in_scope_rows_still_become_chips(self):
        # A searchable scope is required for any chip at all, so this fixture
        # carries a resolved November scope rather than the refusal used by
        # the negative cases above.
        block = self._block(
            found=True,
            summary="Found 1 available slot(s) on Tuesday, November 3.",
            meta={
                "temporal_status": "resolved",
                "temporal_searchable": True,
                "scope_start": "2026-11-01",
                "scope_end": "2026-11-30",
                "authoritative_summary": True,
            },
            rows=[
                {
                    "doctor_id": "d1",
                    "doctor": "Dr. Temporal",
                    "start": "2026-11-03T09:00:00-08:00",
                    "end": "2026-11-03T09:30:00-08:00",
                    "date": "2026-11-03",
                    "time": "09:00 AM",
                }
            ],
        )
        meta = build_ui_meta(
            clinic=None,
            intent="doctor_availability",
            route="sql_only",
            sql_results=[block],
        )
        self.assertEqual(len(meta.get("time_slots") or []), 1)
        self.assertEqual(meta["time_slots"][0]["date"], "2026-11-03")
